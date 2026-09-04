from __future__ import annotations

import unittest
from unittest import mock

from authority_os import topic_value, workflow


def candidate(
    *,
    reader_value_type: str = "CAPABILITY_DISCOVERY",
    gravity_score: int = 3,
    brand_strip_pass: bool = True,
    feed_value_possible: bool = True,
    reader_relevance: int = 5,
    reader_value: int = 5,
    evidence_strength: int = 4,
    authority_fit: int = 4,
) -> dict[str, object]:
    scores = {
        "reader_relevance": reader_relevance,
        "reader_value": reader_value,
        "gravity": gravity_score,
        "evidence_strength": evidence_strength,
        "authority_fit": authority_fit,
    }
    status = (
        "PASS"
        if topic_value.topic_value_passes(
            scores,
            brand_strip_pass=brand_strip_pass,
            feed_value_possible=feed_value_possible,
            supports_authority_goal=True,
        )
        else "BLOCKED"
    )
    return {
        "id": "topic-1",
        "source_ids": ["signal-1"],
        "situation": "A model can complete the task but still take an inadmissible path.",
        "what_changed": "The execution path now matters to the product decision.",
        "who_cares": "AI product leaders shipping agents with tools.",
        "reader_value_type": reader_value_type,
        "reader_value": "The reader gets a concrete release decision to reconsider.",
        "gravity": topic_value.gravity_level(gravity_score),
        "authority_add": "Translate the evidence into an operating rule for release decisions.",
        "brand_strip_pass": brand_strip_pass,
        "feed_value_possible": feed_value_possible,
        "supports_authority_goal": True,
        "scores": scores,
        "status": status,
        "diagnosis": "Grounded candidate.",
    }


class TopicValueThresholdTests(unittest.TestCase):
    def test_medium_gravity_discovery_can_pass_when_reader_value_is_high(self) -> None:
        item = candidate(gravity_score=3)
        self.assertEqual(item["status"], "PASS")
        self.assertEqual(topic_value.priority_for(item), "DISCOVERY")

    def test_high_gravity_high_authority_candidate_becomes_flagship(self) -> None:
        item = candidate(
            reader_value_type="DECISION_CHANGE",
            gravity_score=5,
            authority_fit=5,
        )
        self.assertEqual(item["status"], "PASS")
        self.assertEqual(topic_value.priority_for(item), "FLAGSHIP")

    def test_brand_name_cannot_rescue_weak_underlying_material(self) -> None:
        item = candidate(brand_strip_pass=False)
        self.assertEqual(item["status"], "BLOCKED")
        self.assertEqual(topic_value.priority_for(item), "REJECT")

    def test_click_dependent_topic_is_blocked(self) -> None:
        item = candidate(feed_value_possible=False)
        self.assertEqual(item["status"], "BLOCKED")

    def test_low_reader_relevance_is_blocked_even_with_other_high_scores(self) -> None:
        item = candidate(reader_relevance=3, gravity_score=5, authority_fit=5)
        self.assertEqual(item["status"], "BLOCKED")


