from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest

from authority_os import v1_gates, workflow


def _run_installed_smoke(script: str) -> dict[str, object]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(workflow.REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", _FIXTURES + "\n" + textwrap.dedent(script)],
        cwd=workflow.REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout.splitlines()[-1])


_FIXTURES = """
SITUATIONS = (
    "Retry budgets now stop agent loops before queue saturation.",
    "Payment agents now require approval before funds move.",
    "Research agents now attach citations before claims ship.",
)
CHANGES = (
    "The runtime added a bounded retry checkpoint.",
    "The payment workflow added a human authorization boundary.",
    "The research workflow added source binding before delivery.",
)
ATOMIC_VALUES = (
    "Cap retries before an agent loop can saturate its queue.",
    "Require human approval before a payment agent moves funds.",
    "Bind every research claim to a source before delivery.",
)

def candidates():
    return [
        {
            "id": f"topic-{index}",
            "source_ids": [f"signal-{index}"],
            "situation": SITUATIONS[index - 1],
            "what_changed": CHANGES[index - 1],
            "who_cares": "Senior AI product leaders.",
            "reader_value_type": "DECISION_CHANGE",
            "reader_value": "A reusable release decision changes.",
            "gravity": "HIGH",
            "authority_add": "Translate evidence into a production operating rule.",
            "atomic_value": ATOMIC_VALUES[index - 1],
            "brand_strip_pass": True,
            "feed_value_possible": True,
            "supports_authority_goal": True,
            "scores": {
                "reader_relevance": 5,
                "reader_value": 5,
                "gravity": 5,
                "evidence_strength": 5,
                "authority_fit": 5,
            },
            "status": "PASS",
            "diagnosis": "Strong material.",
        }
        for index in range(1, 4)
    ]

def signals():
    return [
        {
            "id": f"signal-{index}",
            "canonical_url": f"https://example.com/{index}",
            "source_quality": "primary",
            "body": SITUATIONS[index - 1] + " " + CHANGES[index - 1],
        }
        for index in range(1, 4)
    ]

class Observer:
    def __init__(self):
        self.records = []
        self.failures = []

    def __call__(self, stage, rows):
        self.records.append((stage, rows))

    def record_observability_failure(self, stage, exc):
        self.failures.append((stage, str(exc)))
"""


