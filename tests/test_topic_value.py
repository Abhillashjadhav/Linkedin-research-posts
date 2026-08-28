from __future__ import annotations

import unittest

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


class TopicValueProjectionTests(unittest.TestCase):
    def test_discovery_selector_supports_one_high_bar_pilot_topic(self) -> None:
        item = candidate()
        item.pop("id")

        def invoker(*_args: object, **_kwargs: object) -> dict[str, object]:
            return {"candidates": [item]}

        selected = topic_value.invoke_discovery_selector(
            {
                "target_audience": "AI product leaders",
                "authority_goal": "Teach practical production AI decisions",
            },
            [{"id": "signal-1", "title": "Useful capability"}],
            count=1,
            invoker=invoker,
        )

        self.assertEqual([item["id"] for item in selected], ["topic-1"])

    def test_topic_ids_are_derived_locally_from_array_order(self) -> None:
        items = []
        for index in range(1, 4):
            item = candidate()
            item["id"] = "model-generated-duplicate"
            item["source_ids"] = [f"signal-{index}"]
            item["situation"] = f"Grounded situation {index}."
            items.append(item)

        validated = topic_value._validate_candidates(  # type: ignore[attr-defined]
            items,
            valid_source_ids={"signal-1", "signal-2", "signal-3"},
            count=3,
        )

        self.assertEqual(
            [item["id"] for item in validated],
            ["topic-1", "topic-2", "topic-3"],
        )

    def test_topic_value_schema_does_not_delegate_ids_to_the_model(self) -> None:
        candidate_schema = topic_value._schema(3)["properties"]["candidates"][  # type: ignore[index,attr-defined]
            "items"
        ]
        self.assertNotIn("id", candidate_schema["properties"])  # type: ignore[index]
        self.assertNotIn("id", candidate_schema["required"])  # type: ignore[index]

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

    def test_capability_selection_keeps_runnable_and_demo_evidence_together(self) -> None:
        evidence = [
            {
                "id": "signal-1",
                "title": "[Capability Launch] Local agent debugger by Mira Rao",
            },
            {
                "id": "signal-2",
                "title": "[Capability Launch] Local agent debugger by Mira Rao",
            },
            {"id": "signal-3", "title": "Reliability decision"},
            {"id": "signal-4", "title": "Evaluation utility"},
        ]
        candidates = []
        for index, source_id in enumerate(("signal-1", "signal-3", "signal-4"), 1):
            item = candidate()
            item["id"] = f"topic-{index}"
            item["source_ids"] = [source_id]
            item["situation"] = f"Grounded situation {index} for the target reader."
            candidates.append(item)

        def invoker(*_args: object, **_kwargs: object) -> dict[str, object]:
            return {"candidates": candidates}

        profile = {
            "target_audience": "AI product leaders",
            "authority_goal": "Teach practical production AI decisions",
        }
        with self.assertRaisesRegex(workflow.WorkflowError, "runnable artifact"):
            topic_value.invoke_discovery_selector(
                profile,
                evidence,
                invoker=invoker,
            )


if __name__ == "__main__":
    unittest.main()
