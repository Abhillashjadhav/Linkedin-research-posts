from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import single_topic_codex, workflow


class SingleTopicCodexRuntimeTests(unittest.TestCase):
    def test_writer_uses_codex_structured_runtime_and_existing_schema(self) -> None:
        calls: list[dict[str, object]] = []
        returned = [
            {"id": "candidate-1", "angle": "a", "text": "one", "claim_ids": ["source-1"]},
            {"id": "candidate-2", "angle": "b", "text": "two", "claim_ids": ["source-1"]},
            {"id": "candidate-3", "angle": "c", "text": "three", "claim_ids": ["source-1"]},
        ]

        def fake_invoke(**kwargs):
            calls.append(kwargs)
            return {"candidates": returned}

        with (
            patch.object(workflow, "build_writer_prompt", return_value="writer-task"),
            patch.object(workflow, "_writer_system_prompt", return_value="writer-role"),
            patch.object(workflow, "validate_draft_candidates", return_value=returned) as validate,
            patch("authority_os.single_topic_codex.model_runtime.invoke_structured", side_effect=fake_invoke),
        ):
            result = single_topic_codex._invoke_writer_codex(  # type: ignore[attr-defined]
                brief={},
                evidence=[],
                allow_model_egress=True,
                voice_guidance={"provenance": "reconstructed-style-guidance", "voice": "plain"},
            )

        self.assertEqual(result, returned)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["config"].runtime, "codex")  # type: ignore[union-attr]
        self.assertIs(call["schema"], workflow.WRITER_SCHEMA)
        self.assertEqual(call["role_prompt"], "writer-role")
        self.assertEqual(call["task_prompt"], "writer-task")
        self.assertIs(call["web_search"], False)
        self.assertEqual(call["stage_label"], "Single-topic Writer")
        validate.assert_called_once()

    def test_critic_uses_dynamic_v1_schema_and_local_validator(self) -> None:
        sentinel_schema = {"type": "object", "x-v1": True}
        candidates = [{"id": "candidate-1", "angle": "a", "text": "text", "claim_ids": ["source-1"]}]
        validated = [
            {
                "candidate_id": "candidate-1",
                "hook_strength": 5,
                "middle_escalation": 4,
                "earned_closer": 4,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 5,
                "raw_total": 22,
                "effective_total": 22,
                "hook_cap_applied": False,
                "band": "one-light-revision",
            }
        ]
        calls: list[dict[str, object]] = []

        def fake_invoke(**kwargs):
            calls.append(kwargs)
            return {"scorecards": [{"anchored": "provider-shape"}]}

        with (
            patch.object(workflow, "CRITIC_SCORE_SCHEMA", sentinel_schema),
            patch.object(workflow, "build_critic_prompt", return_value="critic-task"),
            patch.object(workflow, "critic_scoring_system_prompt", return_value="critic-role"),
            patch.object(workflow, "validate_critic_scorecards", return_value=validated) as validate,
            patch("authority_os.single_topic_codex.model_runtime.invoke_structured", side_effect=fake_invoke),
        ):
            result = single_topic_codex._invoke_critic_codex(  # type: ignore[attr-defined]
                candidates,
                {},
                [],
                allow_model_egress=True,
            )

        self.assertEqual(result[0]["candidate_id"], "candidate-1")
        self.assertEqual(result[0]["hook_strength"], 5)
        self.assertIs(calls[0]["schema"], sentinel_schema)
        self.assertEqual(calls[0]["config"].runtime, "codex")  # type: ignore[union-attr]
        self.assertIs(calls[0]["web_search"], False)
        validate.assert_called_once_with([{"anchored": "provider-shape"}], candidates)

    def test_writer_revision_uses_codex_and_preserves_existing_envelope(self) -> None:
        revised = {
            "id": "candidate-1",
            "angle": "a",
            "text": "revised",
            "claim_ids": ["source-1"],
        }
        calls: list[dict[str, object]] = []

        def fake_invoke(**kwargs):
            calls.append(kwargs)
            return {"candidate": revised}

        with (
            patch.object(workflow, "_build_writer_revision_prompt", return_value="revision-task"),
            patch.object(workflow, "_writer_revision_system_prompt", return_value="revision-role"),
            patch("authority_os.single_topic_codex.model_runtime.invoke_structured", side_effect=fake_invoke),
        ):
            result = single_topic_codex._invoke_writer_revision_codex(  # type: ignore[attr-defined]
                {"id": "candidate-1"},
                {},
                [],
                scorecard={},
                allow_model_egress=True,
                voice_guidance={"provenance": "reconstructed-style-guidance", "voice": "plain"},
            )

        self.assertEqual(result, revised)
        self.assertIs(calls[0]["schema"], workflow.WRITER_REVISION_SCHEMA)
        self.assertEqual(calls[0]["config"].runtime, "codex")  # type: ignore[union-attr]
        self.assertIs(calls[0]["web_search"], False)

    def test_install_replaces_all_three_legacy_single_topic_model_functions(self) -> None:
        with (
            patch.object(single_topic_codex, "_INSTALLED", False),
            patch.object(workflow, "invoke_writer") as writer,
            patch.object(workflow, "invoke_critic") as critic,
            patch.object(workflow, "invoke_writer_revision") as revision,
        ):
            single_topic_codex.install()
            self.assertIs(workflow.invoke_writer, single_topic_codex._invoke_writer_codex)  # type: ignore[attr-defined]
            self.assertIs(workflow.invoke_critic, single_topic_codex._invoke_critic_codex)  # type: ignore[attr-defined]
            self.assertIs(workflow.invoke_writer_revision, single_topic_codex._invoke_writer_revision_codex)  # type: ignore[attr-defined]
            self.assertIsNot(workflow.invoke_writer, writer)
            self.assertIsNot(workflow.invoke_critic, critic)
            self.assertIsNot(workflow.invoke_writer_revision, revision)

    def test_runtime_module_and_v1_wiring_have_no_claude_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module = (root / "src" / "authority_os" / "single_topic_codex.py").read_text()
        launcher = (root / "bin" / "linkedin-os").read_text()
        capture = (root / "scripts" / "compare_capture_runtime.py").read_text()

        self.assertNotIn('which("claude")', module)
        self.assertNotIn("subprocess.run", module)
        self.assertNotIn("Claude CLI", module)
        self.assertEqual(launcher.count("single_topic_codex.install()"), 1)
        self.assertLess(
            launcher.index("single_topic_codex.install()"),
            launcher.index("human_readability.install()"),
        )
        self.assertIn('if args.label == "v1":', capture)
        self.assertEqual(capture.count("single_topic_codex.install()"), 1)
        self.assertLess(
            capture.index("single_topic_codex.install()"),
            capture.index("human_readability.install()"),
        )

    def test_egress_and_timeout_boundaries_remain_fail_closed(self) -> None:
        with self.assertRaisesRegex(workflow.WorkflowError, "explicit consent"):
            single_topic_codex._invoke_writer_codex(  # type: ignore[attr-defined]
                brief={}, evidence=[], allow_model_egress=False
            )
        with self.assertRaisesRegex(workflow.WorkflowError, "positive integer"):
            single_topic_codex._invoke_critic_codex(  # type: ignore[attr-defined]
                [], {}, [], allow_model_egress=True, timeout=0
            )


if __name__ == "__main__":
    unittest.main()
