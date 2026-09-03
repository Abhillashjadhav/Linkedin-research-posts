"""Conversation-first daily discovery with advisory narrative-spine routing."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import daily_cli as base
from . import eval_dashboard_html, momentum, storage, topic_value, v1_completion, workflow
from .spine_feedback import CONTENT_SPINES


CARD_KEYS = frozenset((*base.CARD_KEYS, "recommended_spine", "spine_fit_reason"))
MAX_SPINE_FIT_REASON_CHARS = 320
MIN_AUTHORITY_FIT_FALLBACK = 20
MIN_COMBINED_INVENTORY_SCORE = 40
CANDIDATE_INVENTORY = base.OUTPUT_ROOT / "candidate-inventory.json"
EVAL_CONTRACTS = (
    ("research_trust", "Topic Value", "research trust"),
    ("claim_body_support", "Topic Value", "claim/body support"),
    ("atomic_value_novelty", "Topic Value", "atomic-value novelty"),
    ("critic_anchor_integrity", "Critic", "anchor integrity"),
    ("critic_reproducibility", "Critic", "score reproducibility"),
    ("solution_plausibility", "Resonance", "solution plausibility"),
    ("reader_attention", "Resonance", "reader attention"),
)
DISCOVERY_STAGES = (
    ("conversation_discovery", "Conversation discovery"),
    ("topic_admission", "Topic admission"),
    ("evidence_verification", "Evidence verification"),
    ("topic_value", "Topic Value"),
    ("thesis_search", "Thesis search"),
    ("drafting", "High-bar drafting"),
    ("final_evals", "Final evals"),
)


def new_run_dashboard(run_id: str = "") -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "outcome": "RUNNING",
        "stopped_at": None,
        "checks": [
            {
                "stage": stage,
                "label": label,
                "status": "NOT_EVALUATED",
                "reason": "stage was not reached",
                "details": {},
            }
            for stage, label in DISCOVERY_STAGES
        ],
    }


def mark_run_stage(
    dashboard: dict[str, object],
    stage: str,
    status: str,
    reason: str,
    **details: object,
) -> None:
    checks = dashboard.get("checks")
    if not isinstance(checks, list):
        raise workflow.WorkflowError("Run dashboard has an invalid check inventory.")
    for check in checks:
        if isinstance(check, dict) and check.get("stage") == stage:
            check["status"] = status
            check["reason"] = reason
            check["details"] = details
            if status == "FAIL":
                dashboard["outcome"] = "FAIL"
                dashboard["stopped_at"] = stage
            return
    raise workflow.WorkflowError(f"Run dashboard does not recognise stage {stage!r}.")


def persist_run_dashboard(
    folder: Path,
    dashboard: dict[str, object],
    *,
    outcome: str | None = None,
) -> Path:
    if outcome is not None:
        dashboard["outcome"] = outcome
    path = base.write_private_json(folder / "run-dashboard.json", dashboard)
    print("Run dashboard:")
    for check in dashboard["checks"]:  # type: ignore[index]
        print(
            f"  {check['label']}: {check['status']} ({check['reason']})"  # type: ignore[index]
        )
    print(f"Run dashboard stored: {path.relative_to(workflow.REPO_ROOT)}.")
    return path


def render_eval_dashboard(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    latest: dict[str, Mapping[str, object]] = {}
    for row in rows:
        contract = str(row.get("contract", ""))
        if contract:
            latest[contract] = row
    checks: list[dict[str, str]] = []
    print("Eval dashboard:")
    for contract, stage, label in EVAL_CONTRACTS:
        row = latest.get(contract)
        status = str(row.get("status", "NOT_EVALUATED")) if row else "NOT_EVALUATED"
        reason = str(row.get("reason", "stage was not reached")) if row else "stage was not reached"
        checks.append(
            {
                "stage": stage,
                "contract": contract,
                "label": label,
                "status": status,
                "reason": reason,
            }
        )
        print(f"  {stage} | {label}: {status} ({reason})")
    return {"schema_version": 1, "checks": checks}


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def update_candidate_inventory(
    candidates: Sequence[Mapping[str, object]],
    *,
    as_of: str,
    days: int,
    path: Path = CANDIDATE_INVENTORY,
) -> tuple[Path, list[dict[str, object]]]:
    """Retain qualified unused topic candidates in a rolling private inventory."""

    target = base._under_private(path)
    now = _parse_timestamp(as_of)
    cutoff = now - timedelta(days=days)
    existing: list[dict[str, object]] = []
    if target.exists():
        raw = base._private_json(target, "Candidate inventory")
        if not isinstance(raw, Mapping) or not isinstance(raw.get("candidates"), list):
            raise workflow.WorkflowError("Candidate inventory has an invalid schema.")
        for item in raw["candidates"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("last_seen_at"), str):
                raise workflow.WorkflowError("Candidate inventory entry is malformed.")
            if _parse_timestamp(str(item["last_seen_at"])) >= cutoff:
                existing.append(dict(item))

    by_topic = {
        " ".join(str(item["topic"]).casefold().split()): item
        for item in existing
        if isinstance(item.get("topic"), str)
    }
    for candidate in candidates:
        momentum_total = candidate.get("total")
        authority = candidate.get("authority_fit")
        authority_total = (
            authority.get("total") if isinstance(authority, Mapping) else None
        )
        if type(momentum_total) is not int or type(authority_total) is not int:
            continue
        combined = int(momentum_total) + int(authority_total)
        if combined < MIN_COMBINED_INVENTORY_SCORE:
            continue
        topic = str(candidate["topic"]).strip()
        key = " ".join(topic.casefold().split())
        prior = by_topic.get(key)
        first_seen = (
            str(prior["first_seen_at"])
            if prior is not None and isinstance(prior.get("first_seen_at"), str)
            else as_of
        )
        by_topic[key] = {
            "topic": topic,
            "why_now": str(candidate["why_now"]),
            "first_seen_at": first_seen,
            "last_seen_at": as_of,
            "expires_at": (now + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
            "momentum_total": int(momentum_total),
            "authority_fit_total": int(authority_total),
            "combined_total": combined,
            "representative_urls": list(candidate.get("representative_urls", [])),
            "status": "AVAILABLE",
        }
    retained = sorted(
        by_topic.values(),
        key=lambda item: (-int(item["combined_total"]), str(item["topic"]).casefold()),
    )
    payload = {
        "schema_version": 1,
        "window_days": days,
        "qualification": (
            f"momentum_total + authority_fit_total >= {MIN_COMBINED_INVENTORY_SCORE}/50"
        ),
        "updated_at": as_of,
        "candidates": retained,
    }
    base.legacy_cli._ensure_owner_only_directory(target.parent)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written < 1:
                raise workflow.WorkflowError("Candidate inventory was not written completely.")
            offset += written
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    return target, retained


def select_topic_scope(
    top_five: Sequence[Mapping[str, object]],
    inventory: Sequence[Mapping[str, object]] = (),
) -> tuple[list[dict[str, object]], str]:
    momentum_eligible = [
        dict(item) for item in top_five if item.get("momentum_eligible") is True
    ]
    if momentum_eligible:
        return momentum_eligible, "momentum-qualified"
    retained = [
        dict(item)
        for item in inventory
        if item.get("status") == "AVAILABLE"
        and type(item.get("combined_total")) is int
        and int(item["combined_total"]) >= MIN_COMBINED_INVENTORY_SCORE
    ]
    if retained:
        return retained, "rolling seven-day inventory"
    authority_eligible = [
        dict(item)
        for item in top_five
        if isinstance(item.get("authority_fit"), Mapping)
        and int(item["authority_fit"].get("total", 0)) >= MIN_AUTHORITY_FIT_FALLBACK
        and int(item.get("observed_axes", 0)) >= momentum.MIN_OBSERVED_AXES
    ]
    return authority_eligible, "authority-fit fallback"


def _schema(kind: str) -> dict[str, object]:
    if kind != "cards":
        return base._schema(kind)
    props = {key: {"type": "string"} for key in CARD_KEYS - {"signal_ids"}}
    props["recommended_spine"] = {
        "type": "string",
        "enum": list(CONTENT_SPINES),
    }
    props["signal_ids"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "items": {"type": "string"},
    }
    card = {
        "type": "object",
        "properties": props,
        "required": sorted(CARD_KEYS),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": card,
            }
        },
        "required": ["cards"],
        "additionalProperties": False,
    }


def persist_browser_dashboard(
    folder: Path,
    run_dashboard: dict[str, object],
    decision_rows: Sequence[Mapping[str, object]],
) -> tuple[Path, Path]:
    """Persist the machine-readable evals and open their zero-install UI."""

    dashboard = render_eval_dashboard(decision_rows)
    dashboard["run_id"] = run_dashboard.get("run_id", "")
    dashboard_path = base.write_private_json(
        folder / "eval-dashboard.json",
        dashboard,
    )
    browser_dashboard = eval_dashboard_html.write_dashboard(
        folder,
        run_dashboard,
        dashboard,
    )
    opened = eval_dashboard_html.open_dashboard(browser_dashboard)
    print(
        f"Eval dashboard stored: "
        f"{dashboard_path.relative_to(workflow.REPO_ROOT)}."
    )
    print(
        f"Eval dashboard UI: {browser_dashboard.as_uri()}"
        + (" (opened in your browser)." if opened else ".")
    )
    return dashboard_path, browser_dashboard


def validate_cards(
    raw: object,
    signals: Sequence[Mapping[str, object]],
    profile: Mapping[str, object],
) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 3:
        raise workflow.WorkflowError("Thesis generator must return exactly three cards.")
    base_cards: list[dict[str, object]] = []
    routing: dict[str, tuple[str, str]] = {}
    for raw_card in raw:
        if not isinstance(raw_card, Mapping) or set(raw_card) != CARD_KEYS:
            raise workflow.WorkflowError("Thesis card has an invalid schema.")
        thesis_id = raw_card.get("id")
        spine = raw_card.get("recommended_spine")
        reason = raw_card.get("spine_fit_reason")
        if not isinstance(thesis_id, str):
            raise workflow.WorkflowError("Thesis card has an invalid ID.")
        if spine not in CONTENT_SPINES:
            raise workflow.WorkflowError("Thesis recommended_spine is unsupported.")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or reason != reason.strip()
            or len(reason) > MAX_SPINE_FIT_REASON_CHARS
        ):
            raise workflow.WorkflowError("Thesis spine_fit_reason is invalid.")
        if thesis_id in routing:
            raise workflow.WorkflowError("Thesis IDs must be distinct.")
        routing[thesis_id] = (str(spine), reason)
        base_cards.append({key: raw_card[key] for key in base.CARD_KEYS})
    validated = base.validate_cards(base_cards, signals, profile)
    return [
        {
            **card,
            "recommended_spine": routing[str(card["id"])][0],
            "spine_fit_reason": routing[str(card["id"])][1],
        }
        for card in validated
    ]


def generate_cards(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    feedback: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    retry = (
        "\nUNTRUSTED_PREVIOUS_SCORES\n"
        f"{json.dumps(feedback, indent=2, sort_keys=True)}\n"
        "END_UNTRUSTED_PREVIOUS_SCORES\nCreate genuinely different theses."
        if feedback
        else ""
    )
    prompt = f"""Create exactly three one-idea authority thesis cards from the Topic-Value-selected signals. Each supplied signal may contain topic_value annotations naming the selected situation, reader-value route, gravity, reader payoff, and the authority contribution available to this author. Preserve that selected reader value; do not replace it with a generic AI-news thesis. Turn the situation into original product judgment, name a concrete reader problem, state what a team should do differently, connect honestly to one supplied proof ID, and include a non-technical summary of no more than 25 words. For each card, include conversation_surface: one concise statement naming the exact assumption, trade-off, counterexample, implementation experience, or unresolved evidence a credible practitioner could challenge or extend. Also include recommended_spine using exactly one of {', '.join(CONTENT_SPINES)}, plus spine_fit_reason explaining why the evidence and conversation surface fit that spine. The spine is advisory only; do not force a template or choose by weekday. The topic field must be a concise phrase using words from the selected signal title so stored evidence can be retrieved later. Do not draft a post or browse. Avoid recent_theses and avoid_topics. Use thesis-1 through thesis-3 exactly once.
