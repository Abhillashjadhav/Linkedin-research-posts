"""Conversation-first daily discovery with advisory narrative-spine routing."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import daily_cli as base
from . import momentum, storage, topic_value, workflow
from .spine_feedback import CONTENT_SPINES


CARD_KEYS = frozenset((*base.CARD_KEYS, "recommended_spine", "spine_fit_reason"))
MAX_SPINE_FIT_REASON_CHARS = 320
CAPABILITY_LAUNCH_TITLE_PREFIX = "[Capability Launch]"


def capability_launch_signal_ids(
    signals: Sequence[Mapping[str, object]],
) -> set[str]:
    """Return externally launched capabilities that earned a traced Scout record."""

    prefix = CAPABILITY_LAUNCH_TITLE_PREFIX.casefold()
    return {
        str(signal["id"])
        for signal in signals
        if isinstance(signal.get("id"), str)
        and isinstance(signal.get("title"), str)
        and str(signal["title"]).strip().casefold().startswith(prefix)
    }


def draft_format_for(
    card: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
) -> str:
    """Prefer video only for a thesis grounded in a qualified capability launch."""

    signal_ids = card.get("signal_ids")
    if not isinstance(signal_ids, Sequence) or isinstance(signal_ids, (str, bytes)):
        return "text"
    if set(str(value) for value in signal_ids) & capability_launch_signal_ids(signals):
        return "vertical-video"
    return "text"


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
    launch_ids = capability_launch_signal_ids(signals)
    if launch_ids and not any(
        set(str(value) for value in card["signal_ids"]) & launch_ids
        for card in validated
    ):
        raise workflow.WorkflowError(
            "Thesis generation ignored a Topic-Value-selected capability launch."
        )
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
    prompt = f"""Create exactly three one-idea authority thesis cards from the Topic-Value-selected signals. Each supplied signal may contain topic_value annotations naming the selected situation, reader-value route, gravity, reader payoff, and the authority contribution available to this author. Preserve that selected reader value; do not replace it with a generic AI-news thesis. Turn the situation into original product judgment, name a concrete reader problem, state what a team should do differently, connect honestly to one supplied proof ID, and include a non-technical summary of no more than 25 words. For each card, include conversation_surface: one concise statement naming the exact assumption, trade-off, counterexample, implementation experience, or unresolved evidence a credible practitioner could challenge or extend. Also include recommended_spine using exactly one of {', '.join(CONTENT_SPINES)}, plus spine_fit_reason explaining why the evidence and conversation surface fit that spine. The spine is advisory only; do not force a template or choose by weekday. When a signal title begins {CAPABILITY_LAUNCH_TITLE_PREFIX}, at least one card must use that launch. Credit the named builder, explain the capability and reader benefit before abstract commentary, preserve the demonstrated result and limitation, and never turn creator-reported evidence into independent verification. Video changes the downstream format, not the evidence or writing bar. The topic field must be a concise phrase using words from the selected signal title so stored evidence can be retrieved later. Do not draft a post or browse. Avoid recent_theses and avoid_topics. Use thesis-1 through thesis-3 exactly once.
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
) -> list[dict[str, object]]:
    return base.search_theses(
        profile,
        signals,
        generator=generate_cards,
        critic=base.score_cards,
    )


def _invoke_signal_scout(
    topic: str | None,
    days: int,
    as_of: str,
    candidate_topics: Sequence[str],
) -> list[dict[str, object]]:
    ranked_scope = "\n- ".join(candidate_topics)
    prompt = f"""Find five defensible GenAI product source records published during the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, evaluations, reliability, enterprise AI and AI product management'}.
Only investigate these momentum-qualified topic candidates unless another source is needed to verify the same underlying claim:
- {ranked_scope}
Search broadly and read each source body. Explicitly inspect public Substack newsletters and publicly indexed X/Twitter posts or search-result snippets when they discuss a qualified candidate. Prefer official engineering/research blogs, documentation, papers, repositories, government and standards sources. A creator-controlled Substack post may support the creator's own launch claim but is not independent verification. Do not subscribe, provide an email address, authenticate, or bypass a paywall. Collect enough body evidence for a later selector to answer: what concretely changed, who in the target audience would care, what capability/decision/utility the reader receives, how consequential it is, and what inspectable evidence supports it.

Because this channel teaches practical GenAI, prefer at least one recent capability launched by a named independent builder or small team when one of the momentum-qualified candidates has all of these: a creator-controlled primary source, public creator identity, direct public demo-video page, and runnable public repository or product. Represent that one launch with two body-read records using the same exact title `{CAPABILITY_LAUNCH_TITLE_PREFIX} <capability> by <creator>`: one canonical URL must be the runnable artifact and the other the original creator demo page. Across the two concise bodies preserve the creator, launch date, exact demonstrated result, reader benefit, novelty basis, verification status, reuse-permission status, and one material limitation. Do not return a capability-launch record if either URL or attribution is missing. Do not call a creator unknown, claim first-ever novelty without proof, or treat the creator demo as independent verification.

Return concise evidence summaries, not copied prose, topic rankings, theses, or post drafts. Public social pages may nominate a claim, but factual evidence must come from the normal primary/reputable source rules. Preserve original video links for credit and review; never download or imply permission to republish them. Never access authenticated LinkedIn/X pages, email, private data, local files, credentials or authenticated services."""
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


