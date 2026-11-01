"""Benchmark failures and unknown evidence must remain visible in the denominator."""

import hashlib

import pytest
from pydantic import ValidationError

from evals.voice_benchmark import DATASET, Capture, Dataset, offline_capture, summarize


@pytest.mark.parametrize("outcome", ["timeout", "overlap", "error"])
def test_censored_decisions_stay_unknown_unless_a_delegation_was_seen(outcome: str) -> None:
    _, _, capture = fixture_capture()
    body = capture.model_dump()
    row = body["observations"][0]
    row.update(outcome=outcome, delegated=False)
    with pytest.raises(ValidationError, match="direct answer"):
        Capture.model_validate(body)
    row["delegated"] = True
    assert Capture.model_validate(body).observations[0].delegated is True
    row["setup_ms"] = 10.0
    with pytest.raises(ValidationError, match="Censored"):
        Capture.model_validate(body)


def fixture_capture() -> tuple[Dataset, str, Capture]:
    dataset = Dataset.model_validate_json(DATASET.read_bytes())
    digest = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    return dataset, digest, offline_capture(dataset, digest, "a" * 40)


def test_fixed_cases_and_imperfect_fake_are_not_quality_results() -> None:
    dataset, digest, capture = fixture_capture()
    report = summarize(capture, dataset, digest)
    assert report["attempted"] == 30
    assert report["quality_claim"] == "harness only"
    assert report["outcomes"] == {"timeout": 1, "completed": 29}
    assert report["first_audio_ms"] == {"n": 29, "p50": 215.0, "p95": 227.6}
    assert report["delegate"] == {"attempted": 10, "observed": 9, "delegated": 3, "correct": 3}
    assert report["ambiguous"] == {"attempted": 10, "observed": 10, "delegated": 3, "correct": None}


def test_reject_missing_duplicate_unknown_or_mismatched_case_evidence() -> None:
    dataset, digest, capture = fixture_capture()
    with pytest.raises(ValueError, match="every case"):
        summarize(
            capture.model_copy(update={"observations": capture.observations[1:]}), dataset, digest
        )
    with pytest.raises(ValueError, match="different dataset"):
        summarize(capture, dataset, "b" * 64)
    body = capture.model_dump()
    body["observations"].append(body["observations"][0])
    with pytest.raises(ValidationError, match="Duplicate"):
        Capture.model_validate(body)
    capture.observations[0].case_id = "unknown-01"
    with pytest.raises(ValueError, match="Unknown case"):
        summarize(capture, dataset, digest)


def test_live_provenance_requires_recording_hash_and_no_transcript_fields() -> None:
    _, _, capture = fixture_capture()
    body = capture.model_dump()
    body.update(mode="live", provider="live", model_source="operator-declared")
    with pytest.raises(ValidationError, match="hash"):
        Capture.model_validate(body)
    for row in body["observations"]:
        row["input_sha256"] = "c" * 64
        row["speech_end_ms"] = 200.0
    assert Capture.model_validate(body).mode == "live"
    body["observations"][0]["transcript"] = "must not be retained"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Capture.model_validate(body)


def test_censored_or_inverted_timing_cannot_bias_percentiles() -> None:
    _, _, capture = fixture_capture()
    body = capture.model_dump()
    body["observations"][0]["first_audio_ms"] = 0.0
    with pytest.raises(ValidationError, match="Censored"):
        Capture.model_validate(body)
    body = capture.model_dump()
    body["observations"][1]["turn_ms"] = 1.0
    with pytest.raises(ValidationError, match="precede"):
        Capture.model_validate(body)
