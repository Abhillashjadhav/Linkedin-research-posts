"""Tests for score-only Critic review and the single-revision boundary."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import workflow


EXPECTED_AXES = (
    "hook_strength",
    "middle_escalation",
    "earned_closer",
    "specificity_and_source_quality",
    "voice_fidelity",
)


def selected_cluster() -> dict[str, object]:
    return {
        "slug": "agent-reliability",
        "why_now": "Recent primary evidence supports a product decision.",
        "dominant_take": "Reliability compounds across workflow steps.",
        "missing_angle": "Name the decision and what would falsify it.",
        "primary_sources": ["https://standards.example/reliability"],
        "source_quality_sufficient": True,
        "body_read_sufficient": True,
        "recency_sufficient": True,
        "stale": False,
    }


def strategy_brief() -> dict[str, object]:
    return workflow.build_strategy_brief(
        selected_cluster(),
        strategy_inputs={
            "target_reader": "AI product leaders",
            "reader_problem": "They need a defensible reliability decision.",
            "core_hypothesis": "Workflow reliability compounds across steps.",
            "product_decision": "Set an end-to-end reliability budget first.",
            "authority_statement": "Connect the mechanism to a falsifiable decision.",
        },
        strategy_input_origin="explicit-input",
        goal="authority",
    )


def evidence_records() -> list[dict[str, object]]:
    return [
        {
            "id": "claim-1",
            "title": "Agent reliability standard",
            "claim": "End-to-end reliability compounds across workflow steps.",
            "source": "https://standards.example/reliability",
            "source_quality": "primary",
            "body_read": True,
        },
        {
            "id": "claim-2",
            "title": "Evaluation reliability note",
            "claim": "A local evaluation can expose a compounding failure mode.",
            "source": "https://research.example/evaluation",
            "source_quality": "primary",
            "body_read": True,
        },
    ]


def draft_text(stem: str, count: int = 200) -> str:
    return " ".join(f"{stem}{index}" for index in range(count)) + "."


def candidate_set() -> list[dict[str, object]]:
    return [
        {
            "id": "candidate-1",
            "angle": "mechanism first",
            "text": draft_text("mechanism"),
            "claim_ids": ["claim-1"],
        },
        {
            "id": "candidate-2",
            "angle": "decision first",
            "text": draft_text("decision"),
            "claim_ids": ["claim-1"],
        },
        {
            "id": "candidate-3",
            "angle": "failure mode first",
            "text": draft_text("failure"),
            "claim_ids": ["claim-1"],
        },
    ]


def scorecard(
    candidate_id: str,
    scores: tuple[int, int, int, int, int] = (5, 5, 5, 5, 5),
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        **dict(zip(EXPECTED_AXES, scores, strict=True)),
    }


def scorecard_set(
    first: tuple[int, int, int, int, int] = (5, 5, 5, 5, 5),
    second: tuple[int, int, int, int, int] = (4, 4, 4, 4, 4),
    third: tuple[int, int, int, int, int] = (3, 5, 5, 5, 5),
) -> list[dict[str, object]]:
    return [
        scorecard("candidate-1", first),
        scorecard("candidate-2", second),
        scorecard("candidate-3", third),
    ]


class RecordingScoreProvider:
    def __init__(self, *responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[object] = []

    def __call__(self, candidates: object) -> list[dict[str, object]]:
        self.calls.append(deepcopy(candidates))
        if not self.responses:
            raise AssertionError("Critic was called more often than the test permits.")
        return self.responses.pop(0)


class RecordingRevisionProvider:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[tuple[object, object]] = []

    def __call__(self, candidate: object, scorecard: object) -> dict[str, object]:
        self.calls.append((deepcopy(candidate), deepcopy(scorecard)))
        return deepcopy(self.response)


class CriticScoreValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = candidate_set()

    def test_axes_are_the_recovered_five_axis_rubric(self) -> None:
        self.assertEqual(workflow.CRITIC_AXES, EXPECTED_AXES)

    def test_exact_scores_are_enriched_with_local_totals_and_bands(self) -> None:
        validated = workflow.validate_critic_scorecards(
            scorecard_set(
                first=(5, 5, 5, 5, 5),
                second=(5, 5, 4, 4, 4),
                third=(4, 4, 4, 4, 4),
            ),
            self.candidates,
        )
        by_id = {item["candidate_id"]: item for item in validated}
        self.assertEqual(by_id["candidate-1"]["raw_total"], 25)
        self.assertEqual(by_id["candidate-1"]["effective_total"], 25)
        self.assertIs(by_id["candidate-1"]["hook_cap_applied"], False)
        self.assertEqual(by_id["candidate-1"]["band"], "advance-to-gates")
        self.assertEqual(by_id["candidate-2"]["effective_total"], 22)
        self.assertEqual(by_id["candidate-2"]["band"], "one-light-revision")
        self.assertEqual(by_id["candidate-3"]["effective_total"], 20)
        self.assertEqual(by_id["candidate-3"]["band"], "below-critic-bar")

    def test_hook_at_three_or_below_caps_effective_total_at_eighteen(self) -> None:
        raw = scorecard_set(third=(3, 5, 5, 5, 5))
        validated = workflow.validate_critic_scorecards(raw, self.candidates)
        third = next(item for item in validated if item["candidate_id"] == "candidate-3")
        self.assertEqual(third["raw_total"], 23)
        self.assertEqual(third["effective_total"], 18)
        self.assertIs(third["hook_cap_applied"], True)
        self.assertEqual(third["band"], "below-critic-bar")

    def test_bands_use_exact_effective_total_boundaries(self) -> None:
        expectations = {
            25: "advance-to-gates",
            24: "advance-to-gates",
            23: "one-light-revision",
            22: "one-light-revision",
            21: "below-critic-bar",
            5: "below-critic-bar",
        }
        score_vectors = {
            25: (5, 5, 5, 5, 5),
            24: (5, 5, 5, 5, 4),
            23: (5, 5, 5, 4, 4),
            22: (5, 5, 4, 4, 4),
            21: (5, 4, 4, 4, 4),
            5: (1, 1, 1, 1, 1),
        }
        for total, expected in expectations.items():
            with self.subTest(total=total):
                one_candidate = [self.candidates[0]]
                validated = workflow.validate_critic_scorecards(
                    [scorecard("candidate-1", score_vectors[total])],
                    one_candidate,
                )
                self.assertEqual(validated[0]["effective_total"], total)
                self.assertEqual(validated[0]["band"], expected)

    def test_axis_values_reject_bool_float_string_and_out_of_range(self) -> None:
        invalid_values: tuple[object, ...] = (True, False, 4.0, "4", 0, 6, None)
        for value in invalid_values:
            with self.subTest(value=value):
                raw = scorecard_set()
                raw[0]["hook_strength"] = value
                with self.assertRaises(workflow.WorkflowError):
                    workflow.validate_critic_scorecards(raw, self.candidates)

    def test_scorecards_require_the_exact_raw_schema(self) -> None:
        cases: list[list[dict[str, object]]] = []
        missing = scorecard_set()
        del missing[0]["voice_fidelity"]
        cases.append(missing)
        extra = scorecard_set()
        extra[0]["overall_score"] = 25
        cases.append(extra)
        blank_id = scorecard_set()
        blank_id[0]["candidate_id"] = " "
        cases.append(blank_id)
        for raw in cases:
            with self.subTest(fields=set(raw[0])):
                with self.assertRaises(workflow.WorkflowError):
                    workflow.validate_critic_scorecards(raw, self.candidates)

    def test_each_candidate_must_have_one_and_only_one_scorecard(self) -> None:
        cases = {
            "missing": scorecard_set()[:2],
            "duplicate": [
                scorecard("candidate-1"),
                scorecard("candidate-1"),
                scorecard("candidate-3"),
            ],
            "unknown": [
                scorecard("candidate-1"),
                scorecard("candidate-2"),
                scorecard("unknown-candidate"),
            ],
        }
        for name, raw in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(workflow.WorkflowError):
                    workflow.validate_critic_scorecards(raw, self.candidates)

    def test_scorecard_errors_do_not_reflect_hostile_candidate_ids(self) -> None:
        sentinel = "private-score-sentinel\x1b]52;clipboard\x07"
        raw = scorecard_set()
        raw[2]["candidate_id"] = sentinel
        with self.assertRaises(workflow.WorkflowError) as raised:
            workflow.validate_critic_scorecards(raw, self.candidates)
        self.assertNotIn("private-score-sentinel", str(raised.exception))
        self.assertNotIn("\x1b", str(raised.exception))

    def test_ranking_is_deterministic_and_independent_of_input_order(self) -> None:
        raw = scorecard_set(
            first=(5, 5, 4, 5, 5),
            second=(5, 5, 5, 5, 5),
            third=(4, 4, 4, 4, 4),
        )
        forwards = workflow.rank_critic_scorecards(
            workflow.validate_critic_scorecards(raw, self.candidates)
        )
        backwards = workflow.rank_critic_scorecards(
            workflow.validate_critic_scorecards(
                list(reversed(raw)), list(reversed(self.candidates))
            )
        )
        expected = ["candidate-2", "candidate-1", "candidate-3"]
        self.assertEqual([item["candidate_id"] for item in forwards], expected)
        self.assertEqual([item["candidate_id"] for item in backwards], expected)

    def test_exact_score_ties_use_candidate_id_not_provider_order(self) -> None:
        raw = scorecard_set(
            first=(5, 5, 4, 4, 4),
            second=(5, 5, 4, 4, 4),
            third=(5, 5, 4, 4, 4),
        )
        ranked = workflow.rank_critic_scorecards(
            workflow.validate_critic_scorecards(
                [raw[2], raw[0], raw[1]],
                [self.candidates[2], self.candidates[0], self.candidates[1]],
            )
        )
        self.assertEqual(
            [item["candidate_id"] for item in ranked],
            ["candidate-1", "candidate-2", "candidate-3"],
        )

    def test_ties_compare_each_axis_in_declared_rubric_order(self) -> None:
        raw = scorecard_set(
            first=(5, 5, 4, 4, 4),
            second=(5, 4, 5, 4, 4),
            third=(5, 4, 4, 5, 4),
        )
        ranked = workflow.rank_critic_scorecards(
            workflow.validate_critic_scorecards(raw, self.candidates)
        )
        self.assertEqual(
            [item["candidate_id"] for item in ranked],
            ["candidate-1", "candidate-2", "candidate-3"],
        )

    def test_ranking_rejects_inconsistent_or_unhashable_computed_fields(self) -> None:
        validated = workflow.validate_critic_scorecards(
            scorecard_set(), self.candidates
        )
        for field, value in (
            ("raw_total", 1),
            ("effective_total", 99),
            ("hook_cap_applied", "false"),
            ("band", ["advance-to-gates"]),
        ):
            with self.subTest(field=field):
                hostile = deepcopy(validated)
                hostile[0][field] = value
                with self.assertRaises(workflow.WorkflowError):
                    workflow.rank_critic_scorecards(hostile)


class CriticReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = candidate_set()
        self.brief = strategy_brief()
        self.evidence = evidence_records()

    def _review(
        self,
        scores: RecordingScoreProvider,
        revision: RecordingRevisionProvider,
    ) -> dict[str, object]:
        return workflow.run_critic_review(
            self.candidates,
            self.brief,
            self.evidence,
            scores,
            revision,
        )

    def test_only_initial_score_leader_in_revision_band_is_revised_once(self) -> None:
        revised = deepcopy(self.candidates[0])
        revised["text"] = draft_text("revisedmechanism")
        scores = RecordingScoreProvider(
            scorecard_set(
                first=(5, 5, 5, 4, 4),
                second=(5, 4, 4, 4, 4),
                third=(3, 5, 5, 5, 5),
            ),
            [scorecard("candidate-1", (5, 5, 5, 5, 5))],
        )
        revision = RecordingRevisionProvider(revised)

        result = self._review(scores, revision)

        self.assertEqual(len(revision.calls), 1)
        self.assertEqual(revision.calls[0][0], self.candidates[0])
        self.assertEqual(revision.calls[0][1]["candidate_id"], "candidate-1")
        self.assertEqual(len(scores.calls), 2)
        self.assertEqual(scores.calls[1], [revised])
        self.assertEqual(result["revision_count"], 1)
        self.assertEqual(result["revision_candidate_id"], "candidate-1")
        self.assertEqual(result["score_leader_id"], "candidate-1")
        self.assertEqual(result["candidates"][0], revised)
        self.assertEqual(result["scorecards"][0]["effective_total"], 25)

    def test_advance_or_below_bar_leader_is_not_revised(self) -> None:
        cases = {
            "advance": scorecard_set(
                first=(5, 5, 5, 5, 5),
                second=(5, 5, 4, 4, 4),
                third=(4, 4, 4, 4, 4),
            ),
            "below": scorecard_set(
                first=(5, 4, 4, 4, 4),
                second=(4, 4, 4, 4, 4),
                third=(3, 5, 5, 5, 5),
            ),
        }
        for name, raw in cases.items():
            with self.subTest(case=name):
                scores = RecordingScoreProvider(raw)
                revision = RecordingRevisionProvider(self.candidates[0])
                result = self._review(scores, revision)
                self.assertEqual(len(scores.calls), 1)
                self.assertEqual(revision.calls, [])
                self.assertEqual(result["revision_count"], 0)
                self.assertIsNone(result["revision_candidate_id"])

    def test_revision_does_not_recurse_when_rescore_stays_in_revision_band(self) -> None:
        revised = deepcopy(self.candidates[0])
        revised["text"] = draft_text("revisedmechanism")
        scores = RecordingScoreProvider(
            scorecard_set(first=(5, 5, 5, 4, 4)),
            [scorecard("candidate-1", (5, 5, 5, 4, 4))],
        )
        revision = RecordingRevisionProvider(revised)
        result = self._review(scores, revision)
        self.assertEqual(len(scores.calls), 2)
        self.assertEqual(len(revision.calls), 1)
        self.assertEqual(result["revision_count"], 1)

    def test_revision_must_preserve_id_angle_and_original_claim_subset(self) -> None:
        invalid_revisions = []
        changed_id = deepcopy(self.candidates[0])
        changed_id["id"] = "candidate-2"
        invalid_revisions.append(changed_id)
        changed_angle = deepcopy(self.candidates[0])
        changed_angle["angle"] = "a new unreviewed angle"
        invalid_revisions.append(changed_angle)
        added_known_claim = deepcopy(self.candidates[0])
        added_known_claim["claim_ids"] = ["claim-1", "claim-2"]
        invalid_revisions.append(added_known_claim)
        malformed_claim = deepcopy(self.candidates[0])
        malformed_claim["claim_ids"] = [{"id": "claim-1"}]
        invalid_revisions.append(malformed_claim)
        for revised in invalid_revisions:
            with self.subTest(revised=revised):
                scores = RecordingScoreProvider(
                    scorecard_set(first=(5, 5, 5, 4, 4))
                )
                revision = RecordingRevisionProvider(revised)
                with self.assertRaises(workflow.WorkflowError):
                    self._review(scores, revision)
                self.assertEqual(len(scores.calls), 1)

    def test_revision_is_revalidated_against_the_complete_draft_contract(self) -> None:
        invalid_revisions = []
        too_short = deepcopy(self.candidates[0])
        too_short["text"] = draft_text("short", 20)
        invalid_revisions.append(too_short)
        banned = deepcopy(self.candidates[0])
        banned["text"] = "Let's dive in. " + draft_text("grounded", 196)
        invalid_revisions.append(banned)
        duplicates_another_candidate = deepcopy(self.candidates[0])
        duplicates_another_candidate["text"] = self.candidates[1]["text"]
        invalid_revisions.append(duplicates_another_candidate)
        invalid_revisions.append(deepcopy(self.candidates[0]))
        for revised in invalid_revisions:
            with self.subTest(text=str(revised["text"])[:30]):
                scores = RecordingScoreProvider(
                    scorecard_set(first=(5, 5, 5, 4, 4))
                )
                revision = RecordingRevisionProvider(revised)
                with self.assertRaises(workflow.WorkflowError):
                    self._review(scores, revision)
                self.assertEqual(len(scores.calls), 1)

    def test_malformed_rescore_fails_instead_of_silently_using_initial_score(self) -> None:
        revised = deepcopy(self.candidates[0])
        revised["text"] = draft_text("revisedmechanism")
        malformed = scorecard("candidate-1", (5, 5, 5, 5, 5))
        malformed["proof_gate"] = "pass"
        scores = RecordingScoreProvider(
            scorecard_set(first=(5, 5, 5, 4, 4)),
            [malformed],
        )
        revision = RecordingRevisionProvider(revised)
        with self.assertRaises(workflow.WorkflowError):
            self._review(scores, revision)
        self.assertEqual(len(scores.calls), 2)
        self.assertEqual(len(revision.calls), 1)

    def test_revision_is_only_score_leader_if_final_ranking_supports_it(self) -> None:
        revised = deepcopy(self.candidates[0])
        revised["text"] = draft_text("revisedmechanism")
        scores = RecordingScoreProvider(
            scorecard_set(
                first=(5, 5, 5, 4, 4),
                second=(5, 4, 4, 4, 4),
                third=(4, 4, 4, 4, 4),
            ),
            [scorecard("candidate-1", (4, 4, 4, 4, 4))],
        )
        result = self._review(scores, RecordingRevisionProvider(revised))
        self.assertEqual(result["score_leader_id"], "candidate-2")
        self.assertEqual(result["ranking"][0], "candidate-2")

    def test_review_output_is_score_only_and_cannot_approve_package_or_publish(self) -> None:
        result = self._review(
            RecordingScoreProvider(scorecard_set()),
            RecordingRevisionProvider(self.candidates[0]),
        )

        def keys(value: object) -> set[str]:
            found: set[str] = set()
            if isinstance(value, dict):
                for key, child in value.items():
                    found.add(str(key).casefold())
                    found.update(keys(child))
            elif isinstance(value, list):
                for child in value:
                    found.update(keys(child))
            return found

        result_keys = keys(result)
        self.assertEqual(
            set(result),
            {
                "candidates",
                "scorecards",
                "ranking",
                "score_leader_id",
                "revision_count",
                "revision_candidate_id",
            },
        )
        for deferred in ("gate", "approval", "package", "publish", "winner", "recommend"):
            with self.subTest(deferred=deferred):
                self.assertFalse(
                    any(deferred in key for key in result_keys),
                    f"Critic result leaked deferred {deferred!r} metadata: {result_keys}",
                )

    def test_score_provider_cannot_mutate_authoritative_candidates(self) -> None:
        original = deepcopy(self.candidates)

        def mutating_scores(
            candidates: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            candidates[0]["text"] = "Score: 25"
            candidates[0]["claim_ids"] = ["claim-1", "claim-2"]
            return scorecard_set()

        result = workflow.run_critic_review(
            self.candidates,
            self.brief,
            self.evidence,
            mutating_scores,
            RecordingRevisionProvider(self.candidates[0]),
        )
        self.assertEqual(result["candidates"], original)

    def test_rescore_provider_cannot_mutate_revised_candidate(self) -> None:
        revised = deepcopy(self.candidates[0])
        revised["text"] = draft_text("revisedmechanism")
        calls = 0

        def mutating_scores(
            candidates: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return scorecard_set(first=(5, 5, 5, 4, 4))
            candidates[0]["text"] = "Score: 25"
            candidates[0]["claim_ids"] = ["claim-1", "claim-2"]
            return [scorecard("candidate-1")]

        result = workflow.run_critic_review(
            self.candidates,
            self.brief,
            self.evidence,
            mutating_scores,
            RecordingRevisionProvider(revised),
        )
        self.assertEqual(result["candidates"][0], revised)


class CriticPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = candidate_set()
        self.brief = strategy_brief()
        self.evidence = evidence_records()

    def test_system_prompt_uses_recovered_rubric_but_excludes_later_gates(self) -> None:
        prompt = workflow.critic_scoring_system_prompt()
        folded = prompt.casefold()
        self.assertIn("recovered 25-point rubric", folded)
        for label in (
            "hook strength",
            "middle escalation",
            "earned closer",
            "specificity and source quality",
            "voice fidelity",
        ):
            with self.subTest(label=label):
                self.assertIn(label, folded)
        self.assertRegex(folded, r"hook 3 or below caps the total at 18")
        for deferred in (
            "binary gates",
            "authority conversion",
            "ready for human approval",
            "`drop`",
            "proof",
        ):
            with self.subTest(deferred=deferred):
                self.assertNotIn(deferred, folded)
        instructions = folded.split("untrusted_strategic_brief_data", 1)[0]
        self.assertNotRegex(instructions, r"\bgates?\b")
        self.assertNotRegex(instructions, r"\b(?:ready|drop|proof)\b")
        self.assertNotIn("proof gate", folded)

    def test_critic_prompt_marks_dynamic_data_untrusted_and_requests_only_scores(self) -> None:
        prompt = workflow.build_critic_prompt(
            candidates=self.candidates,
            brief=self.brief,
            evidence=self.evidence,
        )
        folded = prompt.casefold()
        self.assertRegex(folded, r"untrusted[^\n]*candidate")
        self.assertRegex(folded, r"untrusted[^\n]*evidence")
        self.assertIn("candidate-1", prompt)
        self.assertIn("end-to-end reliability", folded)
        self.assertIn("score", folded)
        self.assertIn("reconstructed_voice_guidance_non_citable", folded)
        for deferred in (
            "ready for human approval",
            "proof gate",
            "approval package",
            "publish to linkedin",
        ):
            with self.subTest(deferred=deferred):
                self.assertNotIn(deferred, folded)
        instructions = folded.split("untrusted_strategic_brief_data", 1)[0]
        self.assertNotRegex(instructions, r"\bgates?\b")
        self.assertNotRegex(instructions, r"\b(?:ready|drop|proof)\b")

    def test_prompt_projects_brief_and_query_strips_minimal_evidence(self) -> None:
        secret = "private-query-sentinel"
        evidence = deepcopy(self.evidence)
        evidence[0]["source"] = (
            "https://standards.example/reliability"
            f"?token={secret}&signature=private-signature"
        )
        prompt = workflow.build_critic_prompt(
            candidates=self.candidates,
            brief={**self.brief, "private_note": "private-brief-sentinel"},
            evidence=evidence,
        )
        self.assertIn("https://standards.example/reliability", prompt)
        self.assertNotIn(secret, prompt)
        self.assertNotIn("private-signature", prompt)
        self.assertNotIn("private-brief-sentinel", prompt)

    def test_prompt_rejects_unprojected_evidence_metadata(self) -> None:
        unsafe = deepcopy(self.evidence)
        unsafe[0]["content_hash"] = "private-content-hash-sentinel"
        with self.assertRaisesRegex(workflow.WorkflowError, "minimal evidence schema"):
            workflow.build_critic_prompt(
                candidates=self.candidates,
                brief=self.brief,
                evidence=unsafe,
            )


class CriticInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = candidate_set()
        self.brief = strategy_brief()
        self.evidence = evidence_records()

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which")
    def test_critic_requires_explicit_egress_consent_before_path_lookup(
        self, which: object, run: object
    ) -> None:
        for consent in (False, None, 1):
            with self.subTest(consent=consent):
                with self.assertRaisesRegex(workflow.WorkflowError, "explicit consent"):
                    workflow.invoke_critic(
                        candidates=self.candidates,
                        brief=self.brief,
                        evidence=self.evidence,
                        allow_model_egress=consent,
                    )
        which.assert_not_called()
        run.assert_not_called()

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which", return_value="/opt/claude")
    def test_critic_is_tool_free_stateless_and_sends_dynamic_data_only_on_stdin(
        self, _which: object, run: object
    ) -> None:
        raw = scorecard_set()
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": {"scorecards": raw}}),
            stderr="",
        )
        result = workflow.invoke_critic(
            candidates=self.candidates,
            brief=self.brief,
            evidence=self.evidence,
            allow_model_egress=True,
            timeout=19,
        )
        self.assertEqual(result, raw)
        command = run.call_args.args[0]
        for flag in (
            "--print",
            "--safe-mode",
            "--output-format",
            "--json-schema",
            "--system-prompt",
            "--tools",
            "--permission-mode",
            "--no-chrome",
            "--disable-slash-commands",
            "--no-session-persistence",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(
            run.call_args.kwargs["input"],
            workflow.build_critic_prompt(
                candidates=self.candidates,
                brief=self.brief,
                evidence=self.evidence,
            ),
        )
        self.assertNotIn("mechanism1", " ".join(command))
        self.assertNotIn("claim-1", " ".join(command))
        self.assertEqual(run.call_args.kwargs["cwd"], workflow.REPO_ROOT)
        self.assertEqual(run.call_args.kwargs["timeout"], 19)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertFalse(run.call_args.kwargs["check"])

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which", return_value="/opt/claude")
    def test_critic_failures_and_malformed_output_do_not_leak_stderr(
        self, _which: object, run: object
    ) -> None:
        secret = "ANTHROPIC_API_KEY=private-critic-sentinel"
        failures = (
            SimpleNamespace(returncode=1, stdout="", stderr=secret),
            SimpleNamespace(returncode=0, stdout="not-json", stderr=secret),
        )
        for failure in failures:
            with self.subTest(returncode=failure.returncode):
                run.return_value = failure
                with self.assertRaises(workflow.WorkflowError) as raised:
                    workflow.invoke_critic(
                        candidates=self.candidates,
                        brief=self.brief,
                        evidence=self.evidence,
                        allow_model_egress=True,
                    )
                self.assertNotIn(secret, str(raised.exception))

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which", return_value="/private/broken-claude")
    def test_critic_start_failure_does_not_reflect_private_path(
        self, _which: object, run: object
    ) -> None:
        run.side_effect = OSError("cannot execute /private/broken-claude")
        with self.assertRaisesRegex(workflow.WorkflowError, "could not start") as raised:
            workflow.invoke_critic(
                candidates=self.candidates,
                brief=self.brief,
                evidence=self.evidence,
                allow_model_egress=True,
            )
        self.assertNotIn("/private/broken-claude", str(raised.exception))


class WriterRevisionInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = candidate_set()[0]
        self.brief = strategy_brief()
        self.evidence = evidence_records()
        self.voice = {
            "voice_guide": "Direct practitioner voice sentinel.",
            "performance_anchors": "Mechanism anchor sentinel.",
            "provenance": "reconstructed-style-guidance",
        }

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which")
    def test_revision_requires_explicit_egress_consent_before_path_lookup(
        self, which: object, run: object
    ) -> None:
        for consent in (False, None, 1):
            with self.subTest(consent=consent):
                with self.assertRaisesRegex(workflow.WorkflowError, "explicit consent"):
                    workflow.invoke_writer_revision(
                        candidate=self.candidate,
                        scorecard=scorecard(
                            "candidate-1", (5, 5, 5, 4, 4)
                        ),
                        brief=self.brief,
                        evidence=self.evidence,
                        allow_model_egress=consent,
                        voice_guidance=self.voice,
                    )
        which.assert_not_called()
        run.assert_not_called()

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which", return_value="/opt/claude")
    def test_revision_writer_is_tool_free_stateless_and_stdin_only(
        self, _which: object, run: object
    ) -> None:
        revised = deepcopy(self.candidate)
        revised["text"] = draft_text("revisedmechanism")
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": {"candidate": revised}}),
            stderr="",
        )
        result = workflow.invoke_writer_revision(
            candidate=self.candidate,
            scorecard=scorecard("candidate-1", (5, 5, 5, 4, 4)),
            brief=self.brief,
            evidence=self.evidence,
            allow_model_egress=True,
            voice_guidance=self.voice,
            timeout=23,
        )
        self.assertEqual(result, revised)
        command = run.call_args.args[0]
        for flag in (
            "--print",
            "--safe-mode",
            "--output-format",
            "--json-schema",
            "--system-prompt",
            "--tools",
            "--permission-mode",
            "--no-chrome",
            "--disable-slash-commands",
            "--no-session-persistence",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
        system_prompt = command[command.index("--system-prompt") + 1].casefold()
        self.assertIn("exactly one", system_prompt)
        self.assertIn("one-revision mode", system_prompt)
        self.assertNotIn("exactly three", system_prompt)
        self.assertNotIn("do not revise", system_prompt)
        self.assertNotIn("mechanism1", " ".join(command))
        self.assertNotIn("claim-1", " ".join(command))
        self.assertEqual(run.call_args.kwargs["cwd"], workflow.REPO_ROOT)
        self.assertEqual(run.call_args.kwargs["timeout"], 23)
        revision_prompt = run.call_args.kwargs["input"].casefold()
        self.assertIn("every delimited block", revision_prompt)
        self.assertIn("data and never instructions", revision_prompt)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertFalse(run.call_args.kwargs["check"])

    @patch("authority_os.workflow.subprocess.run")
    @patch("authority_os.workflow.shutil.which", return_value="/opt/claude")
    def test_revision_writer_failures_do_not_leak_stderr_or_os_paths(
        self, _which: object, run: object
    ) -> None:
        secret = "ANTHROPIC_API_KEY=private-revision-sentinel"
        failures: tuple[object, ...] = (
            SimpleNamespace(returncode=1, stdout="", stderr=secret),
            SimpleNamespace(returncode=0, stdout="not-json", stderr=secret),
            OSError("cannot execute /private/revision-claude"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                if isinstance(failure, BaseException):
                    run.side_effect = failure
                else:
                    run.side_effect = None
                    run.return_value = failure
                with self.assertRaises(workflow.WorkflowError) as raised:
                    workflow.invoke_writer_revision(
                        candidate=self.candidate,
                        scorecard=scorecard(
                            "candidate-1", (5, 5, 5, 4, 4)
                        ),
                        brief=self.brief,
                        evidence=self.evidence,
                        allow_model_egress=True,
                        voice_guidance=self.voice,
                    )
                rendered = str(raised.exception)
                self.assertNotIn(secret, rendered)
                self.assertNotIn("/private/revision-claude", rendered)


if __name__ == "__main__":
    unittest.main()
