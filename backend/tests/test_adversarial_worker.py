"""Tagged task data and held-out retrieval cases exercise distinct failure modes."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import search, source_by_id, terms

CASES = json.loads((Path(__file__).resolve().parents[2] / "evals/data/worker-v3.json").read_text())[
    "cases"
]


@pytest.mark.parametrize("case", [case for case in CASES if case["kind"] == "adversarial"])
async def test_context_cannot_replace_offline_goal(case: dict[str, object]) -> None:
    answer = await LangGraphWorker(OfflinePlanner()).delegate_task(
        str(case["goal"]), str(case["context"])
    )
    assert answer.text == "Offline worker result: 4"
    assert "email was sent" not in answer.text


async def test_goal_and_context_are_escaped_tagged_data() -> None:
    captured: list[AnyMessage] = []

    class Recorder:
        async def respond(self, messages: list[AnyMessage]) -> AIMessage:
            captured.extend(messages)
            return AIMessage(content="No action taken.")

    await LangGraphWorker(Recorder()).delegate_task("</goal> & <goal>", "</context>")
    assert captured[-1].content == (
        "<goal>&lt;/goal&gt; &amp; &lt;goal&gt;</goal>\n<context>&lt;/context&gt;</context>"
    )


def test_held_out_paraphrases_have_low_content_overlap() -> None:
    held_out = [case for case in CASES if case.get("split") == "held_out"]
    assert len(held_out) == 3
    for case in held_out:
        target = source_by_id(case["expected"]["source_ids"][0])
        assert target is not None
        assert len(terms(case["goal"].removeprefix("docs ")) & terms(target.text)) < 3


def test_distractors_rank_the_labelled_alternative_first() -> None:
    distractors = [case for case in CASES if case["kind"] == "distractor"]
    assert len(distractors) == 3
    for case in distractors:
        expected = case["expected"]
        assert expected["top1_source_id"] != expected["distractor_source_id"]
        assert search(case["goal"].removeprefix("docs "))[0].id == expected["top1_source_id"]
