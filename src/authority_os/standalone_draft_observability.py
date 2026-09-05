"""Persist and open the eval UI for a directly invoked live draft run."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from . import daily_cli, daily_spine_cli, eval_dashboard_html, quality_cli, v1_completion, workflow


def run(command: Callable[[list[str]], int], argv: list[str]) -> int:
    """Wrap only a top-level draft; discovery-owned child drafts inherit its run."""

    if not argv or argv[0] != "draft" or os.environ.get(v1_completion.RUN_ID_ENV):
        return command(argv)

    run_id = v1_completion.begin_run()
    print(f"Run ID: {run_id}")
    ledger_path = v1_completion.STATE_ROOT / v1_completion.DECISION_LEDGER_NAME
    ledger_start = len(v1_completion._read_jsonl(ledger_path))
    result = command(argv)
    failure_reason = quality_cli.LAST_ERROR_REASON or "draft command returned no failure reason"
    rows = v1_completion._read_jsonl(ledger_path)[ledger_start:]

    folder = workflow.DEFAULT_PRIVATE_DATA / "draft-runs" / run_id
    daily_cli.legacy_cli._ensure_owner_only_directory(folder)  # type: ignore[attr-defined]
    eval_dashboard = daily_spine_cli.render_eval_dashboard(rows)
    eval_dashboard["run_id"] = run_id
    eval_path = daily_cli.write_private_json(folder / "eval-dashboard.json", eval_dashboard)

    run_dashboard = daily_spine_cli.new_run_dashboard(run_id)
    evaluated = [
        check for check in eval_dashboard["checks"]  # type: ignore[index]
        if check["status"] != "NOT_EVALUATED"
    ]
    post_evaluated = [
        check for check in evaluated if check.get("category") == "post_quality"
    ]
    daily_spine_cli.mark_run_stage(
        run_dashboard,
        "drafting",
        "PASS" if result == 0 or post_evaluated else "FAIL",
        (
            "draft candidates reached evaluation"
            if result == 0 or post_evaluated
            else f"drafting exited {result}: {failure_reason}"
        ),
        return_code=result,
    )
    outcome = daily_spine_cli.finalize_draft_evaluation(
        run_dashboard, eval_dashboard,
        return_code=result, failure_reason=failure_reason,
    )
    daily_spine_cli.persist_run_dashboard(
        folder,
        run_dashboard,
        outcome=outcome,
    )
    browser_path = eval_dashboard_html.write_dashboard(
        folder,
        run_dashboard,
        eval_dashboard,
    )
    opened = eval_dashboard_html.open_dashboard(browser_path)
    print(f"Eval dashboard stored: {eval_path.relative_to(workflow.REPO_ROOT)}.")
    print(
        f"Eval dashboard UI: {browser_path.as_uri()}"
        + (" (opened in your browser)." if opened else ".")
    )
    return result