class InstalledObserverSmokeTests(unittest.TestCase):
    def test_installed_public_resume_skips_discovery_and_reaches_evidence(self) -> None:
        result = _run_installed_smoke(
            """
            import hashlib
            import io
            import json
            import tempfile
            from contextlib import redirect_stderr, redirect_stdout
            from pathlib import Path
            from unittest.mock import patch
            from authority_os import workflow

            workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
                root = Path(temporary)
                source = root / "source"
                output = root / "resume"
                source.mkdir()

                from authority_os import v1_gates
                v1_gates.STATE_ROOT = root / "v1-evals"
                v1_gates.install()
                from authority_os import v1_completion
                v1_completion.STATE_ROOT = v1_gates.STATE_ROOT
                v1_completion.install()
                from authority_os import topic_value_id_contract
                topic_value_id_contract.install()
                from authority_os import daily_discovery_cli
                daily = daily_discovery_cli.base

                profile_data = {
                    "target_audience": "Senior AI product leaders",
                    "authority_goal": "Practical production judgment",
                    "proof_inventory": [{
                        "id": "proof-repo",
                        "label": "Public repository",
                        "public_safe_claim": "A repository demonstrates the workflow.",
                        "evidence_type": "repository",
                    }],
                    "avoid_topics": [],
                    "recent_theses": [],
                }
                candidate = {
                    "id": "topic-1",
                    "topic": "Agent reliability boundaries",
                    "why_now": "A current release makes the boundary consequential.",
                    "total": 20,
                    "observed_axes": 5,
                    "momentum_eligible": True,
                    "representative_urls": ["https://example.com/momentum"],
                    "authority_fit": {"total": 22},
                }
                dashboard = daily.new_run_dashboard("source-run")
                for check in dashboard["checks"]:
                    if check["stage"] in {"conversation_discovery", "topic_admission"}:
                        check["status"] = "PASS"
                    elif check["stage"] == "evidence_verification":
                        check["status"] = "FAIL"
                admission = next(
                    check for check in dashboard["checks"]
                    if check["stage"] == "topic_admission"
                )
                admission["details"] = {
                    "route": "momentum-qualified",
                    "admitted_topics": [candidate["topic"]],
                }
                daily.base.write_private_json(source / "run-dashboard.json", dashboard)
                daily.base.write_private_json(source / "momentum.json", {
                    "schema_version": 1,
                    "created_at": "2026-09-04T12:00:00Z",
                    "topic": None,
                    "days": 7,
                    "candidates": [candidate],
                })
                daily.base.write_private_json(source / daily.ADMITTED_SCOPE_NAME, {
                    "schema_version": 1,
                    "created_at": "2026-09-04T12:00:00Z",
                    "topic": None,
                    "days": 7,
                    "route": "momentum-qualified",
                    "candidates": [candidate],
                    "profile_sha256": daily._mapping_sha256(profile_data),
                    "scope_fingerprint": daily.evidence_scope_fingerprint([candidate]),
                })
                previous = root / "previous"
                previous.mkdir()
                cached_items = workflow.prepare_research_items([
                    {
                        "url": f"https://example.com/research-{index}",
                        "title": f"Agent reliability evidence {index}",
                        "body": f"A body-read primary source records decision {index}.",
                        "source": "Research lab",
                        "published_at": "2026-09-01T00:00:00Z",
                        "source_quality": "primary",
                    }
                    for index in range(1, 4)
                ], fetched_at="2026-09-03T10:00:00Z")
                daily.base.write_private_json(previous / daily.EVIDENCE_CACHE_NAME, {
                    "schema_version": 1,
                    "created_at": "2026-09-03T10:00:00Z",
                    "scope_fingerprint": daily.evidence_scope_fingerprint([candidate]),
                    "origin": "body-verified-private-web",
                    "items": cached_items,
                })
                profile = root / "profile.json"
                profile.write_text(json.dumps(profile_data), encoding="utf-8")
                before = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in source.iterdir()
                }

                with (
                    patch.object(daily.momentum, "invoke_scout", side_effect=AssertionError("discovery repeated")) as scout,
                    patch.object(daily, "_invoke_signal_scout", side_effect=AssertionError("live evidence repeated")) as live_evidence,
                    patch.object(daily.topic_value, "invoke_discovery_selector", side_effect=workflow.WorkflowError("topic value checkpoint")) as selector,
                    patch.object(daily.eval_dashboard_html, "open_dashboard", return_value=False),
                ):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        returncode = daily_discovery_cli.main([
                            "--profile", str(profile),
                            "--days", "7",
                            "--resume-from", str(source),
                            "--output-dir", str(output),
                            "--db", str(root / "authority.sqlite"),
                            "--allow-web-research",
                            "--allow-model-egress",
                        ])
                resumed = json.loads((output / "run-dashboard.json").read_text())
                checks = {item["stage"]: item for item in resumed["checks"]}
                after = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in source.iterdir()
                }
                print(json.dumps({
                    "returncode": returncode,
                    "discovery_calls": scout.call_count,
                    "live_evidence_calls": live_evidence.call_count,
                    "selector_calls": selector.call_count,
                    "source_unchanged": before == after,
                    "conversation_status": checks["conversation_discovery"]["status"],
                    "admission_status": checks["topic_admission"]["status"],
                    "evidence_status": checks["evidence_verification"]["status"],
                    "evidence_route": checks["evidence_verification"]["details"]["acquisition_route"],
                    "topic_value_status": checks["topic_value"]["status"],
                }))
            """
        )
        self.assertEqual(
            result,
            {
                "returncode": 2,
                "discovery_calls": 0,
                "live_evidence_calls": 0,
                "selector_calls": 1,
                "source_unchanged": True,
                "conversation_status": "PASS",
                "admission_status": "PASS",
                "evidence_status": "PASS",
                "evidence_route": "verified-cache",
                "topic_value_status": "FAIL",
            },
        )

    def test_public_discovery_reuses_verified_evidence_before_topic_value(self) -> None:
        result = _run_installed_smoke(
            """
            import io
            import json
            import tempfile
            from contextlib import redirect_stderr, redirect_stdout
            from pathlib import Path
            from unittest.mock import patch
            from authority_os import workflow

            workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
                root = Path(temporary)
                cache_root = root / "cache"
                previous = cache_root / "2026-09-03" / "100000"
                current = root / "current"
                previous.mkdir(parents=True)
                current.mkdir(parents=True)

                from authority_os import v1_gates
                v1_gates.STATE_ROOT = root / "v1-evals"
                v1_gates.install()
                from authority_os import v1_completion
                v1_completion.STATE_ROOT = v1_gates.STATE_ROOT
                v1_completion.install()
                from authority_os import topic_value_id_contract
                topic_value_id_contract.install()
                from authority_os import daily_discovery_cli
                daily = daily_discovery_cli.base

                candidate = {
                    "id": "topic-1",
                    "topic": "Agent reliability boundaries",
                    "why_now": "A current release makes the boundary consequential.",
                    "total": 20,
                    "observed_axes": 5,
                    "momentum_eligible": True,
                    "representative_urls": ["https://example.com/momentum"],
                    "authority_fit": {"total": 22},
                }
                items = workflow.prepare_research_items([
                    {
                        "url": f"https://example.com/research-{index}",
                        "title": f"Agent reliability evidence {index}",
                        "body": f"A body-read source records release decision {index}.",
                        "source": "Research lab",
                        "published_at": "2026-09-01T00:00:00Z",
                        "source_quality": "primary",
                    }
                    for index in range(1, 4)
                ], fetched_at="2026-09-03T10:00:00Z")
                daily.base.write_private_json(
                    previous / daily.EVIDENCE_CACHE_NAME,
                    {
                        "schema_version": 1,
                        "created_at": "2026-09-03T10:00:00Z",
                        "scope_fingerprint": daily.evidence_scope_fingerprint([candidate]),
                        "origin": "body-verified-private-web",
                        "items": items,
                    },
                )
                profile = root / "profile.json"
                profile.write_text(json.dumps({
                    "target_audience": "Senior AI product leaders",
                    "authority_goal": "Practical production judgment",
                    "proof_inventory": [{
                        "id": "proof-repo",
                        "label": "Public repository",
                        "public_safe_claim": "A public repository demonstrates the workflow.",
                        "evidence_type": "repository",
                    }],
                    "avoid_topics": [],
                    "recent_theses": [],
                }), encoding="utf-8")
                inventory_path = root / "candidate-inventory.json"

                with (
                    patch.object(daily.base, "OUTPUT_ROOT", cache_root),
                    patch.object(daily.momentum, "invoke_scout", return_value=[candidate]),
                    patch.object(daily.momentum, "rank_candidates", return_value=[candidate]),
                    patch.object(daily.momentum, "score_authority_fit", return_value=[]),
                    patch.object(daily.momentum, "attach_authority_fit", return_value=[candidate]),
                    patch.object(daily.momentum, "print_top"),
                    patch.object(daily, "update_candidate_inventory", return_value=(inventory_path, [candidate])),
                    patch.object(daily, "select_topic_scope", return_value=([candidate], "rolling seven-day inventory")),
                    patch.object(daily, "_invoke_signal_scout", side_effect=workflow.WorkflowError("Evidence Scout timed out.")) as scout,
                    patch.object(daily.topic_value, "invoke_discovery_selector", side_effect=workflow.WorkflowError("checkpoint after evidence recovery")) as selector,
                    patch.object(daily.eval_dashboard_html, "open_dashboard", return_value=False),
                ):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        returncode = daily_discovery_cli.main([
                            "--profile", str(profile),
                            "--days", "7",
                            "--as-of", "2026-09-04T12:00:00Z",
                            "--output-dir", str(current),
                            "--db", str(root / "authority.sqlite"),
                            "--allow-web-research",
                            "--allow-model-egress",
                        ])

                dashboard = json.loads((current / "run-dashboard.json").read_text())
                checks = {row["stage"]: row for row in dashboard["checks"]}
                print(json.dumps({
                    "returncode": returncode,
                    "scout_timeouts": [call.kwargs["timeout"] for call in scout.call_args_list],
                    "selector_calls": selector.call_count,
                    "evidence_status": checks["evidence_verification"]["status"],
                    "evidence_route": checks["evidence_verification"]["details"]["acquisition_route"],
                    "topic_value_status": checks["topic_value"]["status"],
                }))
            """
        )
        self.assertEqual(
            result,
            {
                "returncode": 2,
                "scout_timeouts": [],
                "selector_calls": 1,
                "evidence_status": "PASS",
                "evidence_route": "verified-cache",
                "topic_value_status": "FAIL",
            },
        )

    def test_installed_public_draft_uses_identity_manifest_and_reaches_critic(self) -> None:
        result = _run_installed_smoke(
            """
            import json
            import io
            import tempfile
            from contextlib import redirect_stderr, redirect_stdout
            from pathlib import Path
            from types import SimpleNamespace
            from unittest.mock import patch
            from authority_os import storage, v1_gates, workflow

            workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
                root = Path(temporary)
                state_root = root / "v1-evals"
                v1_gates.STATE_ROOT = state_root
                v1_gates.install()
                from authority_os import v1_completion
                v1_completion.STATE_ROOT = state_root
                v1_completion.begin_run("installed-evidence-handoff-smoke")
                v1_completion.install()
                from authority_os import __main__ as cli

                items = workflow.prepare_research_items([
                    {
                        "url": "https://example.com/retry-boundary",
                        "title": "Retry budgets stop runaway agent loops",
                        "body": "A bounded retry checkpoint stops queue saturation.",
                        "source": "Runtime engineering",
                        "published_at": "2026-09-01T00:00:00Z",
                        "source_quality": "primary",
                    },
                    {
                        "url": "https://example.org/payment-approval",
                        "title": "Payment agents require human approval",
                        "body": "A human authorization boundary is required before funds move.",
                        "source": "Payments engineering",
                        "published_at": "2026-09-02T00:00:00Z",
                        "source_quality": "primary",
                    },
                ])
                database = root / "authority.sqlite"
                storage.initialise(database)
                storage.insert_research_items(
                    database,
                    items,
                    evidence_origin="private-import",
                )
                topic = "Alignment and security evaluation boundaries"
                manifest = root / "evidence.json"
                manifest.write_text(json.dumps({
                    "schema_version": 1,
                    "thesis_id": "thesis-1",
                    "display_topic": topic,
                    "evidence": [
                        {
                            "signal_id": f"signal-{index}",
                            "canonical_url": item["canonical_url"],
                            "content_hash": item["content_hash"],
                        }
                        for index, item in enumerate(items, start=1)
                    ],
                }), encoding="utf-8")
                strategy = root / "strategy.json"
                strategy.write_text(json.dumps({
                    "target_reader": "Senior AI product leaders",
                    "reader_problem": "Agents reach production without explicit boundaries.",
                    "core_hypothesis": "Evidence-bound decisions reduce silent workflow risk.",
                    "product_decision": "Require the boundary before expanding autonomy.",
                    "authority_statement": "Translate agent mechanics into release decisions.",
                }), encoding="utf-8")
                candidates = workflow.load_fixture(topic=topic)["draft_candidates"]["authority"]
                scorecards = []
                for candidate in candidates:
                    excerpt = candidate["text"].split("\\n", 1)[0]
                    scorecards.append({
                        "candidate_id": candidate["id"],
                        **{axis: 4 for axis in workflow.CRITIC_AXES},
                        "anchors": {
                            axis: {
                                "anchor_id": f"{axis}:4",
                                "evidence": excerpt,
                                "why_not_higher": "The candidate does not completely meet anchor 5.",
                                "why_not_lower": "The excerpt exceeds anchor 3.",
                            }
                            for axis in workflow.CRITIC_AXES
                        },
                    })
                response = SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"structured_output": {"scorecards": scorecards}}),
                    stderr="",
                )
                with (
                    patch.object(workflow, "invoke_writer", return_value=candidates),
                    patch.object(workflow.shutil, "which", return_value="/opt/claude"),
                    patch.object(workflow.subprocess, "run", return_value=response) as critic_run,
                ):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        returncode = cli.main([
                            "draft",
                            "--topic", topic,
                            "--goal", "authority",
                            "--format", "text",
                            "--strategy-input", str(strategy),
                            "--evidence-manifest", str(manifest),
                            "--db", str(database),
                            "--allow-model-egress",
                        ])
                print(json.dumps({
                    "returncode": returncode,
                    "critic_calls": critic_run.call_count,
                    "evidence_urls": [item["canonical_url"] for item in items],
                    "stdout": stdout.getvalue(),
                    "stderr": stderr.getvalue(),
                }))
            """
        )
        self.assertEqual(result["returncode"], 0, result["stderr"])
        self.assertEqual(result["critic_calls"], 2)
        self.assertEqual(
            result["evidence_urls"],
            [
                "https://example.com/retry-boundary",
                "https://example.org/payment-approval",
            ],
        )

    def test_installed_public_path_observes_both_stages_and_reaches_drafting(self) -> None:
        result = _run_installed_smoke(
            """
            import json
            import sys
            import tempfile
            from pathlib import Path
            from types import SimpleNamespace
            from unittest.mock import patch
            from authority_os import topic_value, v1_gates, workflow

            workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
                state_root = Path(temporary) / "v1-evals"
                v1_gates.STATE_ROOT = state_root
                v1_gates.install()
                from authority_os import daily_spine_cli, v1_completion
                v1_completion.STATE_ROOT = state_root
                v1_completion.begin_run("installed-observer-smoke")
                v1_completion.install()

                observer = Observer()
                selected = topic_value.invoke_discovery_selector(
                    {
                        "target_audience": "Senior AI product leaders",
                        "authority_goal": "Practical production judgment",
                    },
                    signals(),
                    invoker=lambda *_args, **_kwargs: {"candidates": candidates()},
                    observer=observer,
                )
                assert len(selected) == 3
                assert [stage for stage, _rows in observer.records] == [
                    "pre-gate",
                    "post-gate",
                ]
                assert all(len(rows) == 3 for _stage, rows in observer.records)
                post_gate = observer.records[1][1]
                assert all(len(row["v1_evals"]) == 2 for row in post_gate)
                assert observer.failures == []

                ledger = v1_completion._read_jsonl(
                    state_root / v1_completion.DECISION_LEDGER_NAME
                )
                assert len(ledger) == 6
                assert all(row["status"] == "PASS" for row in ledger)

                drafting = daily_spine_cli.run_drafting_child(
                    [sys.executable, "-c", "print('draft reached')"],
                    cwd=workflow.REPO_ROOT,
                    folder=Path(temporary) / "drafting",
                )
                assert drafting.returncode == 0

                critic_candidate = {
                    "id": "candidate-1",
                    "angle": "mechanism",
                    "text": "Most teams need a retry boundary before an agent loop reaches production.",
                    "claim_ids": ["source-1"],
                }
                excerpt = critic_candidate["text"]
                scorecard = {
                    "candidate_id": "candidate-1",
                    **{axis: 4 for axis in workflow.CRITIC_AXES},
                    "anchors": {
                        axis: {
                            "anchor_id": f"{axis}:4",
                            "evidence": excerpt,
                            "why_not_higher": "The candidate does not completely meet anchor 5.",
                            "why_not_lower": "The excerpt exceeds anchor 3.",
                        }
                        for axis in workflow.CRITIC_AXES
                    },
                }
                response = SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"structured_output": {"scorecards": [scorecard]}}),
                    stderr="",
                )
                with (
                    patch.object(workflow.shutil, "which", return_value="/opt/claude"),
                    patch.object(workflow.subprocess, "run", return_value=response) as critic_run,
                ):
                    brief = workflow.build_strategy_brief(
                        {
                            "slug": "agent-reliability",
                            "why_now": "Recent primary evidence supports a product decision.",
                            "dominant_take": "Reliability compounds across workflow steps.",
                            "missing_angle": "Name the decision and what would falsify it.",
                            "primary_sources": ["https://example.com/retry"],
                            "source_quality_sufficient": True,
                            "body_read_sufficient": True,
                            "recency_sufficient": True,
                            "stale": False,
                        },
                        strategy_inputs={
                            "target_reader": "Senior AI product leaders",
                            "reader_problem": "Agent loops reach production without retry boundaries.",
                            "core_hypothesis": "Bounded retries prevent queue saturation.",
                            "product_decision": "Set the retry boundary before launch.",
                            "authority_statement": "Translate reliability into a release decision.",
                        },
                        strategy_input_origin="explicit-input",
                        goal="authority",
                        output_format="text",
                    )
                    scored = workflow.invoke_critic(
                        [critic_candidate],
                        brief,
                        [{
                            "id": "source-1",
                            "title": "Retry boundaries for production agents",
                            "claim": "Bounded retries prevent queue saturation.",
                            "source": "https://example.com/retry",
                            "source_quality": "primary",
                            "body_read": True,
                        }],
                        allow_model_egress=True,
                    )
                assert critic_run.call_count == 2
                assert scored[0]["voice_fidelity"] == 4
                critic_command = critic_run.call_args.args[0]
                system_prompt = critic_command[critic_command.index("--system-prompt") + 1]
                assert "linkedin-authority-critic-v2" in system_prompt
                audit = v1_completion._read_jsonl(state_root / v1_gates.CRITIC_AUDIT_NAME)
                assert audit[-1]["critic_rubric_sha256"] == v1_gates.critic_rubric_sha256()
                print(json.dumps({
                    "candidates": len(selected),
                    "stages": [stage for stage, _rows in observer.records],
                    "decision_rows": len(ledger),
                    "drafting_returncode": drafting.returncode,
                    "critic_calls": critic_run.call_count,
                    "critic_voice": scored[0]["voice_fidelity"],
                    "critic_rubric_sha256": audit[-1]["critic_rubric_sha256"],
                }))
            """
        )
        self.assertEqual(
            result,
            {
                "candidates": 3,
                "stages": ["pre-gate", "post-gate"],
                "decision_rows": 6,
                "drafting_returncode": 0,
                "critic_calls": 2,
                "critic_voice": 4,
                "critic_rubric_sha256": v1_gates.critic_rubric_sha256(),
            },
        )

    def test_installed_failure_observes_all_candidates_before_raise(self) -> None:
        result = _run_installed_smoke(
            """
            import json
            import tempfile
            from pathlib import Path
            from authority_os import topic_value, v1_gates, workflow

            workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
                state_root = Path(temporary) / "v1-evals"
                v1_gates.STATE_ROOT = state_root
                v1_gates.install()
                from authority_os import v1_completion
                v1_completion.STATE_ROOT = state_root
                v1_completion.begin_run("installed-observer-failure")
                v1_completion.install()

                def research(candidate, _evidence):
                    failed = candidate["id"] == "topic-1"
                    return {
                        "contract": "research_trust",
                        "mode": "enforce",
                        "status": "FAIL" if failed else "PASS",
                        "reason": "missing-trust" if failed else "body-read-source-present",
                    }

                v1_gates.evaluate_research_trust = research
                observer = Observer()
                try:
                    topic_value.invoke_discovery_selector(
                        {
                            "target_audience": "Senior AI product leaders",
                            "authority_goal": "Practical production judgment",
                        },
                        signals(),
                        invoker=lambda *_args, **_kwargs: {"candidates": candidates()},
                        observer=observer,
                    )
                except v1_gates.V1ContractError as exc:
                    blocked = exc.decision
                else:
                    raise AssertionError("enforced research-trust failure did not raise")

                assert [stage for stage, _rows in observer.records] == [
                    "pre-gate",
                    "post-gate",
                ]
                assert all(len(rows) == 3 for _stage, rows in observer.records)
                post_gate = observer.records[1][1]
                assert all("research_trust" in row["v1_evals"] for row in post_gate)
                failed = next(row for row in post_gate if row["id"] == "topic-1")
                assert failed["v1_evals"]["research_trust"] == blocked
                ledger = v1_completion._read_jsonl(
                    state_root / v1_completion.DECISION_LEDGER_NAME
                )
                assert len(ledger) == 6
                print(json.dumps({
                    "pre_gate_candidates": len(observer.records[0][1]),
                    "post_gate_candidates": len(post_gate),
                    "decision_rows": len(ledger),
                    "blocked_contract": blocked["contract"],
                    "blocked_reason": blocked["reason"],
                }))
            """
        )
        self.assertEqual(result["pre_gate_candidates"], 3)
        self.assertEqual(result["post_gate_candidates"], 3)
        self.assertEqual(result["decision_rows"], 6)
        self.assertEqual(result["blocked_contract"], "research_trust")
        self.assertEqual(result["blocked_reason"], "missing-trust")


if __name__ == "__main__":
    unittest.main()
