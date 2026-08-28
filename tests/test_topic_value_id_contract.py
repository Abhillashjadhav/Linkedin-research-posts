from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import topic_value, topic_value_id_contract


class TopicValueIdSchemaTests(unittest.TestCase):
    def _item(self, count: int) -> dict[str, object]:
        schema = topic_value_id_contract.schema_with_exact_ids(count)
        properties = schema["properties"]
        assert isinstance(properties, dict)
        candidates = properties["candidates"]
        assert isinstance(candidates, dict)
        item = candidates["items"]
        assert isinstance(item, dict)
        return item

    def test_count_one_schema_allows_only_topic_one(self) -> None:
        item = self._item(1)
        properties = item["properties"]
        assert isinstance(properties, dict)
        self.assertEqual(
            properties["id"],
            {"type": "string", "enum": ["topic-1"]},
        )

    def test_count_three_schema_allows_exact_three_ids(self) -> None:
        item = self._item(3)
        properties = item["properties"]
        assert isinstance(properties, dict)
        self.assertEqual(
            properties["id"],
            {
                "type": "string",
                "enum": ["topic-1", "topic-2", "topic-3"],
            },
        )

    def test_exact_id_schema_preserves_v1_atomic_value_field(self) -> None:
        base = topic_value._candidate_schema()  # type: ignore[attr-defined]

        def v1_candidate_schema() -> dict[str, object]:
            schema = copy.deepcopy(base)
            properties = schema["properties"]
            required = schema["required"]
            assert isinstance(properties, dict)
            assert isinstance(required, list)
            properties["atomic_value"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 280,
            }
            required.append("atomic_value")
            return schema

        with patch.object(
            topic_value,
            "_candidate_schema",
            side_effect=v1_candidate_schema,
        ):
            item = self._item(1)
        properties = item["properties"]
        required = item["required"]
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        self.assertIn("atomic_value", properties)
        self.assertIn("atomic_value", required)
        self.assertEqual(properties["id"]["enum"], ["topic-1"])  # type: ignore[index]

    def test_prompt_instruction_names_exact_allowed_ids(self) -> None:
        instruction = topic_value_id_contract.id_contract_instruction(3)
        self.assertIn("CANDIDATE_ID_CONTRACT", instruction)
        self.assertIn("topic-1, topic-2, topic-3", instruction)
        self.assertIn("once each and no others", instruction)


class TopicValueIdWiringTests(unittest.TestCase):
    def test_live_launcher_installs_contract_for_discovery_and_drafting(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "bin" / "linkedin-os").read_text(encoding="utf-8")
        self.assertEqual(launcher.count("topic_value_id_contract.install()"), 2)

    def test_comparison_installs_contract_only_for_v1_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        capture = (root / "scripts" / "compare_capture_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if args.label == "v1":', capture)
        self.assertEqual(capture.count("topic_value_id_contract.install()"), 1)


if __name__ == "__main__":
    unittest.main()