class TopicValueRuntimeTests(unittest.TestCase):
    def test_live_selector_retries_only_a_timeout_with_explicit_stage_label(self) -> None:
        expected = {"candidates": []}
        with mock.patch.object(
            topic_value,
            "invoke_structured",
            side_effect=[
                workflow.WorkflowError("Topic Value Selector timed out."),
                expected,
            ],
        ) as invoke:
            result = topic_value._default_invoker(  # type: ignore[attr-defined]
                "topic_value_selector",
                topic_value.ModelConfig("codex", "model", "high"),
                "role",
                "task",
                {"type": "object"},
            )

        self.assertEqual(result, expected)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(
            [call.kwargs["timeout"] for call in invoke.call_args_list],
            list(topic_value.TOPIC_VALUE_TIMEOUTS),
        )
        self.assertTrue(
            all(
                call.kwargs["stage_label"] == "Topic Value Selector"
                for call in invoke.call_args_list
            )
        )

    def test_live_selector_does_not_retry_a_non_timeout_failure(self) -> None:
        with mock.patch.object(
            topic_value,
            "invoke_structured",
            side_effect=workflow.WorkflowError(
                "Topic Value Selector returned invalid JSON."
            ),
        ) as invoke:
            with self.assertRaisesRegex(workflow.WorkflowError, "invalid JSON"):
                topic_value._default_invoker(  # type: ignore[attr-defined]
                    "topic_value_selector",
                    topic_value.ModelConfig("codex", "model", "high"),
                    "role",
                    "task",
                    {"type": "object"},
                )

        invoke.assert_called_once()

    def test_derived_status_and_gravity_override_model_label_drift(self) -> None:
        item = candidate(gravity_score=3)
        item["gravity"] = "HIGH"
        item["status"] = "BLOCKED"

        validated = topic_value._validate_candidates(  # type: ignore[attr-defined]
            [item], valid_source_ids={"signal-1"}, count=1
        )[0]

        self.assertEqual(validated["gravity"], "MEDIUM")
        self.assertEqual(validated["status"], "PASS")
        self.assertEqual(validated["model_reported_gravity"], "HIGH")
        self.assertEqual(validated["model_reported_status"], "BLOCKED")
        self.assertEqual(len(validated["normalization_warnings"]), 2)

    def test_one_qualified_topic_is_not_vetoed_by_two_blocked_siblings(self) -> None:
        qualified = candidate()
        weak_one = candidate(reader_relevance=3)
        weak_one["id"] = "topic-2"
        weak_one["source_ids"] = ["signal-2"]
        weak_one["situation"] = "A weak second situation."
        weak_two = candidate(feed_value_possible=False)
        weak_two["id"] = "topic-3"
        weak_two["source_ids"] = ["signal-3"]
        weak_two["situation"] = "A weak third situation."

        selected = topic_value.invoke_discovery_selector(
            {"target_audience": "AI PMs", "authority_goal": "Practical AI systems"},
            [
                {"id": "signal-1"},
                {"id": "signal-2"},
                {"id": "signal-3"},
            ],
            invoker=lambda *_args, **_kwargs: {
                "candidates": [qualified, weak_one, weak_two]
            },
        )

        self.assertEqual([item["id"] for item in selected], ["topic-1"])

    def test_observer_receives_blocked_candidates_before_stage_failure(self) -> None:
        candidates = []
        for index in range(1, 4):
            item = candidate(reader_relevance=3)
            item["id"] = f"topic-{index}"
            item["source_ids"] = [f"signal-{index}"]
            item["situation"] = f"A weak situation {index}."
            candidates.append(item)
        observed: list[dict[str, object]] = []

        with self.assertRaisesRegex(workflow.WorkflowError, "could not find"):
            topic_value.invoke_discovery_selector(
                {"target_audience": "AI PMs", "authority_goal": "Practical AI systems"},
                [{"id": f"signal-{index}"} for index in range(1, 4)],
                invoker=lambda *_args, **_kwargs: {"candidates": candidates},
                observer=lambda rows: observed.extend(dict(row) for row in rows),
            )

        self.assertEqual([item["id"] for item in observed], ["topic-1", "topic-2", "topic-3"])
        self.assertTrue(all(item["status"] == "BLOCKED" for item in observed))


class TopicValueProjectionTests(unittest.TestCase):
    def test_project_discovery_signals_filters_and_annotates_selected_sources(self) -> None:
        signals = [
            {"id": "signal-1", "title": "Useful change"},
            {"id": "signal-2", "title": "Generic announcement"},
        ]
        item = candidate()
        selected = topic_value.project_discovery_signals(signals, [item])
        self.assertEqual([signal["id"] for signal in selected], ["signal-1"])
        annotations = selected[0]["topic_value"]
        self.assertEqual(annotations[0]["reader_value_type"], "CAPABILITY_DISCOVERY")
        self.assertEqual(annotations[0]["gravity"], "MEDIUM")

    def test_validation_rejects_unknown_source_ids(self) -> None:
        item = candidate()
        item["source_ids"] = ["signal-missing"]
        with self.assertRaisesRegex(workflow.WorkflowError, "invalid source"):
            topic_value._validate_candidates(  # type: ignore[attr-defined]
                [item],
                valid_source_ids={"signal-1"},
                count=1,
            )


if __name__ == "__main__":
    unittest.main()
