"""Validate and summarize bounded browser observations; never call a paid provider."""

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DATASET = Path(__file__).with_name("data") / "voice-v1.json"
MAX_ARTIFACT_BYTES = 2_000_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Case(StrictModel):
    id: str = Field(pattern=r"^[a-z]+-\d{2}$")
    utterance: str = Field(min_length=1, max_length=500)
    label: Literal["delegate", "direct", "ambiguous"]


class Dataset(StrictModel):
    version: Literal["voice-v1"]
    cases: list[Case] = Field(min_length=30, max_length=30)

    @model_validator(mode="after")
    def unique_cases(self) -> Dataset:
        if len({case.id for case in self.cases}) != 30:
            message = "Case identifiers must be unique"
            raise ValueError(message)
        if Counter(case.label for case in self.cases) != {
            "delegate": 10,
            "direct": 10,
            "ambiguous": 10,
        }:
            message = "Each delegation class requires ten cases"
            raise ValueError(message)
        return self


class Observation(StrictModel):
    case_id: str = Field(pattern=r"^[a-z]+-\d{2}$")
    trial: int = Field(ge=1, le=10)
    outcome: Literal["completed", "timeout", "overlap", "error"]
    failure_stage: Literal["setup", "connect", "playback", "close"] | None = None
    delegated: bool | None = None
    setup_ms: float | None = Field(default=None, ge=0, le=120_000)
    first_audio_ms: float | None = Field(default=None, ge=0, le=120_000)
    turn_ms: float | None = Field(default=None, ge=0, le=120_000)
    input_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    speech_end_ms: float | None = Field(default=None, gt=0, le=10_000)

    @model_validator(mode="after")
    def consistent_timing(self) -> Observation:
        if self.outcome == "completed" and (
            self.first_audio_ms is None or self.turn_ms is None or self.delegated is None
        ):
            message = "Completed observations require timing and delegation evidence"
            raise ValueError(message)
        if self.outcome != "completed" and (
            self.setup_ms is not None or self.first_audio_ms is not None or self.turn_ms is not None
        ):
            message = "Censored observations must not contribute latency samples"
            raise ValueError(message)
        if self.outcome != "completed" and self.delegated is False:
            message = "Censored attempts cannot establish a direct answer"
            raise ValueError(message)
        if (
            self.first_audio_ms is not None
            and self.turn_ms is not None
            and self.turn_ms < self.first_audio_ms
        ):
            message = "Turn completion cannot precede first audio"
            raise ValueError(message)
        return self


class Capture(StrictModel):
    schema_version: Literal[1]
    mode: Literal["offline", "live"]
    provider: Literal["fake", "live", "realtime", "azure"]
    model: str = Field(min_length=1, max_length=100)
    model_source: Literal["scripted", "operator-declared"]
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    working_tree_dirty: bool = False
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    recorded_at: str = Field(min_length=1, max_length=40)
    browser: str = Field(min_length=1, max_length=100)
    trials: int = Field(ge=1, le=10)
    observations: list[Observation] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def provenance(self) -> Capture:
        if (self.mode == "offline") != (self.provider == "fake"):
            message = "Scripted observations must never be attributed to a live provider"
            raise ValueError(message)
        if (self.mode == "offline") != (self.model_source == "scripted"):
            message = "Model provenance must match the capture mode"
            raise ValueError(message)
        if self.mode == "live" and any(
            o.input_sha256 is None or o.speech_end_ms is None for o in self.observations
        ):
            message = "Live observations require the hash and speech boundary of each recording"
            raise ValueError(message)
        if self.mode == "live" and self.working_tree_dirty:
            message = "Live evidence requires committed source"
            raise ValueError(message)
        keys = {(o.case_id, o.trial) for o in self.observations}
        if len(keys) != len(self.observations) or any(
            o.trial > self.trials for o in self.observations
        ):
            message = "Duplicate or out-of-range trials"
            raise ValueError(message)
        return self


def read_json(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        message = "Artifact exceeds the size limit"
        raise ValueError(message)
    return raw.decode("utf-8")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 2)


def summarize(capture: Capture, dataset: Dataset, dataset_hash: str) -> dict[str, object]:
    if capture.dataset_sha256 != dataset_hash:
        message = "Capture uses a different dataset"
        raise ValueError(message)
    labels = {case.id: case.label for case in dataset.cases}
    if any(o.case_id not in labels for o in capture.observations):
        message = "Unknown case in capture"
        raise ValueError(message)
    expected = {
        (case.id, trial) for case in dataset.cases for trial in range(1, capture.trials + 1)
    }
    if {(o.case_id, o.trial) for o in capture.observations} != expected:
        message = "Capture must include every case and trial, including failures"
        raise ValueError(message)
    results: dict[str, object] = {
        "mode": capture.mode,
        "provider": capture.provider,
        "model": capture.model,
        "recorded_at": capture.recorded_at,
        "attempted": len(capture.observations),
        "outcomes": dict(Counter(o.outcome for o in capture.observations)),
        "quality_claim": "live observations" if capture.mode == "live" else "harness only",
    }
    completed = [o for o in capture.observations if o.outcome == "completed"]
    for field in ("setup_ms", "first_audio_ms", "turn_ms"):
        values = [value for o in completed if (value := getattr(o, field)) is not None]
        results[field] = {
            "n": len(values),
            "p50": percentile(values, 0.5),
            "p95": percentile(values, 0.95),
        }
    for label in ("delegate", "direct", "ambiguous"):
        rows = [o for o in capture.observations if labels[o.case_id] == label]
        observed = [o for o in rows if o.delegated is not None]
        results[label] = {
            "attempted": len(rows),
            "observed": len(observed),
            "delegated": sum(o.delegated is True for o in observed),
            # Missing evidence counts as a failure for definite labels, never as a direct answer.
            "correct": None
            if label == "ambiguous"
            else sum(o.delegated == (label == "delegate") for o in observed),
        }
    return results


def offline_capture(dataset: Dataset, digest: str, revision: str) -> Capture:
    """Deliberately imperfect scripted observations exercise scoring, not model quality."""
    rows = []
    for index, case in enumerate(dataset.cases):
        rows.append(
            Observation(
                case_id=case.id,
                trial=1,
                outcome="timeout" if index == 0 else "completed",
                delegated=None if index == 0 else index % 3 == 0,
                setup_ms=None if index == 0 else 300.0,
                first_audio_ms=None if index == 0 else 200.0 + index,
                turn_ms=None if index == 0 else 1000.0 + index,
            )
        )
    return Capture(
        schema_version=1,
        mode="offline",
        provider="fake",
        model="scripted-v1",
        model_source="scripted",
        revision=revision,
        dataset_sha256=digest,
        recorded_at=datetime.now(UTC).isoformat(),
        browser="none: scripted observations",
        trials=1,
        observations=rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture", type=Path, help="Validate browser capture instead of fake data"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = read_json(DATASET)
    dataset = Dataset.model_validate_json(raw)
    digest = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    capture = (
        Capture.model_validate_json(read_json(args.capture))
        if args.capture
        else offline_capture(
            dataset,
            digest,
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=DATASET.parents[2], text=True
            ).strip(),
        )
    )
    if not args.capture:
        capture.working_tree_dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=DATASET.parents[2], text=True
            ).strip()
        )
    report = {"capture": capture.model_dump(), "summary": summarize(capture, dataset, digest)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