def validate_momentum_resume(
    raw: object,
    *,
    requested_topic: str | None,
    requested_days: int,
    requested_as_of: str | None,
) -> tuple[str, list[dict[str, object]]]:
    """Validate a previously written momentum checkpoint before resuming."""

    required = {
        "schema_version",
        "created_at",
        "label",
        "topic",
        "days",
        "threshold",
        "ranking_claim_limit",
        "candidates",
        "publishing_status",
        "human_selection_required",
    }
    if not isinstance(raw, Mapping) or not required <= set(raw):
        raise workflow.WorkflowError("Momentum resume evidence has an invalid schema.")
    if (
        raw.get("schema_version") != 1
        or raw.get("label") != momentum.MOMENTUM_LABEL
        or raw.get("threshold") != momentum.MIN_AUTHORITY_MOMENTUM
        or raw.get("publishing_status") != "DISABLED"
        or raw.get("human_selection_required") is not True
    ):
        raise workflow.WorkflowError("Momentum resume evidence has invalid control fields.")
    if raw.get("topic") != requested_topic or raw.get("days") != requested_days:
        raise workflow.WorkflowError(
            "Momentum resume topic and day window must match the discovery command."
        )
    created_at = raw.get("created_at")
    if not isinstance(created_at, str):
        raise workflow.WorkflowError("Momentum resume evidence needs a valid created_at.")
    workflow.parse_published_at(created_at)
    if requested_as_of is not None and requested_as_of != created_at:
        raise workflow.WorkflowError(
            "--as-of must match the saved momentum created_at when resuming."
        )

    raw_candidates = raw.get("candidates")
    if (
        not isinstance(raw_candidates, Sequence)
        or isinstance(raw_candidates, (str, bytes))
        or len(raw_candidates) != momentum.MOMENTUM_TOP_K
    ):
        raise workflow.WorkflowError("Momentum resume evidence must contain five candidates.")

    candidates: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_topics: set[str] = set()
    for rank, raw_candidate in enumerate(raw_candidates, 1):
        if not isinstance(raw_candidate, Mapping):
            raise workflow.WorkflowError("Momentum resume candidate must be an object.")
        candidate = dict(raw_candidate)
        candidate_id = candidate.get("id")
        topic = candidate.get("topic")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id.strip()
            or candidate_id in seen_ids
            or not isinstance(topic, str)
            or not topic.strip()
            or topic.casefold() in seen_topics
        ):
            raise workflow.WorkflowError(
                "Momentum resume candidates need distinct non-blank IDs and topics."
            )
        seen_ids.add(candidate_id)
        seen_topics.add(topic.casefold())
        if candidate.get("momentum_rank") != rank:
            raise workflow.WorkflowError("Momentum resume ranks must be ordered one through five.")
        if type(candidate.get("momentum_eligible")) is not bool:
            raise workflow.WorkflowError("Momentum resume eligibility must be boolean.")
        observed_axes = candidate.get("observed_axes")
        total = candidate.get("total")
        if (
            type(observed_axes) is not int
            or not 0 <= observed_axes <= len(momentum.MOMENTUM_AXES)
            or (
                total is not None
                and (type(total) is not int or not 0 <= total <= 25)
            )
        ):
            raise workflow.WorkflowError("Momentum resume scores are invalid.")
        if candidate.get("confidence") not in {"LOW", "MEDIUM", "HIGH"}:
            raise workflow.WorkflowError("Momentum resume confidence is invalid.")
        for field in ("why_now", "caveats"):
            if not isinstance(candidate.get(field), str) or not str(candidate[field]).strip():
                raise workflow.WorkflowError(
                    f"Momentum resume field {field!r} must be non-blank text."
                )
        platforms = candidate.get("platforms")
        if (
            not isinstance(platforms, Sequence)
            or isinstance(platforms, (str, bytes))
            or not platforms
            or any(not isinstance(value, str) or not value.strip() for value in platforms)
        ):
            raise workflow.WorkflowError("Momentum resume platforms are invalid.")
        authority_fit = candidate.get("authority_fit")
        if (
            not isinstance(authority_fit, Mapping)
            or type(authority_fit.get("total")) is not int
            or not 5 <= int(authority_fit["total"]) <= 25
        ):
            raise workflow.WorkflowError("Momentum resume authority fit is invalid.")
        candidates.append(candidate)
    return created_at, candidates


