"""Zero-install browser dashboard for one private LinkedIn OS run."""

from __future__ import annotations

import html
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import workflow


def _safe(value: object, fallback: str = "Not recorded") -> str:
    text = " ".join(str(value or "").split())
    return html.escape(text or fallback)


def _checks(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = payload.get("checks")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _status(value: object) -> str:
    normalized = str(value or "NOT_EVALUATED").upper()
    return normalized if normalized in {
        "PASS", "FAIL", "BLOCKED", "NOT_EVALUATED", "RUNNING", "REJECTED", "UNAVAILABLE", "COMPLETED_WITH_WARNINGS"
    } else "BLOCKED"


def _scout_css(value: object) -> str:
    status = str(value or "UNAVAILABLE").upper()
    return status.casefold().replace("_", "-") if status in {
        "OBSERVED", "NO_SIGNAL", "UNAVAILABLE"
    } else "unavailable"


def _card(check: Mapping[str, object]) -> str:
    status = _status(check.get("status"))
    css = status.casefold().replace("_", "-")
    label = check.get("label") or check.get("contract") or check.get("stage")
    meta = check.get("contract") or check.get("stage") or "check"
    return (
        '<article class="check">'
        f'<span class="status {css}">{_safe(status)}</span>'
        '<div>'
        f'<strong>{_safe(label)}</strong>'
        f'<p>{_safe(check.get("reason"))}</p>'
        f'<small>{_safe(meta)}</small>'
        '</div></article>'
    )


def _empty_scorecard_message(
    run_checks: Sequence[Mapping[str, object]],
) -> str:
    drafting = next(
        (item for item in run_checks if item.get("stage") == "drafting"),
        None,
    )
    if drafting is not None and _status(drafting.get("status")) == "PASS":
        return "The Critic ran but returned no valid 1–5 scorecard."
    return "Drafting stopped before the Critic ran. See FIRST BLOCKER."


def render_dashboard(
    run_dashboard: Mapping[str, object],
    eval_dashboard: Mapping[str, object],
) -> str:
    """Render a complete standalone HTML view without scripts or network calls."""

    run_checks = _checks(run_dashboard)
    eval_checks = _checks(eval_dashboard)
    pipeline_checks = [item for item in eval_checks if item.get("category") != "post_quality"]
    post_checks = [item for item in eval_checks if item.get("category") == "post_quality"]
    all_checks = [*run_checks, *eval_checks]
    blockers = [
        item for item in all_checks if _status(item.get("status")) in {"FAIL", "BLOCKED"}
        and item.get("mode") not in {"diagnostic", "shadow"}
    ]
    gaps = [item for item in all_checks if _status(item.get("status")) == "NOT_EVALUATED"]
    passed = [item for item in all_checks if _status(item.get("status")) == "PASS"]
    outcome = _status(run_dashboard.get("outcome"))
    if blockers:
        outcome = "FAIL"
    elif outcome == "RUNNING" or gaps:
        outcome = "INCOMPLETE"
    elif all_checks and outcome != "COMPLETED_WITH_WARNINGS":
        outcome = "PASS"
    first = blockers[0] if blockers else gaps[0] if gaps else None
    first_label = (
        first.get("label") or first.get("contract") or first.get("stage")
        if first else "No blocker recorded"
    )
    first_reason = first.get("reason") if first else "Draft delivered; see scores and advisory findings below."
    run_id = run_dashboard.get("run_id") or eval_dashboard.get("run_id")
    outcome_css = "pass" if outcome == "PASS" else "fail" if outcome == "FAIL" else "incomplete"
    run_cards = "".join(_card(item) for item in run_checks) or '<p class="empty">No workflow checks recorded.</p>'
    pipeline_cards = "".join(_card(item) for item in pipeline_checks) or '<p class="empty">No pipeline contracts recorded.</p>'
    post_cards = "".join(_card(item) for item in post_checks) or '<p class="empty">No post-quality contracts recorded.</p>'
    raw_scorecards = eval_dashboard.get("critic_scorecards")
    scorecards = [item for item in raw_scorecards if isinstance(item, Mapping)] if isinstance(raw_scorecards, list) else []
    axis_order = (
        "hook_strength",
        "middle_escalation",
        "earned_closer",
        "specificity_and_source_quality",
        "voice_fidelity",
    )
    scorecard_rows = "".join(
        "<tr>"
        f'<td>{int(item.get("cycle", 0))}</td>'
        f'<td>{_safe(item.get("candidate_id"))}</td>'
        + "".join(
            f'<td><span class="axis-score">{int(item.get("axes", {}).get(axis, 0))}/5</span></td>'
            for axis in axis_order
            if isinstance(item.get("axes"), Mapping)
        )
        + f'<td><strong>{int(item.get("total", 0))}/25</strong><small> bar {int(item.get("threshold", 18))}</small></td>'
        + f'<td><span class="status {_status(item.get("status")).casefold()}">{_safe(item.get("status"))}</span></td>'
        + f'<td>{_safe(" | ".join(str(value) for value in item.get("failure_codes", [])), "No score shortfall")}<small>Advisories: {_safe(" | ".join(str(value) for value in item.get("advisory_codes", [])), "none")}</small></td>'
        + "</tr>"
        for item in scorecards
    ) or f'<tr><td colspan="10">{_empty_scorecard_message(run_checks)}</td></tr>'
    raw_scouts = run_dashboard.get("surface_scouts")
    scouts = [item for item in raw_scouts if isinstance(item, Mapping)] if isinstance(raw_scouts, list) else []
    observed_scouts = sum(1 for item in scouts if item.get("status") == "OBSERVED")
    signal_count = sum(int(item.get("signal_count", 0)) for item in scouts)
    scout_cards = "".join(
        '<article class="scout">'
        f'<span class="status {_scout_css(item.get("status"))}">{_safe(item.get("status"))}</span>'
        f'<strong>{_safe(item.get("label"))}</strong>'
        f'<p>{_safe(item.get("reason_code"))} · {int(item.get("signal_count", 0))} signal(s)</p>'
        f'<small>{_safe(item.get("reason"))}</small></article>'
        for item in scouts
    ) or '<p class="empty">No per-scout trace was recorded.</p>'
    raw_baseline = run_dashboard.get("baseline")
    baseline = [item for item in raw_baseline if isinstance(item, Mapping)] if isinstance(raw_baseline, list) else []
    baseline_rows = "".join(
        f'<tr><td>{_safe(item.get("run_id"))}</td><td><span class="status {_status(item.get("outcome")).casefold()}">{_safe(item.get("outcome"))}</span></td><td>{_safe(item.get("stopped_at"), "Completed")}</td><td>{int(item.get("passed_stages", 0))}</td></tr>'
        for item in baseline
    ) or '<tr><td colspan="4">No prior local runs available yet.</td></tr>'
    execution = run_dashboard.get("execution")
    execution_rows = ""
    if isinstance(execution, Mapping):
        execution_rows = "".join(
            (
                f'<tr><td>{_safe(label)}</td><td>{_safe(execution.get(key))}</td></tr>'
                for key, label in (
                    ("commit", "Git commit"),
                    ("branch", "Git branch"),
                    ("dirty", "Tracked changes present"),
                    ("observability_contract", "Observability contract"),
                )
            )
        )
    execution_rows = execution_rows or '<tr><td colspan="2">Execution identity was not recorded. This run predates end-to-end observability.</td></tr>'
    raw_run_decisions = run_dashboard.get("decisions")
    run_decisions = (
        [item for item in raw_run_decisions if isinstance(item, Mapping)]
        if isinstance(raw_run_decisions, list)
        else []
    )
    raw_eval_decisions = eval_dashboard.get("decisions")
    eval_decisions = (
        [item for item in raw_eval_decisions if isinstance(item, Mapping)]
        if isinstance(raw_eval_decisions, list)
        else []
    )
    decision_rows = "".join(
        "<tr>"
        f'<td>{_safe(item.get("stage"))}<small>{_safe(item.get("subject_id"), "run")}</small></td>'
        f'<td>{_safe(item.get("decision"))}</td>'
        f'<td><span class="status {_status(item.get("status")).casefold().replace("_", "-")}">{_safe(_status(item.get("status")))}</span></td>'
        f'<td>{_safe(item.get("expected"))}</td>'
        f'<td>{_safe(item.get("observed"))}</td>'
        f'<td>{_safe(item.get("reason"))}<small>{_safe(item.get("artifact"), "No separate artifact")}</small></td>'
        "</tr>"
        for item in [*run_decisions, *eval_decisions]
    ) or '<tr><td colspan="6">No decision trace was recorded. This run predates end-to-end observability.</td></tr>'
    versions = run_dashboard.get("evaluator_versions")
    version_rows = ""
    if isinstance(versions, Mapping):
        version_rows += f'<tr><td>LinkedIn OS</td><td>{_safe(versions.get("linkedin_os"))}</td></tr>'
        models = versions.get("models")
        if isinstance(models, Mapping):
            for name, config in models.items():
                if isinstance(config, Mapping):
                    version_rows += f'<tr><td>{_safe(name)}</td><td>{_safe(config.get("model"))} · {_safe(config.get("reasoning"))}</td></tr>'
        rubrics = versions.get("rubrics")
        if isinstance(rubrics, Mapping):
            for name, digest in rubrics.items():
                version_rows += f'<tr><td>{_safe(name)}</td><td>{_safe(digest)}</td></tr>'
    version_rows = version_rows or '<tr><td colspan="2">Evaluator versions were not recorded.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn OS run {_safe(run_id)}</title><style>
:root{{--bg:#07101d;--panel:#0e1a2b;--line:#253650;--text:#eef5ff;--muted:#94a6bd;--blue:#62a8ff;--green:#4ade80;--red:#fb7185;--amber:#fbbf24}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 90% 0,rgba(45,112,207,.18),transparent 35rem),var(--bg);color:var(--text);font:16px/1.5 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{width:min(1500px,calc(100% - 40px));margin:auto;padding:36px 0 60px}}.eyebrow{{color:var(--blue);font:700 12px/1.2 ui-monospace,monospace;letter-spacing:.12em}}h1{{margin:8px 0 6px;font-size:clamp(32px,5vw,62px);line-height:1.03;letter-spacing:-.045em}}.run{{color:var(--muted);font-family:ui-monospace,monospace;overflow-wrap:anywhere}}.summary{{display:grid;grid-template-columns:1fr 2fr .8fr .8fr .8fr;gap:14px;margin:28px 0 20px}}.box,.panel,.rule{{border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,#111f32,#0a1422)}}.box{{min-height:150px;padding:21px}}.label{{display:block;margin-bottom:18px;color:var(--muted);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}.box strong{{display:block;font-size:20px}}.box p{{margin:8px 0 0;color:var(--muted);font-size:14px}}.metric strong{{font-size:38px;line-height:1}}.metric.pass-count strong{{color:var(--green)}}.metric.gap-count strong{{color:var(--amber)}}.metric.scout-count strong{{color:var(--blue)}}.verdict{{display:inline-block!important;width:max-content;padding:7px 10px;border-radius:7px;font:800 14px/1 ui-monospace,monospace;letter-spacing:.06em}}.verdict.pass{{color:#092313;background:var(--green)}}.verdict.fail{{color:#2a070e;background:var(--red)}}.verdict.incomplete{{color:#2a1b02;background:var(--amber)}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}}.panel{{overflow:hidden;margin-top:20px}}.heading{{padding:21px;border-bottom:1px solid var(--line)}}h2{{margin:4px 0 0;font-size:21px}}.check{{display:grid;grid-template-columns:112px 1fr;gap:15px;padding:17px 21px;border-bottom:1px solid rgba(37,54,80,.75)}}.check:last-child{{border-bottom:0}}.check strong{{display:block}}.check p{{margin:4px 0;color:var(--muted);font-size:14px}}.check small,.scout small{{color:#6f829b;font:700 11px/1.4 ui-monospace,monospace}}.status{{width:max-content;height:max-content;padding:5px 7px;border:1px solid currentColor;border-radius:6px;font:800 11px/1 ui-monospace,monospace}}.status.pass,.status.observed{{color:var(--green)}}.status.fail,.status.blocked,.status.unavailable{{color:var(--red)}}.status.rejected{{color:var(--muted)}}.status.not-evaluated,.status.no-signal{{color:var(--amber)}}.status.running{{color:var(--blue)}}.scouts{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line)}}.scout{{display:flex;flex-direction:column;gap:8px;padding:18px;background:var(--panel)}}.scout p{{margin:0;color:var(--muted);font-size:13px}}.table-scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:13px 18px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:top}}th{{color:var(--muted);font-size:11px;text-transform:uppercase;white-space:nowrap}}td:first-child{{overflow-wrap:anywhere}}.axis-score{{display:inline-block;min-width:38px;color:var(--blue);font-weight:800}}td small{{display:block;color:var(--muted)}}.rule{{display:flex;gap:18px;margin-top:20px;padding:17px 21px}}.rule p{{margin:0;color:var(--muted);font-size:14px}}.empty{{padding:24px;color:var(--muted)}}@media(max-width:1000px){{.summary{{grid-template-columns:1fr 1fr}}.scouts{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:650px){{main{{width:calc(100% - 24px);padding-top:22px}}.summary,.grid,.scouts{{grid-template-columns:1fr}}.check{{grid-template-columns:1fr}}.rule{{flex-direction:column;gap:6px}}}}
</style></head><body><main>
<p class="eyebrow">LINKEDIN OS · LOCAL EVAL REVIEW</p><h1>See exactly where this post stopped.</h1><p class="run">Run {_safe(run_id)}</p>
<section class="summary"><article class="box"><span class="label">Run outcome</span><strong class="verdict {outcome_css}">{_safe(outcome)}</strong><p>Human approval remains separate.</p></article><article class="box"><span class="label">First blocker</span><strong>{_safe(first_label)}</strong><p>{_safe(first_reason)}</p></article><article class="box metric scout-count"><span class="label">Conversation sources</span><strong>{observed_scouts}/{len(scouts) or 7}</strong><p>{signal_count} surface signal(s)</p></article><article class="box metric pass-count"><span class="label">Passed</span><strong>{len(passed)}</strong><p>recorded checks</p></article><article class="box metric gap-count"><span class="label">Not evaluated</span><strong>{len(gaps)}</strong><p>visible gaps</p></article></section>
<section class="panel"><div class="heading"><p class="eyebrow">SURFACE SCOUTS</p><h2>What ran, what returned, and why</h2></div><div class="scouts">{scout_cards}</div></section>
<div class="grid"><section class="panel"><div class="heading"><p class="eyebrow">OPERATING FLOW</p><h2>Workflow stages</h2></div>{run_cards}</section><section class="panel"><div class="heading"><p class="eyebrow">PIPELINE CONTRACTS</p><h2>Input and execution evals</h2></div>{pipeline_cards}</section></div>
<section class="panel"><div class="heading"><p class="eyebrow">CRITIC SCORECARDS</p><h2>Every candidate, every cycle, every 1–5 axis</h2></div><div class="table-scroll"><table><thead><tr><th>Cycle</th><th>Candidate</th><th>Hook</th><th>Middle</th><th>Closer</th><th>Specificity + sources</th><th>Voice</th><th>Total</th><th>Critic bar</th><th>Failure codes</th></tr></thead><tbody>{scorecard_rows}</tbody></table></div></section>
<section class="panel"><div class="heading"><p class="eyebrow">POST QUALITY</p><h2>Would the post itself clear the bar?</h2></div>{post_cards}</section>
<section class="panel"><div class="heading"><p class="eyebrow">DECISION TRACE</p><h2>Expected rule, observed value, and exact reason</h2></div><div class="table-scroll"><table><thead><tr><th>Stage / subject</th><th>Decision</th><th>Status</th><th>Expected</th><th>Observed</th><th>Why / artifact</th></tr></thead><tbody>{decision_rows}</tbody></table></div></section>
<div class="grid"><section class="panel"><div class="heading"><p class="eyebrow">EXECUTION</p><h2>Exact code that ran</h2></div><table><tbody>{execution_rows}</tbody></table></section><section class="panel"><div class="heading"><p class="eyebrow">REPRODUCIBILITY</p><h2>Evaluator, model and rubric versions</h2></div><table><tbody>{version_rows}</tbody></table></section></div>
<section class="panel"><div class="heading"><p class="eyebrow">BASELINE</p><h2>Last five local runs</h2></div><table><thead><tr><th>Run</th><th>Outcome</th><th>Stopped at</th><th>Passed stages</th></tr></thead><tbody>{baseline_rows}</tbody></table></section>
<section class="rule"><strong>Reading rule</strong><p>PASS means a check cleared its bar. Editorial findings are non-blocking advisories. COMPLETED_WITH_WARNINGS means a draft was delivered with unmet writing scores. REJECTED describes an edit that did not improve the retained draft. Input, execution, authorization and secure-file errors can still stop a run. NOT_EVALUATED means the check did not run.</p></section>
</main></body></html>"""


def write_dashboard(
    folder: Path,
    run_dashboard: Mapping[str, object],
    eval_dashboard: Mapping[str, object],
) -> Path:
    root = workflow.DEFAULT_PRIVATE_DATA.expanduser().resolve()
    target = (folder / "eval-dashboard.html").expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise workflow.WorkflowError("Eval dashboard must stay under data/private.") from None
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise workflow.WorkflowError("Eval dashboard already exists for this run.") from exc
    try:
        payload = render_dashboard(run_dashboard, eval_dashboard).encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise workflow.WorkflowError("Eval dashboard write did not make progress.")
            offset += written
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return target


def open_dashboard(path: Path) -> bool:
    """Open locally on macOS without starting or installing a server."""

    if sys.platform != "darwin" or os.environ.get("CI"):
        return False
    completed = subprocess.run(
        ["open", str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0
