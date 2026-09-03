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
        "PASS", "FAIL", "BLOCKED", "NOT_EVALUATED", "RUNNING"
    } else "BLOCKED"


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


def render_dashboard(
    run_dashboard: Mapping[str, object],
    eval_dashboard: Mapping[str, object],
) -> str:
    """Render a complete standalone HTML view without scripts or network calls."""

    run_checks = _checks(run_dashboard)
    eval_checks = _checks(eval_dashboard)
    all_checks = [*run_checks, *eval_checks]
    blockers = [
        item for item in all_checks if _status(item.get("status")) in {"FAIL", "BLOCKED"}
    ]
    gaps = [item for item in all_checks if _status(item.get("status")) == "NOT_EVALUATED"]
    passed = [item for item in all_checks if _status(item.get("status")) == "PASS"]
    outcome = _status(run_dashboard.get("outcome"))
    if blockers:
        outcome = "FAIL"
    elif outcome == "RUNNING" or gaps:
        outcome = "INCOMPLETE"
    elif all_checks:
        outcome = "PASS"
    first = blockers[0] if blockers else gaps[0] if gaps else None
    first_label = (
        first.get("label") or first.get("contract") or first.get("stage")
        if first else "No blocker recorded"
    )
    first_reason = first.get("reason") if first else "Every visible check passed."
    run_id = run_dashboard.get("run_id") or eval_dashboard.get("run_id")
    outcome_css = "pass" if outcome == "PASS" else "fail" if outcome == "FAIL" else "incomplete"
    run_cards = "".join(_card(item) for item in run_checks) or '<p class="empty">No workflow checks recorded.</p>'
    eval_cards = "".join(_card(item) for item in eval_checks) or '<p class="empty">No eval checks recorded.</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn OS run {_safe(run_id)}</title><style>
:root{{--bg:#07101d;--panel:#0e1a2b;--line:#253650;--text:#eef5ff;--muted:#94a6bd;--blue:#62a8ff;--green:#4ade80;--red:#fb7185;--amber:#fbbf24}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 90% 0,rgba(45,112,207,.18),transparent 35rem),var(--bg);color:var(--text);font:16px/1.5 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{width:min(1380px,calc(100% - 40px));margin:auto;padding:36px 0 60px}}.eyebrow{{color:var(--blue);font:700 12px/1.2 ui-monospace,monospace;letter-spacing:.12em}}h1{{margin:8px 0 6px;font-size:clamp(32px,5vw,62px);line-height:1.03;letter-spacing:-.045em}}.run{{color:var(--muted);font-family:ui-monospace,monospace;overflow-wrap:anywhere}}.summary{{display:grid;grid-template-columns:1fr 2fr .7fr .7fr;gap:14px;margin:28px 0 20px}}.box,.panel,.rule{{border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,#111f32,#0a1422)}}.box{{min-height:150px;padding:21px}}.label{{display:block;margin-bottom:18px;color:var(--muted);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}.box strong{{display:block;font-size:20px}}.box p{{margin:8px 0 0;color:var(--muted);font-size:14px}}.metric strong{{font-size:42px;line-height:1}}.metric.pass-count strong{{color:var(--green)}}.metric.gap-count strong{{color:var(--amber)}}.verdict{{display:inline-block!important;width:max-content;padding:7px 10px;border-radius:7px;font:800 14px/1 ui-monospace,monospace;letter-spacing:.06em}}.verdict.pass{{color:#092313;background:var(--green)}}.verdict.fail{{color:#2a070e;background:var(--red)}}.verdict.incomplete{{color:#2a1b02;background:var(--amber)}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}}.panel{{overflow:hidden}}.heading{{padding:21px;border-bottom:1px solid var(--line)}}h2{{margin:4px 0 0;font-size:21px}}.check{{display:grid;grid-template-columns:112px 1fr;gap:15px;padding:17px 21px;border-bottom:1px solid rgba(37,54,80,.75)}}.check:last-child{{border-bottom:0}}.check strong{{display:block}}.check p{{margin:4px 0;color:var(--muted);font-size:14px}}.check small{{color:#6f829b;font:700 11px/1.2 ui-monospace,monospace;text-transform:uppercase}}.status{{width:max-content;height:max-content;padding:5px 7px;border:1px solid currentColor;border-radius:6px;font:800 11px/1 ui-monospace,monospace}}.status.pass{{color:var(--green)}}.status.fail,.status.blocked{{color:var(--red)}}.status.not-evaluated{{color:var(--amber)}}.status.running{{color:var(--blue)}}.rule{{display:flex;gap:18px;margin-top:20px;padding:17px 21px}}.rule p{{margin:0;color:var(--muted);font-size:14px}}.empty{{padding:24px;color:var(--muted)}}@media(max-width:900px){{.summary,.grid{{grid-template-columns:1fr 1fr}}}}@media(max-width:650px){{main{{width:calc(100% - 24px);padding-top:22px}}.summary,.grid{{grid-template-columns:1fr}}.check{{grid-template-columns:1fr}}.rule{{flex-direction:column;gap:6px}}}}
</style></head><body><main>
<p class="eyebrow">LINKEDIN OS · LOCAL EVAL REVIEW</p><h1>See exactly where this post stopped.</h1><p class="run">Run {_safe(run_id)}</p>
<section class="summary"><article class="box"><span class="label">Run outcome</span><strong class="verdict {outcome_css}">{_safe(outcome)}</strong><p>Human approval remains separate.</p></article><article class="box"><span class="label">First blocker</span><strong>{_safe(first_label)}</strong><p>{_safe(first_reason)}</p></article><article class="box metric pass-count"><span class="label">Passed</span><strong>{len(passed)}</strong><p>recorded checks</p></article><article class="box metric gap-count"><span class="label">Not evaluated</span><strong>{len(gaps)}</strong><p>visible gaps</p></article></section>
<div class="grid"><section class="panel"><div class="heading"><p class="eyebrow">OPERATING FLOW</p><h2>Workflow stages</h2></div>{run_cards}</section><section class="panel"><div class="heading"><p class="eyebrow">QUALITY CONTRACTS</p><h2>Post evals</h2></div>{eval_cards}</section></div>
<section class="rule"><strong>Reading rule</strong><p>PASS means the check ran and cleared its bar. FAIL or BLOCKED is a stopping condition. NOT_EVALUATED is an observability gap, never a pass.</p></section>
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

