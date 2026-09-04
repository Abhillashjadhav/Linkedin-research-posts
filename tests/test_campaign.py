"""Regression tests for the trace-first five-day coordinator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from authority_os import campaign, workflow


def words(stem: str) -> str:
    opening = (
        f"{stem} workflow reliability gives AI product leaders a reliable workflow expansion decision. "
        "Set a reliability budget before expanding the workflow. Connect workflow reliability "
        "to a falsifiable product decision."
    )
    filler = " ".join(f"{stem}{chr(97 + (index % 26))}{chr(97 + ((index // 26) % 26))}" for index in range(165))
    return f"{opening} {filler}."


def candidates() -> list[dict[str, object]]:
    return [
        {"id": "candidate-1", "angle": "mechanism", "text": words("alpha"), "claim_ids": ["source-1"]},
        {"id": "candidate-2", "angle": "decision", "text": words("bravo"), "claim_ids": ["source-1"]},
        {"id": "candidate-3", "angle": "failure", "text": words("charlie"), "claim_ids": ["source-1"]},
    ]


class FakeInvoker:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.drafts = candidates()

    def __call__(self, stage, _config, _role, _task, _schema):
        self.calls.append(stage)
        if stage == "writer":
            return {"candidates": self.drafts}
        if stage == "narrative_editor":
            return {
                "results": [
                    {
                        "id": item["id"],
                        "status": "UNCHANGED",
                        "edited_text": item["text"],
                        "claim_ids": item["claim_ids"],
                        "diagnosis": "The decision and consequence are already explicit.",
                        "repeatable_sentence": "Set a reliability budget before expanding the workflow.",
                    }
                    for item in self.drafts
                ]
            }
        if stage == "critic":
            return {
                "scorecards": [
                    {
                        "candidate_id": item["id"],
                        "hook_strength": 5,
                        "middle_escalation": 5,
                        "earned_closer": 5,
                        "specificity_and_source_quality": 5,
                        "voice_fidelity": 5,
                    }
                    for item in self.drafts
                ]
            }
        if stage in {"no_ai_slop_artisanal", "first_comment_no_ai_slop"}:
            source = self.drafts[0]["text"] if stage == "no_ai_slop_artisanal" else "The source documents the reliability budget. https://example.com/reliability"
            return {"edited_text": source, "changes_made": [], "status": "PASS", "failed_checks": []}
        if stage == "first_comment_writer":
            return {"text": "The source documents the reliability budget. https://example.com/reliability"}
        if stage == "first_comment_reviewer":
            return {"scores": {axis: 5 for axis in campaign.COMMENT_AXES}}
        if stage == "artifact_editor":
            return {
                "format": "DIAGRAM",
                "rationale": "The decision is a two-step control flow.",
                "visual_narrative": "A validated budget permits expansion.",
                "panels": [
                    {"heading": "Set the budget", "body": "Define the reliability boundary.", "claim_ids": ["source-1"]},
                    {"heading": "Permit expansion", "body": "Advance only after the boundary passes.", "claim_ids": ["source-1"]},
                ],
            }
        if stage == "visual_qa":
            return {
                "checks": [
                    {"name": name, "status": "PASS", "reason": "Matches the locked post and layout metadata."}
                    for name in campaign.VISUAL_CHECKS
                ],
                "overall": "PASS",
            }
        raise AssertionError(f"unexpected stage: {stage}")


class CampaignTests(unittest.TestCase):
    def day(self) -> dict[str, object]:
        return {
            "day": "Monday",
            "date": "2026-08-10",
            "topic": "Reliability budgets",
            "topic_slug": "reliability-budgets",
            "thesis": "Workflow reliability needs a budget before expansion.",
            "target_reader": "AI product leaders designing reliable workflows",
            "reader_problem": "AI product leaders need a reliable workflow expansion decision.",
            "product_decision": "Set a reliability budget before expanding the workflow.",
            "authority_statement": "Connect workflow reliability to a falsifiable product decision.",
            "why_now": "Recent primary evidence supports the decision.",
            "dominant_take": "Evaluate the complete workflow.",
            "missing_angle": "Tie the budget to transition authority.",
            "artifact_policy": "Return a diagram.",
            "evidence": [
                {
                    "id": "source-1",
                    "title": "Reliability evidence",
                    "claim": "Workflow reliability needs a reliability budget before expansion.",
                    "source": "https://example.com/reliability",
                    "source_quality": "primary",
                    "body_read": True,
                    "source_date": "2026-08-09",
                    "date_kind": "accessed",
                    "caveats": "Test evidence.",
                }
            ],
        }

    def test_full_stage_order_and_ready_trace(self) -> None:
        invoker = FakeInvoker()
        models = campaign.StageModels.preferred()
        with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
            trace = campaign._run_day(
                self.day(),
                directory=Path(temporary),
                models=models,
                invoker=invoker,
                skill="name: no-ai-slop\nMinimum edit.",
                evaluation="# No AI slop eval\nPass or fail.",
                editor_provenance={"repository": "test", "skill_sha256": "a", "eval_sha256": "b"},
                researched_at="2026-08-09T00:00:00Z",
            )
            self.assertEqual(trace["final"]["status"], "READY_FOR_HUMAN_REVIEW")
            self.assertTrue((Path(temporary) / "artifact-diagram.svg").is_file())
        self.assertEqual(
            invoker.calls,
            [
                "writer",
                "narrative_editor",
                "critic",
                "no_ai_slop_artisanal",
                "first_comment_writer",
                "first_comment_no_ai_slop",
                "first_comment_reviewer",
                "artifact_editor",
                "visual_qa",
            ],
        )

    def test_post_route_uses_shared_eighteen_point_acceptance_floor(self) -> None:
        class BoundaryInvoker(FakeInvoker):
            def __call__(self, stage, config, role, task, schema):
                if stage == "critic":
                    self.calls.append(stage)
                    return {
                        "scorecards": [
                            {
                                "candidate_id": item["id"],
                                "hook_strength": 5,
                                "middle_escalation": 3,
                                "earned_closer": 3,
                                "specificity_and_source_quality": 3,
                                "voice_fidelity": 4,
                            }
                            for item in self.drafts
                        ]
                    }
                if stage == "first_comment_reviewer":
                    self.calls.append(stage)
                    return {
                        "scores": {
                            "continuity_with_post": 4,
                            "additional_value": 4,
                            "authority_and_proof": 4,
                            "natural_non_promotional_fit": 3,
                            "voice_fidelity": 3,
                        }
                    }
                return super().__call__(stage, config, role, task, schema)

        invoker = BoundaryInvoker()
        with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
            trace = campaign._run_day(
                self.day(),
                directory=Path(temporary),
                models=campaign.StageModels.preferred(),
                invoker=invoker,
                skill="name: no-ai-slop\nMinimum edit.",
                evaluation="# No AI slop eval\nPass or fail.",
                editor_provenance={
                    "repository": "test",
                    "skill_sha256": "a",
                    "eval_sha256": "b",
                },
                researched_at="2026-08-09T00:00:00Z",
            )
        self.assertEqual(trace["final"]["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(trace["post_edit_recritic"]["score"]["effective_total"], 18)
        self.assertEqual(trace["first_comment"]["review"]["total"], 18)
        self.assertIn("no_ai_slop_artisanal", invoker.calls)

    def test_post_route_never_trades_away_voice_floor(self) -> None:
        class LowVoiceInvoker(FakeInvoker):
            def __call__(self, stage, config, role, task, schema):
                if stage == "critic":
                    self.calls.append(stage)
                    return {
                        "scorecards": [
                            {
                                "candidate_id": item["id"],
                                "hook_strength": 5,
                                "middle_escalation": 5,
                                "earned_closer": 5,
                                "specificity_and_source_quality": 5,
                                "voice_fidelity": 3,
                            }
                            for item in self.drafts
                        ]
                    }
                return super().__call__(stage, config, role, task, schema)

        invoker = LowVoiceInvoker()
        with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
            trace = campaign._run_day(
                self.day(),
                directory=Path(temporary),
                models=campaign.StageModels.preferred(),
                invoker=invoker,
                skill="name: no-ai-slop\nMinimum edit.",
                evaluation="# No AI slop eval\nPass or fail.",
                editor_provenance={
                    "repository": "test",
                    "skill_sha256": "a",
                    "eval_sha256": "b",
                },
                researched_at="2026-08-09T00:00:00Z",
            )
        self.assertEqual(trace["final"]["status"], "BLOCKED")
        self.assertNotIn("no_ai_slop_artisanal", invoker.calls)
        diagnostics = trace["writer"]["cycles"]
        self.assertEqual(len(diagnostics), campaign.MAX_CANDIDATE_CYCLES)

    def test_spec_requires_exact_monday_to_friday_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spec.json"
            path.write_text(json.dumps({"schema_version": 1, "days": []}), encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                campaign._load_spec(path)

    def test_narrative_editor_drops_a_new_deterministic_gate_regression(self) -> None:
        drafts = candidates()

        def invoker(stage, _config, _role, _task, _schema):
            self.assertEqual(stage, "narrative_editor")
            return {
                "results": [
                    {
                        "id": item["id"],
                        "status": "EDITED",
                        "edited_text": str(item["text"]).replace(
                            "Set a reliability budget before expanding the workflow.",
                            "I built the reliability budget before expanding the workflow.",
                        ),
                        "claim_ids": item["claim_ids"],
                        "diagnosis": "Added unsupported personal standing.",
                        "repeatable_sentence": "Connect workflow reliability to a falsifiable product decision.",
                    }
                    for item in drafts
                ]
            }

        survivors, trace = campaign._invoke_narrative_editor(
            candidates=drafts,
            brief=campaign._brief(self.day()),
            evidence=campaign._runtime_evidence(self.day()["evidence"]),
            config=campaign.StageModels.preferred().narrative_editor,
            invoker=invoker,
        )
        self.assertEqual(survivors, [])
        self.assertTrue(all(item["status"] == "DROP" for item in trace))
        self.assertTrue(
            all(str(item["diagnosis"]).startswith("contract-rejected-gate-regression") for item in trace)
        )

    def test_artisanal_prompt_protects_source_anchored_sentences(self) -> None:
        observed: dict[str, str] = {}

        def invoker(stage, _config, role, task, _schema):
            self.assertEqual(stage, "no_ai_slop_artisanal")
            observed.update({"role": role, "task": task})
            return {
                "edited_text": "Source fact remains unchanged.",
                "changes_made": [],
                "status": "PASS",
                "failed_checks": [],
            }

        campaign._invoke_artisanal_editor(
            text="Source fact remains unchanged.",
            claim_ids=["source-1"],
            context="locked LinkedIn post candidate",
            skill="name: no-ai-slop\nMinimum edit.",
            evaluation="# Eval\nPass.",
            config=campaign.StageModels.preferred().artisanal_editor,
            invoker=invoker,
            stage="no_ai_slop_artisanal",
        )
        self.assertIn("character-for-character unchanged", observed["task"])

    def test_reporting_override_does_not_reuse_blocked_verdict(self) -> None:
        entry = campaign._summary_entry(
            {
                "day": "Monday",
                "final": {"status": "BLOCKED"},
                "regeneration_count": 4,
            },
            reporting_statuses={"Monday": "ALREADY_PUBLISHED — OUT_OF_SCOPE"},
            models=campaign.StageModels.preferred(),
        )
        self.assertEqual(entry["status"], "ALREADY_PUBLISHED — OUT_OF_SCOPE")
        self.assertIsNone(entry["regeneration_count"])
        self.assertIsNone(entry["critic_effective_total"])
        self.assertIsNone(entry["writer"])
        self.assertIsNone(entry["narrative_editor"])
        self.assertIsNone(entry["critic"])

    def test_comment_numbers_and_links_fail_closed(self) -> None:
        gates = campaign._comment_evidence_gates(
            {"text": "The result was 99%. https://wrong.example/data"},
            post_text="No number appears here.",
            evidence=self.day()["evidence"],
        )
        self.assertFalse(gates["passes"])
        self.assertEqual(gates["source_links_supported"], "FAIL")
        self.assertEqual(gates["numbers_supported"], "FAIL")

    def test_comment_number_gate_ignores_digits_inside_approved_url(self) -> None:
        evidence = json.loads(json.dumps(self.day()["evidence"]))
        evidence[0]["source"] = "https://example.com/gemini-api-3-6"
        gates = campaign._comment_evidence_gates(
            {
                "text": "Primary source: https://example.com/gemini-api-3-6",
            },
            post_text="No number appears here.",
            evidence=evidence,
        )
        self.assertTrue(gates["passes"])
        self.assertEqual(gates["numbers_supported"], "PASS")

    def test_comment_requires_a_supplied_source_url(self) -> None:
        gates = campaign._comment_evidence_gates(
            {"text": "The source documents the reliability budget."},
            post_text="No number appears here.",
            evidence=self.day()["evidence"],
        )
        self.assertFalse(gates["passes"])
        self.assertEqual(gates["source_links_supported"], "FAIL")
        self.assertEqual(gates["source_urls"], [])

    def test_comment_accepts_multiple_supplied_source_urls(self) -> None:
        evidence = json.loads(json.dumps(self.day()["evidence"]))
        evidence.append(
            {
                **evidence[0],
                "id": "source-2",
                "source": "https://example.com/second-primary-source",
            }
        )
        gates = campaign._comment_evidence_gates(
            {
                "text": (
                    "Primary sources: https://example.com/reliability and "
                    "https://example.com/second-primary-source"
                )
            },
            post_text="No number appears here.",
            evidence=evidence,
        )
        self.assertTrue(gates["passes"])
        self.assertEqual(
            gates["source_urls"],
            [
                "https://example.com/reliability",
                "https://example.com/second-primary-source",
            ],
        )

    def test_comment_writer_contract_exposes_urls_not_internal_ids(self) -> None:
        observed: dict[str, object] = {}

        def invoker(stage, _config, role, _task, schema):
            self.assertEqual(stage, "first_comment_writer")
            observed.update({"role": role, "schema": schema})
            return {"text": "Primary source: https://example.com/reliability"}

        result = campaign._invoke_comment_writer(
            post={"text": "Post"},
            day=self.day(),
            evidence=self.day()["evidence"],
            config=campaign.StageModels.preferred().comment_writer,
            invoker=invoker,
        )
        self.assertEqual(set(result), {"text"})
        self.assertEqual(observed["schema"]["required"], ["text"])
        self.assertNotIn("claim_ids", observed["schema"]["properties"])
        self.assertIn("at least one supplied primary-source URL", observed["role"])

    def test_day_rerun_prunes_only_outputs_stale_after_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in (
                "post.md",
                "first-comment.md",
                "artifact-current.svg",
                "artifact-old.svg",
                "trace.json",
            ):
                (directory / name).write_text("old", encoding="utf-8")
            campaign._prune_day_outputs(
                directory,
                {
                    "final": {"status": "BLOCKED"},
                    "artifact": {"files": ["artifact-current.svg"]},
                },
            )
            self.assertFalse((directory / "post.md").exists())
            self.assertFalse((directory / "first-comment.md").exists())
            self.assertFalse((directory / "artifact-old.svg").exists())
            self.assertTrue((directory / "artifact-current.svg").exists())
            self.assertTrue((directory / "trace.json").exists())

    def test_completed_artifacts_promote_from_isolated_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            directory = root / "day"
            staging.mkdir()
            directory.mkdir()
            (staging / "artifact-diagram.svg").write_text("new", encoding="utf-8")
            (directory / "artifact-diagram.svg").write_text("old", encoding="utf-8")
            campaign._promote_artifacts(
                staging,
                directory,
                {"artifact": {"files": ["artifact-diagram.svg"]}},
            )
            self.assertEqual(
                (directory / "artifact-diagram.svg").read_text(encoding="utf-8"),
                "new",
            )
            self.assertFalse((staging / "artifact-diagram.svg").exists())


if __name__ == "__main__":
    unittest.main()
