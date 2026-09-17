"""One-batch delivery must preserve exact drafts and the owner's >18 boundary."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import (
    __main__ as cli, best_effort, daily_cli, daily_spine_cli, draft_delivery,
    eval_dashboard_html, human_readability, post_styles, quality_optimizer,
    social_media_gate_policy, v1_completion, workflow,
)
from test_drafting import evidence_record, strategy_brief
from test_package import fixture_context, rescored_review
from test_quality_optimizer import attempt, candidate


def batch():
    # Candidate 1 has the higher total, candidate 2 the stronger qualified hook.
    # Candidate 3 has the same hook as 2 but 18 is outside the strict boundary.
    return attempt(
        candidate(23, dict(zip(workflow.CRITIC_AXES, (3, 5, 5, 5, 5))),
                  candidate_id="candidate-1", text="Incident one.\n\nReader consequence one."),
        candidate(20, dict(zip(workflow.CRITIC_AXES, (5, 4, 4, 4, 3))),
                  candidate_id="candidate-2", text="Incident two.\n\nReader consequence two."),
        candidate(18, dict(zip(workflow.CRITIC_AXES, (5, 3, 3, 4, 3))),
                  candidate_id="candidate-3", text="Incident three.\n\nReader consequence three."),
    )


class SharedBriefTests(unittest.TestCase):
    def test_style_reaches_all_three_writing_roles_and_no_manual_placeholder(self):
        brief = strategy_brief()
        brief["post_style"] = "short-humorous"
        evidence = [evidence_record()]
        drafts = [{"id": f"candidate-{n}", "angle": str(n),
                   "text": f"Distinct incident {n}. Reader stake.", "claim_ids": ["claim-1"]}
                  for n in range(1, 4)]
        writer = workflow.build_writer_prompt(
            brief=brief, evidence=evidence, voice_guidance=workflow.load_voice_guidance())
        editor = human_readability._task(drafts, brief, evidence, None)
        critic = workflow.build_critic_prompt(drafts, brief, evidence)
        for prompt in (writer, editor, critic):
            self.assertIn("POST_STYLE: short-humorous", prompt)
            self.assertIn("40–80 words", prompt)
            self.assertIn("Line 2 immediately connects", prompt)
        self.assertNotIn("candidate 2 with the product decision", writer)
        self.assertNotIn("LINE 1 MUST pair the concrete reader problem", editor)
        with patch.object(social_media_gate_policy, "_ORIGINAL_BUILD_WRITER_PROMPT", return_value=writer):
            effective = social_media_gate_policy._build_writer_prompt_social(
                brief=brief, evidence=evidence, voice_guidance=workflow.load_voice_guidance())
        self.assertNotIn("SOCIAL_MEDIA_HUMAN_REVIEW_POLICY", effective)

    def test_both_public_parsers_accept_same_style(self):
        parsed = cli.build_parser().parse_args(["draft", "--post-style", "short-humorous"])
        discovered = daily_spine_cli.parser().parse_args(
            ["--profile", "data/private/profile.json", "--post-style", "short-humorous", "--generate-post"])
        self.assertEqual(parsed.post_style, discovered.post_style)
        self.assertEqual(post_styles.hook_verdict(None), "UNCERTAIN")
        self.assertEqual(post_styles.hook_verdict(3), "FAIL")
        self.assertEqual(post_styles.hook_verdict(4), "PASS")

    def test_short_style_does_not_inherit_a_long_form_word_minimum(self):
        brief = strategy_brief()
        brief.update(goal="reach", post_style="short-humorous")
        texts = (
            "A retry queue can repeat a successful write after a timeout.",
            "Choose a recovery budget before adding another workflow step.",
            "The incident log exposes which dependency exhausted the available capacity.",
        )
        drafts = [{"id": f"candidate-{n}", "angle": str(n),
                   "text": text, "claim_ids": ["claim-1"]}
                  for n, text in enumerate(texts, start=1)]
        self.assertEqual(workflow.validate_draft_candidates(
            drafts, brief=brief, evidence=[evidence_record()]), drafts)

    def test_package_and_delivery_choose_the_same_hook_and_strict_total_boundary(self):
        context = fixture_context(mode="live")
        context["brief"]["post_style"] = "short-humorous"
        drafts = context["review"]["candidates"]
        for axes, expected in (
            (((3, 5, 5, 5, 5), (5, 4, 4, 4, 3), (5, 3, 3, 4, 3)), drafts[1]["id"]),
            (((4, 4, 4, 3, 3),) * 3, None),
        ):
            with self.subTest(expected=expected):
                scorecards = [{"candidate_id": draft["id"], **dict(zip(workflow.CRITIC_AXES, values))}
                              for draft, values in zip(drafts, axes, strict=True)]
                manifest, evaluation, rendered = quality_optimizer._package_data(
                    package_id="test-short-form", created_at="2026-09-17T00:00:00Z",
                    mode="live", brief=context["brief"], evidence=context["evidence"],
                    proof=context["proof"], review=rescored_review(drafts, scorecards))
                self.assertEqual(manifest["recommended_candidate_id"], expected)
                self.assertEqual(evaluation["recommended_candidate_id"], expected)
                stored = json.loads(rendered["manifest.json"])
                self.assertEqual(stored["recommended_candidate_id"], expected)
                self.assertEqual(stored["review_status"], "READY_FOR_HUMAN_REVIEW" if expected else "BLOCKED")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA)
        self.folder = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.path_patch = patch.object(best_effort, "output_path", return_value=self.folder / "best-effort-post.md")
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_single_batch_shortlists_hook_first_above_18_and_embeds_every_text(self):
        supplied = batch()
        records = []
        with patch.object(quality_optimizer, "_ORIGINAL_RUN_ATTEMPT", return_value=supplied) as invoked, \
             patch.object(v1_completion, "current_run_id", return_value="test-short-form"), \
             patch.object(v1_completion, "record_decision", side_effect=lambda *a, **k: records.append((a, k))), \
             redirect_stdout(io.StringIO()):
            result = quality_optimizer._command_short_form(SimpleNamespace(
                command="draft", post_style="short-humorous", dry_run=False))
        self.assertEqual(result, 0)
        self.assertEqual(invoked.call_count, 1)
        saved = draft_delivery.load(self.folder)
        self.assertEqual(saved["selection"]["candidate_id"], "candidate-2")
        self.assertEqual(len(saved["results"]), 3)
        self.assertEqual((self.folder / "shortlisted-post.md").read_text(), supplied.candidates[1].text + "\n")
        for expected, row in zip(supplied.candidates, saved["results"], strict=True):
            self.assertEqual(row["candidate"]["text"], expected.text)
            self.assertEqual(row["text_sha256"], hashlib.sha256(expected.text.encode()).hexdigest())
        dashboard = {"checks": []}
        draft_delivery.attach(self.folder, dashboard)
        rendered = eval_dashboard_html.render_dashboard({"outcome": "PASS", "checks": []}, dashboard)
        for expected in supplied.candidates:
            self.assertIn(expected.text, rendered)
        self.assertIn("candidate-2 · SHORTLISTED", rendered)
        self.assertNotIn("See the printed candidate artifact path", rendered)
        for file in self.folder.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_18_is_delivered_but_never_claimed_as_shortlisted(self):
        supplied = attempt(batch().candidates[2])
        with patch.object(quality_optimizer, "_ORIGINAL_RUN_ATTEMPT", return_value=supplied), \
             patch.object(v1_completion, "current_run_id", return_value="test-below-bar"), \
             patch.object(v1_completion, "record_decision"), redirect_stdout(io.StringIO()):
            quality_optimizer._command_short_form(SimpleNamespace(command="draft", post_style="short-humorous"))
        saved = draft_delivery.load(self.folder)
        self.assertFalse(saved["selection"]["shortlisted"])
        self.assertFalse((self.folder / "shortlisted-post.md").exists())
        self.assertTrue((self.folder / "best-available-post.md").exists())

    def test_cycles_are_immutable_and_do_not_overwrite_same_candidate_id(self):
        with patch.object(v1_completion, "current_run_id", return_value="test-cycles"):
            draft_delivery.retain(batch(), cycle=1)
            draft_delivery.retain(batch(), cycle=2)
        self.assertEqual(len(draft_delivery.load(self.folder)["results"]), 6)
        with patch.object(v1_completion, "current_run_id", return_value="test-cycles"):
            with self.assertRaises(workflow.WorkflowError):
                draft_delivery.retain(batch(), cycle=1)

    def test_candidate_text_is_escaped_in_html(self):
        row = {"candidate_id": "candidate-1", "candidate": {"text": "<script>alert(1)</script>"}}
        rendered = eval_dashboard_html.render_dashboard({"checks": []}, {"checks": [], "results": [row]})
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>alert", rendered)

    def test_dashboard_uses_the_declared_total_contract_without_axis_veto(self):
        rows = [{"contract": "critic_total", "stage": "quality-cycle-1", "status": "PASS",
                 "subject_id": "candidate-1", "artifact_sha256": "abc", "evidence": {
                     "score": 23, "threshold": 19, "cycle": 1,
                     "acceptance_contract_version": "shortlist-above-18-v1",
                     "axes": dict(batch().candidates[0].axes)}}]
        with redirect_stdout(io.StringIO()):
            rendered = daily_spine_cli.render_eval_dashboard(rows)
        self.assertEqual(rendered["critic_scorecards"][0]["status"], "PASS")
        self.assertEqual(rendered["critic_scorecards"][0]["failure_codes"], [])


if __name__ == "__main__":
    unittest.main()