UNTRUSTED_PROFILE
{json.dumps(dict(profile), indent=2, sort_keys=True)}
END_UNTRUSTED_PROFILE
UNTRUSTED_TOPIC_VALUE_SIGNALS
{json.dumps(list(signals), indent=2, sort_keys=True)}
END_UNTRUSTED_TOPIC_VALUE_SIGNALS{retry}"""
    result = base.invoke_structured(
        config=base.THESIS_MODEL,
        role_prompt=base._role("thesis"),
        task_prompt=prompt,
        schema=_schema("cards"),
        timeout=420,
        web_search=False,
        stage_label="Thesis generator",
    )
    return validate_cards(result.get("cards"), signals, profile)


def search_theses(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    *,
    trace_path: Path | None = None,
) -> list[dict[str, object]]:
    feedback: Mapping[str, object] | None = None
    rejected: set[str] = set()
    cycle_traces: list[dict[str, object]] = []
    best_so_far: dict[str, object] | None = None
    for cycle in range(1, base.MAX_CYCLES + 1):
        cards = generate_cards(profile, signals, feedback)
        if any(base._normal(card["thesis"]) in rejected for card in cards):
            raise workflow.WorkflowError("Thesis generator reused a rejected thesis.")
        scores = {
            str(score["thesis_id"]): score
            for score in base.score_cards(cards, profile, signals)
        }
        combined = [
            {
                **card,
                "scores": {
                    axis: int(scores[str(card["id"])][axis])
                    for axis in base.AXES
                },
                "total": int(scores[str(card["id"])]["total"]),
            }
            for card in cards
        ]
        combined.sort(
            key=lambda card: (
                -int(card["total"]),
                -int(card["scores"]["distinctiveness"]),  # type: ignore[index]
                str(card["id"]),
            )
        )
        qualifying = [
            card
            for card in combined
            if int(card["total"]) >= base.MIN_TOTAL
            and int(card["scores"]["simplicity"]) >= base.MIN_SIMPLICITY  # type: ignore[index]
        ]
        evaluated: list[dict[str, object]] = []
        for card in combined:
            reasons: list[str] = []
            if int(card["total"]) < base.MIN_TOTAL:
                reasons.append(
                    f"total {card['total']}/25 is below {base.MIN_TOTAL}/25"
                )
            simplicity = int(card["scores"]["simplicity"])  # type: ignore[index]
            if simplicity < base.MIN_SIMPLICITY:
                reasons.append(
                    f"simplicity {simplicity}/5 is below {base.MIN_SIMPLICITY}/5"
                )
            evaluated.append(
                {
                    **card,
                    "qualifies": not reasons,
                    "rejection_reasons": reasons,
                }
            )
        cycle_traces.append({"cycle": cycle, "candidates": evaluated})
        if best_so_far is None or (
            int(evaluated[0]["total"]),
            int(evaluated[0]["scores"]["distinctiveness"]),  # type: ignore[index]
            int(evaluated[0]["scores"]["simplicity"]),  # type: ignore[index]
        ) > (
            int(best_so_far["total"]),
            int(best_so_far["scores"]["distinctiveness"]),  # type: ignore[index]
            int(best_so_far["scores"]["simplicity"]),  # type: ignore[index]
        ):
            best_so_far = dict(evaluated[0])
        print(f"Thesis evaluation cycle {cycle}:")
        for card in evaluated:
            result = "PASS" if card["qualifies"] else "FAIL"
            reason = (
                "cleared every thesis threshold"
                if card["qualifies"]
                else "; ".join(card["rejection_reasons"])  # type: ignore[arg-type]
            )
            print(
                f"  {card['id']}: {card['total']}/25; "
                f"simplicity={card['scores']['simplicity']}/5; {result} ({reason})"  # type: ignore[index]
            )
            print(
                "    axes="
                + ", ".join(
                    f"{axis}:{card['scores'][axis]}"  # type: ignore[index]
                    for axis in base.AXES
                )
            )
        if qualifying:
            if trace_path is not None:
                base.write_private_json(
                    trace_path,
                    {
                        "schema_version": 1,
                        "outcome": "PASS",
                        "thresholds": {
                            "minimum_total": base.MIN_TOTAL,
                            "minimum_simplicity": base.MIN_SIMPLICITY,
                        },
                        "cycles": cycle_traces,
                        "best_overall": best_so_far,
                        "qualifying_ids": [str(card["id"]) for card in qualifying],
                    },
                )
            print(
                f"Thesis search: retained {len(qualifying)} qualifying candidate(s) "
                f"from cycle {cycle}; weaker parallel candidates were not allowed "
                "to discard the leader."
            )
            return qualifying
        rejected.update(base._normal(card["thesis"]) for card in cards)
        feedback = {
            "cycle": cycle,
            "required_total": base.MIN_TOTAL,
            "required_simplicity": base.MIN_SIMPLICITY,
            "rejected": [
                {
                    "id": card["id"],
                    "thesis": card["thesis"],
                    "conversation_surface": card["conversation_surface"],
                    "scores": card["scores"],
                    "total": card["total"],
                }
                for card in combined
            ],
        }
    if trace_path is not None:
        base.write_private_json(
            trace_path,
            {
                "schema_version": 1,
                "outcome": "FAIL",
                "thresholds": {
                    "minimum_total": base.MIN_TOTAL,
                    "minimum_simplicity": base.MIN_SIMPLICITY,
                },
                "cycles": cycle_traces,
                "best_overall": best_so_far,
                "qualifying_ids": [],
            },
        )
        print(
            f"Thesis evaluation stored: "
            f"{trace_path.relative_to(workflow.REPO_ROOT)}."
        )
    if best_so_far is not None:
        print(
            f"Best thesis across all cycles: {best_so_far['id']} at "
            f"{best_so_far['total']}/25; "
            f"simplicity={best_so_far['scores']['simplicity']}/5; "  # type: ignore[index]
            f"reasons={'; '.join(best_so_far['rejection_reasons'])}."  # type: ignore[arg-type]
        )
    raise workflow.WorkflowError(
        "No thesis cleared the authority bar after the bounded search. "
        "Improve the audience, proof inventory or signals."
    )


def _invoke_signal_scout(
    topic: str | None,
    days: int,
    as_of: str,
    candidate_topics: Sequence[str],
) -> list[dict[str, object]]:
    ranked_scope = "\n- ".join(candidate_topics)
    prompt = f"""Find five defensible GenAI product signals published during the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, evaluations, reliability, enterprise AI and AI product management'}.
