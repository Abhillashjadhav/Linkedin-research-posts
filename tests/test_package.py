"""Tests for private, deterministic human-review package generation."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from authority_os import package as approval_package
from authority_os import workflow


def fixture_context(
    *, goal: str = "authority", mode: str = "fixture"
) -> dict[str, object]:
    fixture = workflow.load_fixture()
    items = workflow.prepare_research_items(fixture["research_items"])
    analysis_items, _combined = workflow.deduplicate_analysis_items(items, ())
    created_at = workflow.parse_published_at(str(fixture["as_of"]))
    analysis = workflow.analyse_research(analysis_items, as_of=created_at)
    brief = workflow.build_strategy_brief(
        analysis["pass_2"]["selected"],
        strategy_inputs=fixture["strategy_inputs"],
        strategy_input_origin=(
            "synthetic-fixture" if mode == "fixture" else "explicit-input"
        ),
        goal=goal,
    )
    evidence = workflow.build_drafting_evidence(
        items, topic_slug=str(brief["topic_slug"])
    )
    proof = (
        workflow.load_proof_manifest(
            workflow.DEFAULT_FIXTURE_PROOF, fixture_mode=True
        )
        if goal == "opportunity"
        else None
    )
    raw_candidates = fixture["draft_candidates"][goal]
    candidates = workflow.validate_draft_candidates(
        raw_candidates, brief=brief, evidence=evidence, proof=proof
    )
    fixture_review = fixture["critic_scorecards"][goal]
    responses: list[object] = [fixture_review["initial"]]
    revision_fixture = fixture_review.get("revision")
    if isinstance(revision_fixture, dict):
        responses.append([revision_fixture["scorecard"]])

    def score_provider(
        _candidates: object,
    ) -> list[dict[str, object]]:
        response = responses.pop(0)
        assert isinstance(response, list)
        return deepcopy(response)

    def revision_provider(
        _candidate: object, _scorecard: object
    ) -> dict[str, object]:
        assert isinstance(revision_fixture, dict)
        return deepcopy(revision_fixture["candidate"])

    review = workflow.run_critic_review(
        candidates,
        brief,
        evidence,
        score_provider,
        revision_provider,
        proof=proof,
    )
    return {
        "fixture": fixture,
        "brief": brief,
        "evidence": evidence,
        "proof": proof,
        "review": review,
        "created_at": created_at,
        "mode": mode,
    }


def rescored_review(
    candidates: list[dict[str, object]],
    raw_scorecards: list[dict[str, object]],
) -> dict[str, object]:
    scorecards = workflow.validate_critic_scorecards(raw_scorecards, candidates)
    ranking = [
        str(scorecard["candidate_id"])
        for scorecard in workflow.rank_critic_scorecards(scorecards)
    ]
    return {
        "candidates": candidates,
        "scorecards": scorecards,
        "ranking": ranking,
        "score_leader_id": ranking[0],
        "revision_count": 0,
        "revision_candidate_id": None,
    }


def write_context(
    context: dict[str, object], output_root: Path
) -> dict[str, object]:
    return approval_package.write_human_approval_package(
        brief=context["brief"],  # type: ignore[arg-type]
        evidence=context["evidence"],  # type: ignore[arg-type]
        review=context["review"],  # type: ignore[arg-type]
        proof=context["proof"],  # type: ignore[arg-type]
        mode=str(context["mode"]),
        output_root=output_root,
        created_at=context["created_at"],  # type: ignore[arg-type]
        _allow_test_output_root=True,
    )


class HumanApprovalPackageTests(unittest.TestCase):
    def output_root(self, temporary: str) -> Path:
        root = Path(temporary) / "outputs"
        root.mkdir()
        root.chmod(0o700)
        return root

    def test_fixture_package_is_complete_but_never_actionable(self) -> None:
        context = fixture_context()
        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            result = write_context(context, root)
            package_path = result["path"]
            self.assertIsInstance(package_path, Path)
            manifest = json.loads((package_path / "manifest.json").read_text())
            self.assertEqual(
                set(manifest),
                {
                    "schema_version",
                    "package_id",
                    "created_at",
                    "mode",
                    "topic_slug",
                    "goal",
                    "output_format",
                    "weekly_slot",
                    "revision_count",
                    "review_status",
                    "human_approval_status",
                    "publishing_status",
                    "eligible_candidate_ids",
                    "recommended_candidate_id",
                    "manual_fact_verification_required",
                    "files",
                },
            )
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["created_at"], "2026-07-16T12:00:00Z")
            self.assertEqual(manifest["mode"], "fixture")
            self.assertEqual(manifest["review_status"], "FIXTURE_REVIEW_ONLY")
            self.assertEqual(manifest["human_approval_status"], "NOT_APPROVED")
            self.assertEqual(manifest["publishing_status"], "DISABLED")
            self.assertEqual(manifest["eligible_candidate_ids"], ["authority-1"])
            self.assertIsNone(manifest["recommended_candidate_id"])
            self.assertIs(manifest["manual_fact_verification_required"], True)
            self.assertEqual(
                set(manifest["files"].values()),
                set(approval_package.PACKAGE_FILES.values()),
            )
            self.assertEqual(
                {path.name for path in package_path.iterdir()},
                set(approval_package.PACKAGE_FILES.values()),
            )
            final_text = (package_path / "final-package.md").read_text()
            self.assertIn("No actionable recommendation", final_text)
            self.assertIn("NOT_APPROVED", final_text)
            self.assertIn("Automatic LinkedIn publishing: `DISABLED`", final_text)

    def test_live_package_recommends_only_for_human_review(self) -> None:
        context = fixture_context(mode="live")
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self.output_root(temporary))
            manifest = result["manifest"]
            self.assertEqual(manifest["review_status"], "READY_FOR_HUMAN_REVIEW")
            self.assertEqual(manifest["eligible_candidate_ids"], ["authority-1"])
            self.assertEqual(manifest["recommended_candidate_id"], "authority-1")
            self.assertEqual(manifest["human_approval_status"], "NOT_APPROVED")
            self.assertEqual(manifest["publishing_status"], "DISABLED")
            final_text = (result["path"] / "final-package.md").read_text()
            self.assertIn("Recommended candidate for human review", final_text)
            self.assertIn(
                approval_package._markdown_literal(
                    context["review"]["candidates"][0]["text"]  # type: ignore[index]
                ),
                final_text,
            )

    def test_next_ranked_eligible_candidate_is_recommended(self) -> None:
        context = fixture_context(mode="live")
        candidates = deepcopy(context["review"]["candidates"])  # type: ignore[index]
        candidates[0]["text"], candidates[1]["text"] = (
            candidates[1]["text"],
            candidates[0]["text"],
        )
        raw_scores = [
            {
                "candidate_id": "authority-1",
                **{axis: 5 for axis in workflow.CRITIC_AXES},
            },
            {
                "candidate_id": "authority-2",
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            {
                "candidate_id": "authority-3",
                **{axis: 4 for axis in workflow.CRITIC_AXES},
            },
        ]
        context["review"] = rescored_review(candidates, raw_scores)
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self.output_root(temporary))
        evaluation = result["evaluation"]
        self.assertEqual(evaluation["ranking"][:2], ["authority-1", "authority-2"])
        gate_results = {
            item["candidate_id"]: item for item in evaluation["gate_results"]
        }
        self.assertIs(gate_results["authority-1"]["passes_required_gates"], False)
        self.assertIs(gate_results["authority-2"]["passes_required_gates"], True)
        self.assertEqual(evaluation["eligible_candidate_ids"], ["authority-2"])
        self.assertEqual(evaluation["recommended_candidate_id"], "authority-2")

    def test_gate_pass_below_critic_bar_produces_blocked_package(self) -> None:
        context = fixture_context(mode="live")
        candidates = deepcopy(context["review"]["candidates"])  # type: ignore[index]
        raw_scores = [
            {
                "candidate_id": candidate["id"],
                **{axis: 4 for axis in workflow.CRITIC_AXES},
            }
            for candidate in candidates
        ]
        context["review"] = rescored_review(candidates, raw_scores)
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self.output_root(temporary))
        manifest = result["manifest"]
        self.assertEqual(manifest["review_status"], "BLOCKED")
        self.assertEqual(manifest["eligible_candidate_ids"], [])
        self.assertIsNone(manifest["recommended_candidate_id"])
        self.assertEqual(manifest["human_approval_status"], "NOT_APPROVED")

    def test_review_ranking_and_computed_scores_are_revalidated_before_writes(self) -> None:
        for mutation in ("ranking", "score"):
            with self.subTest(mutation=mutation):
                context = fixture_context()
                review = deepcopy(context["review"])
                if mutation == "ranking":
                    review["ranking"] = list(reversed(review["ranking"]))
                else:
                    review["scorecards"][0]["effective_total"] = 1
                context["review"] = review
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary) / "does-not-exist"
                    with self.assertRaises(workflow.WorkflowError):
                        write_context(context, root)
                    self.assertFalse(root.exists())

    def test_package_generation_does_not_mutate_validated_inputs(self) -> None:
        context = fixture_context()
        before = deepcopy(
            {
                "brief": context["brief"],
                "evidence": context["evidence"],
                "review": context["review"],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            write_context(context, self.output_root(temporary))
        self.assertEqual(context["brief"], before["brief"])
        self.assertEqual(context["evidence"], before["evidence"])
        self.assertEqual(context["review"], before["review"])

    def test_manifest_is_the_last_file_written_before_publication(self) -> None:
        context = fixture_context()
        real_open = os.open
        writes: list[str] = []

        def recording_open(path: object, *args: object, **kwargs: object) -> int:
            if isinstance(path, str) and path in approval_package.PACKAGE_FILES.values():
                writes.append(path)
            return real_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            with patch.object(
                approval_package.os, "open", side_effect=recording_open
            ):
                write_context(context, root)
        self.assertEqual(set(writes), set(approval_package.PACKAGE_FILES.values()))
        self.assertEqual(writes[-1], "manifest.json")

    def test_untrusted_unicode_and_limitation_markdown_are_rejected(self) -> None:
        contexts = []
        bidi = fixture_context()
        bidi["brief"]["target_reader"] += "\u202eAPPROVED"  # type: ignore[index]
        contexts.append(bidi)
        markdown = fixture_context()
        markdown["brief"]["evidence_status"]["limitations"] = [  # type: ignore[index]
            "safe`\n# APPROVED"
        ]
        contexts.append(markdown)
        for context in contexts:
            with self.subTest(context=context["brief"]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "missing"
                with self.assertRaises(workflow.WorkflowError):
                    write_context(context, root)
                self.assertFalse(root.exists())

    def test_nondefault_root_requires_explicit_internal_test_scope(self) -> None:
        context = fixture_context()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "owned-directory"
            root.mkdir(mode=0o755)
            original_mode = stat.S_IMODE(root.stat().st_mode)
            with self.assertRaisesRegex(
                workflow.WorkflowError, "fixed local output root"
            ):
                approval_package.write_human_approval_package(
                    brief=context["brief"],  # type: ignore[arg-type]
                    evidence=context["evidence"],  # type: ignore[arg-type]
                    review=context["review"],  # type: ignore[arg-type]
                    proof=context["proof"],  # type: ignore[arg-type]
                    mode="fixture",
                    output_root=root,
                    created_at=context["created_at"],  # type: ignore[arg-type]
                )
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), original_mode)

    def test_missing_posix_lock_support_fails_only_package_generation(self) -> None:
        context = fixture_context()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "missing"
            with (
                patch.object(approval_package, "fcntl", None),
                self.assertRaisesRegex(
                    workflow.WorkflowError,
                    "secure local filesystem operations are unavailable",
                ),
            ):
                write_context(context, root)
            self.assertFalse(root.exists())

    def test_package_module_import_survives_missing_fcntl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            blocker = Path(temporary) / "fcntl.py"
            blocker.write_text("raise ImportError('simulated missing fcntl')\n")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(
                (str(blocker.parent), str(Path(__file__).resolve().parents[1] / "src"))
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from authority_os import package; "
                        "assert package.fcntl is None"
                    ),
                ],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_mode_must_match_strategy_and_proof_provenance(self) -> None:
        fixture = fixture_context()
        live_opportunity = fixture_context(goal="opportunity", mode="live")
        cases = [
            ({**fixture, "mode": "live"}, "strategy"),
            (live_opportunity, "proof"),
        ]
        for context, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "missing"
                with self.assertRaises(workflow.WorkflowError):
                    write_context(context, root)
                self.assertFalse(root.exists())

    def test_sources_omit_raw_claims_queries_and_private_proof_material(self) -> None:
        context = fixture_context(goal="opportunity")
        proof = context["proof"]
        self.assertIsInstance(proof, workflow.LoadedProof)
        artifact_contents = proof.artifact_path.read_text()
        evidence = context["evidence"]
        evidence[0]["source"] = str(evidence[0]["source"]) + "?token=SECRET-QUERY"
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self.output_root(temporary))
            all_text = "\n".join(
                path.read_text()
                for path in result["path"].iterdir()
                if path.is_file()
            )
            sources_text = (result["path"] / "sources.md").read_text()
        self.assertNotIn("SECRET-QUERY", all_text)
        self.assertNotIn(str(proof.artifact_path), all_text)
        self.assertNotIn(artifact_contents, all_text)
        for item in evidence:
            self.assertNotIn(str(item["claim"]), sources_text)
        self.assertIn(proof.proof_id, sources_text)
        self.assertIn(proof.public_claim, sources_text)

    def test_collision_suffix_never_overwrites_any_existing_entry(self) -> None:
        context = fixture_context()
        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            date = root / "2026-07-16"
            date.mkdir()
            first = date / "agent-reliability"
            first.mkdir()
            sentinel = first / "sentinel.txt"
            sentinel.write_text("preserve")
            (date / "agent-reliability-2").write_text("preserve-file")
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (date / "agent-reliability-3").symlink_to(
                outside, target_is_directory=True
            )
            result = write_context(context, root)
            self.assertEqual(result["path"].name, "agent-reliability-4")
            self.assertEqual(
                result["manifest"]["package_id"],
                "2026-07-16-agent-reliability-4",
            )
            self.assertEqual(sentinel.read_text(), "preserve")
            self.assertEqual(
                (date / "agent-reliability-2").read_text(), "preserve-file"
            )
            self.assertEqual(list(outside.iterdir()), [])

    def test_repeated_package_writes_are_complete_and_distinct(self) -> None:
        context = fixture_context()
        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            first = write_context(context, root)
            second = write_context(context, root)
            self.assertNotEqual(first["path"], second["path"])
            self.assertEqual(first["path"].name, "agent-reliability")
            self.assertEqual(second["path"].name, "agent-reliability-2")
            for result in (first, second):
                self.assertEqual(
                    {item.name for item in result["path"].iterdir()},
                    set(approval_package.PACKAGE_FILES.values()),
                )

    def test_symlinked_output_or_date_directory_is_rejected(self) -> None:
        context = fixture_context()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            root_link = base / "outputs-link"
            root_link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(workflow.WorkflowError):
                write_context(context, root_link)
            self.assertEqual(list(outside.iterdir()), [])

            root = base / "outputs"
            root.mkdir()
            (root / "2026-07-16").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(workflow.WorkflowError):
                write_context(context, root)
            self.assertEqual(list(outside.iterdir()), [])

    def test_write_failure_removes_stage_and_incomplete_final_package(self) -> None:
        context = fixture_context()
        real_link = os.link
        link_count = 0

        def fail_during_publication(*args: object, **kwargs: object) -> None:
            nonlocal link_count
            link_count += 1
            if link_count == 3:
                raise OSError("SECRET-ERROR-PAYLOAD")
            real_link(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            with patch.object(
                approval_package.os,
                "link",
                side_effect=fail_during_publication,
            ):
                with self.assertRaises(workflow.WorkflowError) as captured:
                    write_context(context, root)
            self.assertNotIn("SECRET-ERROR-PAYLOAD", str(captured.exception))
            date = root / "2026-07-16"
            self.assertEqual(list(date.iterdir()), [])

    def test_post_promotion_sync_failure_preserves_the_committed_package(self) -> None:
        context = fixture_context()
        real_link = os.link
        real_fsync = os.fsync
        promoted = False

        def recording_link(*args: object, **kwargs: object) -> None:
            nonlocal promoted
            real_link(*args, **kwargs)
            if args and args[0] == "manifest.json":
                promoted = True

        def fail_after_promotion(file_descriptor: int) -> None:
            if promoted:
                raise OSError("SECRET-DURABILITY-PAYLOAD")
            real_fsync(file_descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            with (
                patch.object(
                    approval_package.os, "link", side_effect=recording_link
                ),
                patch.object(
                    approval_package.os, "fsync", side_effect=fail_after_promotion
                ),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError,
                    "committed but durability could not be confirmed",
                ) as captured:
                    write_context(context, root)
            self.assertNotIn("SECRET-DURABILITY-PAYLOAD", str(captured.exception))
            package_path = root / "2026-07-16" / "agent-reliability"
            self.assertEqual(
                {path.name for path in package_path.iterdir()},
                set(approval_package.PACKAGE_FILES.values()),
            )
            self.assertEqual(
                json.loads((package_path / "manifest.json").read_text())["package_id"],
                "2026-07-16-agent-reliability",
            )

    def test_manifest_stage_cleanup_failure_cannot_retract_committed_package(self) -> None:
        context = fixture_context()
        real_unlink = os.unlink
        failed = False

        def fail_manifest_stage_unlink(
            path: object, *, dir_fd: int | None = None
        ) -> None:
            nonlocal failed
            if path == "manifest.json" and not failed:
                failed = True
                raise OSError("SECRET-STAGE-CLEANUP-PAYLOAD")
            real_unlink(path, dir_fd=dir_fd)

        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            with patch.object(
                approval_package.os,
                "unlink",
                side_effect=fail_manifest_stage_unlink,
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError,
                    "committed but private staging cleanup was incomplete",
                ) as captured:
                    write_context(context, root)
            self.assertNotIn(
                "SECRET-STAGE-CLEANUP-PAYLOAD", str(captured.exception)
            )
            date = root / "2026-07-16"
            package_path = date / "agent-reliability"
            self.assertEqual(
                {path.name for path in package_path.iterdir()},
                set(approval_package.PACKAGE_FILES.values()),
            )
            self.assertEqual(
                {path.name for path in date.iterdir()}, {"agent-reliability"}
            )

    def test_concurrent_name_race_is_reserved_without_overwrite(self) -> None:
        context = fixture_context()
        real_mkdir = os.mkdir
        raced = False

        def racing_mkdir(
            path: object,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> None:
            nonlocal raced
            if path == "agent-reliability" and not raced:
                real_mkdir(path, mode, dir_fd=dir_fd)
                raced = True
                raise FileExistsError("simulated concurrent reservation")
            real_mkdir(path, mode, dir_fd=dir_fd)

        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            with patch.object(
                approval_package.os, "mkdir", side_effect=racing_mkdir
            ):
                result = write_context(context, root)
            raced_path = root / "2026-07-16" / "agent-reliability"
            raced_inode = raced_path.stat().st_ino
            self.assertEqual(list(raced_path.iterdir()), [])
            self.assertEqual(result["path"].name, "agent-reliability-2")
            self.assertEqual(raced_path.stat().st_ino, raced_inode)
            self.assertEqual(
                result["manifest"]["package_id"],
                "2026-07-16-agent-reliability-2",
            )

    def test_short_writes_are_completed_exactly(self) -> None:
        context = fixture_context()
        real_write = os.write

        def short_write(file_descriptor: int, payload: object) -> int:
            return real_write(file_descriptor, bytes(payload)[:7])

        with tempfile.TemporaryDirectory() as temporary:
            root = self.output_root(temporary)
            with patch.object(
                approval_package.os, "write", side_effect=short_write
            ):
                result = write_context(context, root)
            manifest = json.loads((result["path"] / "manifest.json").read_text())
            self.assertEqual(manifest, result["manifest"])

    def test_private_permissions_are_forced_under_a_permissive_umask(self) -> None:
        context = fixture_context()
        old_umask = os.umask(0)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = self.output_root(temporary)
                result = write_context(context, root)
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
                self.assertEqual(
                    stat.S_IMODE(result["path"].parent.stat().st_mode), 0o700
                )
                self.assertEqual(stat.S_IMODE(result["path"].stat().st_mode), 0o700)
                for path in result["path"].iterdir():
                    self.assertTrue(path.is_file())
                    self.assertFalse(path.is_symlink())
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        finally:
            os.umask(old_umask)


if __name__ == "__main__":
    unittest.main()
