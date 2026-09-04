from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest

from authority_os import workflow


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
    def test_installed_public_path_observes_both_stages_and_reaches_drafting(self) -> None:
        result = _run_installed_smoke(
            """
            import json
            import sys
            import tempfile
            from pathlib import Path
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
                assert all(len(row["v1_evals"]) == 3 for row in post_gate)
                assert observer.failures == []

                ledger = v1_completion._read_jsonl(
                    state_root / v1_completion.DECISION_LEDGER_NAME
                )
                assert len(ledger) == 9
                assert all(row["status"] == "PASS" for row in ledger)

                drafting = daily_spine_cli.run_drafting_child(
                    [sys.executable, "-c", "print('draft reached')"],
                    cwd=workflow.REPO_ROOT,
                    folder=Path(temporary) / "drafting",
                )
                assert drafting.returncode == 0
                print(json.dumps({
                    "candidates": len(selected),
                    "stages": [stage for stage, _rows in observer.records],
                    "decision_rows": len(ledger),
                    "drafting_returncode": drafting.returncode,
                }))
            """
        )
        self.assertEqual(
            result,
            {
                "candidates": 3,
                "stages": ["pre-gate", "post-gate"],
                "decision_rows": 9,
                "drafting_returncode": 0,
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
                assert len(ledger) == 9
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
        self.assertEqual(result["decision_rows"], 9)
        self.assertEqual(result["blocked_contract"], "research_trust")
        self.assertEqual(result["blocked_reason"], "missing-trust")


if __name__ == "__main__":
    unittest.main()
