"""Production configuration, compact status and offline tooling boundaries."""

import logging
import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from voice_delegate.api.schemas import Status
from voice_delegate.config import Settings
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import corpus
from voice_delegate_agent.tools import TOOLS

ROOT = Path(__file__).resolve().parents[2]


def test_production_rejects_default_hosts_and_accepts_explicit_hosts() -> None:
    values = {
        "environment": "production",
        "allowed_origin": "https://demo.example",
        "access_token": "a" * 32,
    }
    with pytest.raises(ValidationError, match="VOICE_ALLOWED_HOSTS without testserver"):
        Settings.model_validate(values)
    assert Settings.model_validate({**values, "allowed_hosts": ["demo.example"]}).allowed_hosts == [
        "demo.example"
    ]


def test_status_bounds_evidence_without_mutating_worker_sources() -> None:
    source = replace(corpus()[0], text="x" * 900)
    status = Status(state="reconnecting", sources=(source,))
    assert status.sources[0].text == "x" * 400
    assert source.text == "x" * 900
    with pytest.raises(ValidationError):
        Status.model_validate({"state": "not-a-state"})


async def test_only_documentation_search_and_calculation_tools_are_exposed() -> None:
    assert {tool.name for tool in TOOLS} == {"calculate", "search_documentation"}
    result = await LangGraphWorker(OfflinePlanner()).delegate_task("docs fallback history", "")
    assert result.sources
    assert result.sources[0].text[:100] in result.text


def test_markdown_footnotes_are_not_link_definitions() -> None:
    links = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/check_links.py")))
    assert links.destinations("[^note]: explanatory text\n[doc]: docs/architecture.md\n") == [
        (2, "docs/architecture.md")
    ]


@pytest.mark.parametrize("script", ["smoke_container.py", "scaling_smoke.py"])
def test_smoke_failures_survive_teardown_errors(
    script: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    smoke = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts" / script)))
    with pytest.raises(SystemExit, match="failed probe"):
        smoke.require(False, "failed probe")
    runner = MagicMock(return_value=SimpleNamespace(returncode=1))
    monkeypatch.setattr(smoke.subprocess, "run", runner)
    with caplog.at_level(logging.WARNING):
        smoke.cleanup(["docker", "cleanup"])
    assert runner.call_args.kwargs["check"] is False
    assert "teardown failed" in caplog.text
    runner.side_effect = FileNotFoundError
    smoke.cleanup(["docker", "cleanup"])
    assert "could not run" in caplog.text