def command(args: argparse.Namespace) -> int:
    if not args.allow_web_research:
        raise workflow.WorkflowError("Discovery requires --allow-web-research.")
    if not args.allow_model_egress:
        raise workflow.WorkflowError(
            "Discovery requires --allow-model-egress before the private profile reaches thesis models."
        )
    profile = base.validate_profile(base._private_json(args.profile, "Authority profile"))
    if args.resume_momentum is not None:
        if args.output_dir is not None:
            raise workflow.WorkflowError(
                "--resume-momentum cannot be combined with --output-dir."
            )
        momentum_path = base._under_private(args.resume_momentum)
        as_of, top_five = validate_momentum_resume(
            base._private_json(momentum_path, "Momentum resume evidence"),
            requested_topic=args.topic,
            requested_days=args.days,
            requested_as_of=args.as_of,
        )
        folder = momentum_path.parent
        print(
            f"Resuming after momentum from "
            f"{momentum_path.relative_to(workflow.REPO_ROOT)}."
        )
    else:
        as_of = args.as_of or datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        workflow.parse_published_at(as_of)
        folder = base._under_private(
            args.output_dir
            or base.OUTPUT_ROOT / as_of[:10] / as_of[11:19].replace(":", "")
        )
        base.legacy_cli._ensure_owner_only_directory(folder)

        momentum_candidates = momentum.invoke_scout(args.topic, args.days, as_of)
        ranked = momentum.rank_candidates(
            momentum_candidates,
            minimum=momentum.MIN_AUTHORITY_MOMENTUM,
        )
        top_five = ranked[: momentum.MOMENTUM_TOP_K]
        authority_scores = momentum.score_authority_fit(top_five, profile)
        top_five = momentum.attach_authority_fit(top_five, authority_scores)

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
        print(
            f"Momentum evidence stored: "
            f"{momentum_package.relative_to(workflow.REPO_ROOT)}."
        )
    momentum.print_top(top_five)

    eligible = [item for item in top_five if item.get("momentum_eligible") is True]
    if len(eligible) < args.topic_count:
        raise workflow.WorkflowError(
            f"Fewer than {args.topic_count} topic(s) cleared the authority "
            "conversation-momentum floor; "
            "no topic-value selection or thesis generation was attempted."
        )

    items = _invoke_signal_scout(
        args.topic,
        args.days,
        as_of,
        [str(item["topic"]) for item in eligible],
    )
    raw_signals = base.project_signals(items)

    topic_value_candidates = topic_value.invoke_discovery_selector(
        profile,
        raw_signals,
        count=args.topic_count,
    )
    signals = topic_value.project_discovery_signals(raw_signals, topic_value_candidates)
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
        f"{len(topic_value_candidates)} situation(s) cleared Topic Value "
        "before thesis generation:"
    )
    for candidate in topic_value_candidates:
        print(
            f"{candidate['id']}: {candidate['reader_value_type']} | "
            f"gravity={candidate['gravity']} | priority={candidate['priority']} | "
            f"score={candidate['total']}/25"
        )
        print(f"Situation: {candidate['situation']}")
        print(f"Reader value: {candidate['reader_value']}")

    theses = search_theses(profile, signals)

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
            "draft_format_by_thesis": {
                str(card["id"]): draft_format_for(card, signals) for card in theses
            },
            "publishing_status": "DISABLED",
            "human_selection_required": True,
        },
    )
    db_rel = db.relative_to(workflow.REPO_ROOT).as_posix()
    print(
        f"Live research stored: inserted={inserted}; duplicates={duplicates}; "
        f"package={package.relative_to(workflow.REPO_ROOT)}."
    )
    print("Three theses cleared the locked authority bar:")
    for card in theses:
        strategy = base.write_private_json(
            folder / f"strategy-{card['id']}.json",
            base.strategy_for(card, profile),
        )
        strategy_rel = strategy.relative_to(workflow.REPO_ROOT).as_posix()
        output_format = draft_format_for(card, signals)
        draft = (
            f"./bin/linkedin-os draft --topic {json.dumps(str(card['topic']))} "
            f"--goal authority --format {output_format} --strategy-input {json.dumps(strategy_rel)} "
            f"--db {json.dumps(db_rel)} --allow-model-egress --package"
        )
        print(
            f"{card['id']}: {card['plain_language_summary']} "
            f"[{card['total']}/25; simplicity={card['scores']['simplicity']}/5]"
        )
        print(f"Decision: {card['product_decision']}")
        print(f"Conversation: {card['conversation_surface']}")
        print(
            f"Spine: {card['recommended_spine']} — {card['spine_fit_reason']}"
        )
        if output_format == "vertical-video":
            print(
                "Video priority: creator demo and runnable capability are traced; "
                "all normal writing, evidence, voice, quality, artifact, and human-review "
                "boundaries still apply."
            )
        print(f"Draft command: {draft}")
    print("No thesis was selected and no post was generated or published.")
    return 0


def parser() -> argparse.ArgumentParser:
    result = base.parser()
    result.add_argument(
        "--resume-momentum",
        type=Path,
        help=(
            "Resume from a validated momentum.json checkpoint under data/private "
            "without repeating momentum discovery or authority-fit scoring."
        ),
    )
    result.add_argument(
        "--topic-count",
        type=int,
        choices=(1, 2, 3),
        default=3,
        help=(
            "Number of independently qualified situations required before thesis "
            "generation; use 1 for a bounded single-topic pilot."
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
