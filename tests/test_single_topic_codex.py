from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import compare_capture_runtime
from authority_os import campaign, model_runtime, resonance, single_topic_codex, topic_value, workflow


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

        feedback = {
            "axis_shortfalls": {
                "voice_fidelity": {"observed": 3, "required": 4, "shortfall": 1}
            }
        }
        with (
            patch.object(
                workflow,
                "_build_writer_revision_prompt",
                return_value="revision-task",
            ) as prompt,
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
                repair_feedback=feedback,
            )

        self.assertEqual(result, revised)
        self.assertIs(calls[0]["schema"], workflow.WRITER_REVISION_SCHEMA)
        self.assertEqual(calls[0]["config"].runtime, "codex")  # type: ignore[union-attr]
        self.assertIs(calls[0]["web_search"], False)
        self.assertEqual(prompt.call_args.kwargs["repair_feedback"], feedback)

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

    def test_v0_comparison_installs_only_the_codex_provider_adapter(self) -> None:
        original_writer = workflow.invoke_writer
        original_critic = workflow.invoke_critic
        original_revision = workflow.invoke_writer_revision
        original_preferred = campaign.StageModels.__dict__["preferred"]
        original_features = model_runtime.NON_WEB_TOOL_FEATURES
        try:
            module = compare_capture_runtime._install_v0_codex_provider()  # type: ignore[attr-defined]
            compare_capture_runtime._lock_comparison_codex_runtime(  # type: ignore[attr-defined]
                include_v1_selection=False
            )
            self.assertIs(workflow.invoke_writer, module._invoke_writer_codex)  # type: ignore[attr-defined]
            self.assertIs(workflow.invoke_critic, module._invoke_critic_codex)  # type: ignore[attr-defined]
            self.assertIs(
                workflow.invoke_writer_revision,
                module._invoke_writer_revision_codex,  # type: ignore[attr-defined]
            )
            self.assertEqual(
                module.campaign.StageModels.preferred().writer.model,  # type: ignore[attr-defined]
                "gpt-5.6-sol",
            )
            self.assertEqual(
                module.campaign.StageModels.preferred().critic.model,  # type: ignore[attr-defined]
                "gpt-5.6-sol",
            )
            self.assertEqual(
                module.campaign.StageModels.preferred().writer.reasoning,  # type: ignore[attr-defined]
                "high",
            )
            self.assertEqual(
                module.campaign.StageModels.preferred().critic.reasoning,  # type: ignore[attr-defined]
                "high",
            )
            self.assertIn("fast_mode", module.model_runtime.NON_WEB_TOOL_FEATURES)  # type: ignore[attr-defined]
        finally:
            workflow.invoke_writer = original_writer
            workflow.invoke_critic = original_critic
            workflow.invoke_writer_revision = original_revision
            campaign.StageModels.preferred = original_preferred  # type: ignore[method-assign]
            model_runtime.NON_WEB_TOOL_FEATURES = original_features

    def test_v1_comparison_overrides_only_model_runtime_settings(self) -> None:
        original_preferred = campaign.StageModels.__dict__["preferred"]
        original_features = model_runtime.NON_WEB_TOOL_FEATURES
        original_topic_value_config = topic_value.ModelConfig
        original_resonance_config = resonance.ModelConfig
        try:
            compare_capture_runtime._lock_comparison_codex_runtime(  # type: ignore[attr-defined]
                include_v1_selection=True
            )
            stage_models = campaign.StageModels.preferred()
            for config in (
                stage_models.writer,
                stage_models.narrative_editor,
                stage_models.critic,
                stage_models.artisanal_editor,
                stage_models.comment_writer,
                stage_models.comment_reviewer,
                stage_models.artifact_editor,
                stage_models.visual_qa,
            ):
                self.assertEqual(config.model, "gpt-5.6-sol")
                self.assertEqual(config.reasoning, "high")
            self.assertEqual(
                topic_value.ModelConfig("codex", "ignored", "ultra").reasoning,
                "high",
            )
            self.assertEqual(
                resonance.ModelConfig("codex", "ignored", "max").model,
                "gpt-5.6-sol",
            )
            self.assertIn("fast_mode", model_runtime.NON_WEB_TOOL_FEATURES)
        finally:
            campaign.StageModels.preferred = original_preferred  # type: ignore[method-assign]
            model_runtime.NON_WEB_TOOL_FEATURES = original_features
            topic_value.ModelConfig = original_topic_value_config  # type: ignore[assignment]
            resonance.ModelConfig = original_resonance_config  # type: ignore[assignment]

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