Only investigate these momentum-qualified topic candidates unless another source is needed to verify the same underlying claim:
- {ranked_scope}
Search broadly and read each source body. Prefer official engineering/research blogs, documentation, papers, repositories, government and standards sources. Collect enough body evidence for a later selector to answer: what concretely changed, who in the target audience would care, what capability/decision/utility the reader receives, how consequential it is, and what inspectable evidence supports it. Return concise evidence summaries, not copied prose, topic rankings, theses, or post drafts. Public social pages may nominate a claim, but factual evidence must come from the normal primary/reputable source rules. Never access authenticated LinkedIn/X pages, email, private data, local files, credentials or authenticated services."""
    result = base.invoke_structured(
        config=base.SCOUT_MODEL,
        role_prompt=base._role("scout"),
        task_prompt=prompt,
        schema=base._schema("research"),
        timeout=420,
        web_search=True,
        stage_label="Scout",
    )
    items = result.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise workflow.WorkflowError("Scout must return an items list.")
    prepared = workflow.prepare_research_items(items)
    if not 3 <= len(prepared) <= 7:
        raise workflow.WorkflowError("Discovery needs three to seven defensible signals.")
    return prepared


def command(args: argparse.Namespace) -> int:
    if not args.allow_web_research:
        raise workflow.WorkflowError("Discovery requires --allow-web-research.")
    if not args.allow_model_egress:
        raise workflow.WorkflowError(
            "Discovery requires --allow-model-egress before the private profile reaches thesis models."
        )
    run_id = v1_completion.begin_run()
    print(f"Run ID: {run_id}")
    ledger_path = (
        v1_completion.STATE_ROOT / v1_completion.DECISION_LEDGER_NAME
    )
    ledger_start = len(v1_completion._read_jsonl(ledger_path))
    profile = base.validate_profile(base._private_json(args.profile, "Authority profile"))
    as_of = args.as_of or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    workflow.parse_published_at(as_of)

    folder = base._under_private(
        args.output_dir
        or base.OUTPUT_ROOT / as_of[:10] / as_of[11:19].replace(":", "")
    )
    base.legacy_cli._ensure_owner_only_directory(folder)
    run_dashboard = new_run_dashboard(run_id)

    try:
        momentum_candidates = momentum.invoke_scout(args.topic, args.days, as_of)
        ranked = momentum.rank_candidates(
            momentum_candidates,
            minimum=momentum.MIN_AUTHORITY_MOMENTUM,
        )
        top_five = ranked[: momentum.MOMENTUM_TOP_K]
        authority_scores = momentum.score_authority_fit(top_five, profile)
        top_five = momentum.attach_authority_fit(top_five, authority_scores)
    except workflow.WorkflowError as exc:
        mark_run_stage(
            run_dashboard,
            "conversation_discovery",
            "FAIL",
            str(exc),
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    mark_run_stage(
        run_dashboard,
        "conversation_discovery",
        "PASS",
        "conversation candidates were collected and ranked",
        signal_count=len(momentum_candidates),
        ranked_count=len(ranked),
    )
    inventory_path, inventory = update_candidate_inventory(
        top_five,
        as_of=as_of,
        days=args.days,
    )

    momentum_package = base.write_private_json(
        folder / "momentum.json",
        {
            "schema_version": 1,
            "created_at": as_of,
            "label": momentum.MOMENTUM_LABEL,
            "topic": args.topic,
            "days": args.days,
            "threshold": momentum.MIN_AUTHORITY_MOMENTUM,
            "ranking_claim_limit": (
                "Public-web proxy only; not an exact X/Twitter popularity ranking."
            ),
            "candidates": top_five,
            "publishing_status": "DISABLED",
            "human_selection_required": True,
        },
    )
    momentum.print_top(top_five)
    print(
        f"Momentum evidence stored: "
        f"{momentum_package.relative_to(workflow.REPO_ROOT)}."
    )
    print(
        f"Rolling candidate inventory: {len(inventory)} qualified unused topic(s) at "
        f"{inventory_path.relative_to(workflow.REPO_ROOT)}."
    )

    eligible, discovery_route = select_topic_scope(top_five, inventory)
    if not eligible:
        reason = (
            "No topic cleared either the authority conversation-momentum floor or the "
            "evidence-bounded authority-fit fallback."
        )
        mark_run_stage(run_dashboard, "topic_admission", "FAIL", reason)
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise workflow.WorkflowError(
            f"{reason} No thesis was generated."
        )
    mark_run_stage(
        run_dashboard,
        "topic_admission",
        "PASS",
        f"{len(eligible)} topic(s) admitted through {discovery_route}",
        route=discovery_route,
        admitted_topics=[str(item["topic"]) for item in eligible],
    )
    print(
        f"Discovery route: {discovery_route}; {len(eligible)} topic(s) admitted "
        "to evidence verification."
    )

    try:
        items = _invoke_signal_scout(
            args.topic,
            args.days,
            as_of,
            [str(item["topic"]) for item in eligible],
        )
        raw_signals = base.project_signals(items)
    except workflow.WorkflowError as exc:
        mark_run_stage(
            run_dashboard,
            "evidence_verification",
            "FAIL",
            str(exc),
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    mark_run_stage(
        run_dashboard,
        "evidence_verification",
        "PASS",
        f"{len(raw_signals)} body-verified signal(s) prepared",
        signal_ids=[str(item["id"]) for item in raw_signals],
    )

    try:
        topic_value_candidates = topic_value.invoke_discovery_selector(profile, raw_signals)
        signals = topic_value.project_discovery_signals(raw_signals, topic_value_candidates)
    except workflow.WorkflowError as exc:
        mark_run_stage(run_dashboard, "topic_value", "FAIL", str(exc))
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    mark_run_stage(
        run_dashboard,
        "topic_value",
        "PASS",
        f"{len(topic_value_candidates)} situation(s) cleared Topic Value",
        candidates=[
            {
                "id": str(item["id"]),
                "total": int(item["total"]),
                "priority": str(item["priority"]),
            }
            for item in topic_value_candidates
        ],
    )
    topic_value_package = base.write_private_json(
        folder / "topic-value.json",
        {
            "schema_version": 1,
            "created_at": as_of,
            "target_audience": profile["target_audience"],
            "authority_goal": profile["authority_goal"],
            "candidates": topic_value_candidates,
            "selected_signal_ids": [str(item["id"]) for item in signals],
            "publishing_status": "DISABLED",
            "human_selection_required": True,
        },
    )
    print(
        f"Topic Value evidence stored: "
        f"{topic_value_package.relative_to(workflow.REPO_ROOT)}."
    )
    print(
        f"{len(topic_value_candidates)} situation(s) cleared Topic Value before "
        "thesis generation:"
    )
    for candidate in topic_value_candidates:
        print(
            f"{candidate['id']}: {candidate['reader_value_type']} | "
            f"gravity={candidate['gravity']} | priority={candidate['priority']} | "
            f"score={candidate['total']}/25"
        )
        print(f"Situation: {candidate['situation']}")
        print(f"Reader value: {candidate['reader_value']}")

    thesis_trace_path = folder / "thesis-evaluations.json"
    try:
        theses = search_theses(
            profile,
            signals,
            trace_path=thesis_trace_path,
        )
    except workflow.WorkflowError as exc:
        trace_details: dict[str, object] = {}
        if thesis_trace_path.exists():
            trace_details["evaluation_artifact"] = thesis_trace_path.relative_to(
                workflow.REPO_ROOT
            ).as_posix()
        mark_run_stage(
            run_dashboard,
            "thesis_search",
            "FAIL",
            str(exc),
            **trace_details,
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    mark_run_stage(
        run_dashboard,
        "thesis_search",
        "PASS",
        f"{len(theses)} thesis candidate(s) cleared the authority bar",
        qualifying_ids=[str(item["id"]) for item in theses],
        evaluation_artifact=thesis_trace_path.relative_to(workflow.REPO_ROOT).as_posix(),
    )

    db = base._under_private(args.db)
    base.legacy_cli.initialise_paths(db)
    inserted, duplicates = storage.insert_research_items(
        db, items, evidence_origin="private-import"
    )
    package = base.write_private_json(
        folder / "theses.json",
        {
            "schema_version": 1,
            "created_at": as_of,
            "topic": args.topic,
            "days": args.days,
            "momentum_label": momentum.MOMENTUM_LABEL,
            "conversation_momentum": top_five,
            "topic_value_candidates": topic_value_candidates,
            "raw_signals": raw_signals,
            "signals": signals,
            "theses": theses,
            "publishing_status": "DISABLED",
            "human_selection_required": True,
        },
    )
    db_rel = db.relative_to(workflow.REPO_ROOT).as_posix()
    print(
        f"Live research stored: inserted={inserted}; duplicates={duplicates}; "
        f"package={package.relative_to(workflow.REPO_ROOT)}."
    )
    print(f"{len(theses)} thesis candidate(s) cleared the locked authority bar:")
    draft_commands: list[tuple[dict[str, object], list[str], str]] = []
    for card in theses:
        strategy = base.write_private_json(
            folder / f"strategy-{card['id']}.json",
            base.strategy_for(card, profile),
        )
        strategy_rel = strategy.relative_to(workflow.REPO_ROOT).as_posix()
        week_slot = getattr(args, "week_slot", None)
        slot_arg = f" --week-slot {week_slot}" if week_slot is not None else ""
        draft = (
            f"./bin/linkedin-os draft --topic {json.dumps(str(card['topic']))} "
            f"--goal authority --format text{slot_arg} "
            f"--strategy-input {json.dumps(strategy_rel)} "
            f"--db {json.dumps(db_rel)} --allow-model-egress --package"
        )
        draft_argv = [
            str(workflow.REPO_ROOT / "bin" / "linkedin-os"),
            "draft",
            "--topic",
            str(card["topic"]),
            "--goal",
            "authority",
            "--format",
            "text",
        ]
        if week_slot is not None:
            draft_argv.extend(["--week-slot", str(week_slot)])
        draft_argv.extend([
            "--strategy-input",
            strategy_rel,
            "--db",
            db_rel,
            "--allow-model-egress",
            "--package",
        ])
        draft_commands.append((card, draft_argv, draft))
        print(
            f"{card['id']}: {card['plain_language_summary']} "
            f"[{card['total']}/25; simplicity={card['scores']['simplicity']}/5]"
        )
        print(f"Decision: {card['product_decision']}")
        print(f"Conversation: {card['conversation_surface']}")
        print(
            f"Spine: {card['recommended_spine']} — {card['spine_fit_reason']}"
        )
        print(f"Draft command: {draft}")
    if getattr(args, "generate_post", False):
        selected = draft_commands[0]
        guidance = workflow.load_voice_guidance()
        anchors = [
            key for key, value in guidance.items()
            if key != "provenance" and isinstance(value, str) and value.strip()
        ]
        print(
            f"Auto-selection: {selected[0]['id']} ({selected[0]['total']}/25), "
            "the highest qualifying thesis."
        )
        print(
            f"Voice stage: LOADED ({len(anchors)} non-blank anchor(s)); "
            "Writer and Critic receive the same guidance."
        )
        print("Drafting: starting the high-bar post workflow.", flush=True)
        completed = subprocess.run(
            selected[1],
            cwd=workflow.REPO_ROOT,
            check=False,
        )
        current_rows = v1_completion._read_jsonl(ledger_path)[ledger_start:]
        dashboard = render_eval_dashboard(current_rows)
        dashboard["run_id"] = run_id
        dashboard_path = base.write_private_json(
            folder / "eval-dashboard.json",
            dashboard,
        )
        evaluated_rows = [
            check
            for check in dashboard["checks"]
            if check["status"] != "NOT_EVALUATED"
        ]
        failed_rows = [
            check
            for check in evaluated_rows
            if check["status"] in {"FAIL", "BLOCKED"}
        ]
        if completed.returncode == 0 or evaluated_rows:
            mark_run_stage(
                run_dashboard,
                "drafting",
                "PASS",
                "draft candidates were generated and reached evaluation",
                return_code=completed.returncode,
            )
        else:
            mark_run_stage(
                run_dashboard,
                "drafting",
                "FAIL",
                f"high-bar drafting workflow exited with code {completed.returncode} before an eval was recorded",
                return_code=completed.returncode,
            )
        if failed_rows:
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "FAIL",
                f"{len(failed_rows)} evaluated contract(s) failed or blocked",
                failed_contracts=[str(check["contract"]) for check in failed_rows],
            )
        elif completed.returncode != 0 and evaluated_rows:
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "FAIL",
                "workflow failed although every recorded eval passed; an unobserved gate remains",
                evaluated_contracts=[
                    str(check["contract"]) for check in evaluated_rows
                ],
            )
        elif completed.returncode == 0:
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "PASS",
                f"{len(evaluated_rows)} evaluated contract(s) cleared",
            )
        print(
            f"Eval dashboard stored: "
            f"{dashboard_path.relative_to(workflow.REPO_ROOT)}."
        )
        persist_run_dashboard(
            folder,
            run_dashboard,
            outcome="PASS" if completed.returncode == 0 else "FAIL",
        )
        browser_dashboard = eval_dashboard_html.write_dashboard(
            folder,
            run_dashboard,
            dashboard,
        )
        opened = eval_dashboard_html.open_dashboard(browser_dashboard)
        print(
            f"Eval dashboard UI: {browser_dashboard.as_uri()}"
            + (" (opened in your browser)." if opened else ".")
        )
        return completed.returncode
    persist_run_dashboard(
        folder,
        run_dashboard,
        outcome="AWAITING_HUMAN_SELECTION",
    )
    persist_browser_dashboard(
        folder,
        run_dashboard,
        v1_completion._read_jsonl(ledger_path)[ledger_start:],
    )
    print("No thesis was selected and no post was generated or published.")
    return 0


def parser() -> argparse.ArgumentParser:
    result = base.parser()
    result.add_argument(
        "--week-slot",
        type=int,
        choices=(2, 3),
        help="Bind the generated authority post to weekly slot 2 or 3; Thursday is slot 3.",
    )
    result.add_argument(
        "--generate-post",
        action="store_true",
        help=(
            "Select the highest-scoring qualifying thesis and continue through the "
            "high-bar drafting workflow."
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        return command(parser().parse_args(argv))
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
