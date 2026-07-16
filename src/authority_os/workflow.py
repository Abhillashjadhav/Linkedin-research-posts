"""Small offline foundation for the Authority OS workflow."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "private" / "authority_os.sqlite"
DEFAULT_FIXTURE = REPO_ROOT / "data" / "samples" / "dry-run.json"
DEFAULT_OUTPUTS = REPO_ROOT / "outputs"
SOURCE_QUALITIES = {"primary", "secondary", "mixed"}
SHORT_TOKENS = {"ai", "ml", "pm", "ux"}
TOPIC_CONNECTORS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
PREFIX_THEME_TERMS = {"eval", "govern", "reliab"}
STRATEGIC_GOALS = ("reach", "authority", "opportunity")
OUTPUT_FORMATS = (
    "text",
    "carousel",
    "vertical-video",
    "article",
    "artifact-demo",
)
WEEKLY_GOAL_MIX = ("reach", "authority", "authority", "opportunity")
STRATEGY_INPUT_FIELDS = (
    "target_reader",
    "reader_problem",
    "core_hypothesis",
    "product_decision",
    "authority_statement",
)
GOAL_ROUTES: dict[str, dict[str, object]] = {
    "reach": {
        "purpose": "Earn attention from relevant non-followers.",
        "narrative_route": ("incident", "mechanism", "implication"),
        "proof_required": False,
    },
    "authority": {
        "purpose": "Demonstrate differentiated GenAI product judgement.",
        "narrative_route": ("incident-or-problem", "mechanism", "decision"),
        "proof_required": False,
    },
    "opportunity": {
        "purpose": (
            "Convert credibility into profile visits, tool adoption, and inbound opportunities."
        ),
        "narrative_route": ("problem", "decision", "artifact", "evidence"),
        "proof_required": True,
    },
}


class WorkflowError(RuntimeError):
    """A safe, user-actionable workflow failure."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_published_at(value: str) -> datetime:
    """Parse a source timestamp into UTC, accepting date-only values as UTC."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid source timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonicalise_url(url: str) -> str:
    """Canonicalise a public HTTP(S) URL without fetching it."""

    raw = str(url).strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"invalid public URL: {raw!r}")
    if parts.username or parts.password:
        raise ValueError("source URLs must not contain credentials")
    hostname = parts.hostname.lower().rstrip(".")
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
    ):
        raise ValueError("local source URLs are not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            # inet_aton parses legacy numeric IPv4 spellings (for example
            # 127.1, integer, octal, and hexadecimal forms) without DNS.
            address = ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(hostname)))
        except OSError:
            address = None
    if address and not address.is_global:
        raise ValueError("private or non-global source URLs are not allowed")

    port = parts.port
    default_port = (parts.scheme.lower() == "http" and port == 80) or (
        parts.scheme.lower() == "https" and port == 443
    )
    if address:
        normalized_address = str(address)
        display_host = (
            f"[{normalized_address}]" if address.version == 6 else normalized_address
        )
    else:
        display_host = hostname
    netloc = display_host if not port or default_port else f"{display_host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (parts.scheme.lower(), netloc, path, urlencode(sorted(query)), "")
    )


canonicalize_url = canonicalise_url


def normalise_content(title: str, body: str) -> str:
    """Normalize the body as the dedup unit, with title as an honest fallback."""

    text = body if body.strip() else title
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


normalize_content = normalise_content


def content_hash(title: str, body: str) -> str:
    return hashlib.sha256(normalise_content(title, body).encode("utf-8")).hexdigest()


def prepare_research_items(
    raw_items: Iterable[Mapping[str, object]], *, fetched_at: str | None = None
) -> list[dict[str, object]]:
    """Validate and normalize source records before persistence."""

    prepared: list[dict[str, object]] = []
    fetched = fetched_at or now_iso()
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"research item {index} must be a JSON object")
        def text_field(name: str, fallback: str | None = None) -> str:
            value = item.get(name, item.get(fallback, "") if fallback else "")
            return "" if value is None else str(value).strip()

        title = text_field("title")
        body = text_field("body")
        source = text_field("source")
        published_at = text_field("published_at", "timestamp")
        quality = text_field("source_quality").lower()
        url = text_field("canonical_url", "url")
        if not title or not source or not published_at or not url:
            raise ValueError(
                f"research item {index} needs title, source, timestamp, and URL"
            )
        if quality not in SOURCE_QUALITIES:
            raise ValueError(
                f"research item {index} source_quality must be primary, secondary, or mixed"
            )
        parse_published_at(published_at)
        prepared.append(
            {
                "canonical_url": canonicalise_url(url),
                "title": title,
                "body": body,
                "source": source,
                "author": text_field("author"),
                "published_at": published_at,
                "source_quality": quality,
                "content_hash": content_hash(title, body),
                "fetched_at": fetched,
            }
        )
    return prepared


def load_research_file(path: Path | str) -> list[dict[str, object]]:
    source = Path(path)
    if not source.is_file():
        raise WorkflowError(f"Research input is not a readable file: {source}")
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"Could not read research input: {source}") from exc
    if source.suffix.lower() in {".jsonl", ".ndjson"}:
        items = [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]
    else:
        payload = json.loads(text)
        if isinstance(payload, dict):
            if "items" not in payload:
                raise WorkflowError("Research JSON object must contain an items[] list")
            items = payload["items"]
        else:
            items = payload
    if not isinstance(items, list):
        raise WorkflowError("Research input must be a JSON list or an object with items[]")
    return prepare_research_items(items)


def load_recent_posts_file(path: Path | str) -> list[str]:
    """Load an explicit private JSON array of recent post text for stale checks."""

    source = Path(path)
    if not source.is_file():
        raise WorkflowError(f"Recent-post input is not a readable file: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowError(f"Could not read recent-post input: {source}") from exc
    if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
        raise WorkflowError("Recent-post input must be a JSON list of strings")
    return [item.strip() for item in payload if item.strip()]


THEMES = {
    "agent-reliability": ("agent", "reliab", "failure", "workflow"),
    "evaluations": ("eval", "benchmark", "measure", "test"),
    "rag": ("rag", "retrieval", "rerank", "embedding"),
    "context-engineering": ("context", "prompt", "tool result"),
    "memory": ("memory", "remember", "state"),
    "mcp-tool-use": ("mcp", "tool use", "protocol"),
    "cost-latency": ("cost", "latency", "token", "inference"),
    "enterprise-governance": ("enterprise", "govern", "risk", "safety"),
}


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:60].rstrip("-") or "untitled"


def _theme_for(title: str) -> str:
    tokens = _tokens(title)

    def matches(term: str) -> bool:
        term_tokens = term.split()
        if len(term_tokens) > 1:
            pattern = r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, term_tokens)) + r"(?![a-z0-9])"
            return bool(re.search(pattern, title.casefold()))
        needle = term_tokens[0]
        if needle in PREFIX_THEME_TERMS:
            return any(token.startswith(needle) for token in tokens)
        return needle in tokens

    scored = [
        (sum(matches(term) for term in terms), theme)
        for theme, terms in THEMES.items()
    ]
    score, theme = max(scored, key=lambda pair: pair[0])
    return theme if score else slugify(title) or "other-signal"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 2 or token in SHORT_TOKENS
    }


def _lexical_tokens(text: str) -> set[str]:
    """Return boundary-safe lexical tokens without applying a length filter."""

    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def text_similarity(left: str, right: str) -> float:
    left_norm = normalise_content("", left)
    right_norm = normalise_content("", right)
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 1.0
    return max(sequence, jaccard)


def stale_against_recent(
    candidate: str, recent_posts: Sequence[str], *, threshold: float = 0.72
) -> bool:
    return any(text_similarity(candidate, recent) >= threshold for recent in recent_posts)


def deduplicate_analysis_items(
    current_items: Sequence[Mapping[str, object]],
    existing_items: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return unique current rows and unique current-plus-stored analysis rows."""

    current_unique: list[dict[str, object]] = []
    combined_unique: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    for rows, is_current in ((current_items, True), (existing_items, False)):
        for item in rows:
            canonical_url = item.get("canonical_url")
            digest = item.get("content_hash")
            if not isinstance(canonical_url, str) or not canonical_url.strip():
                raise WorkflowError("Analysis item needs a non-blank canonical URL.")
            if not isinstance(digest, str) or not digest.strip():
                raise WorkflowError("Analysis item needs a non-blank content hash.")
            if canonical_url in seen_urls or digest in seen_hashes:
                continue
            seen_urls.add(canonical_url)
            seen_hashes.add(digest)
            prepared = dict(item)
            combined_unique.append(prepared)
            if is_current:
                current_unique.append(prepared)
    return current_unique, combined_unique


def analyse_research(
    items: Sequence[Mapping[str, object]],
    *,
    topic: str | None = None,
    recent_posts: Sequence[str] | None = None,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Cluster metadata first, then interpret the strongest full bodies."""

    if not items:
        raise WorkflowError("No research evidence is available; nothing was manufactured.")

    grouped: dict[str, list[Mapping[str, object]]] = {}
    for index, item in enumerate(items, start=1):  # pass 1: no body interpretation
        title = str(item.get("title", "")).strip()
        source = str(item.get("source", "")).strip()
        if not title or not source:
            raise WorkflowError(f"Research item {index} is missing title or source metadata.")
        grouped.setdefault(_theme_for(title), []).append(item)

    reference_time = as_of or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    reference_time = reference_time.astimezone(timezone.utc)

    clusters: list[dict[str, object]] = []
    quality_rank = {"primary": 2, "mixed": 1, "secondary": 0}
    for slug, members in grouped.items():  # pass 2: strongest full bodies
        dated_members: list[tuple[Mapping[str, object], datetime]] = []
        for item in members:
            raw_timestamp = str(item.get("published_at", "")).strip()
            try:
                published = parse_published_at(raw_timestamp)
            except ValueError as exc:
                raise WorkflowError(str(exc)) from exc
            dated_members.append((item, published))
        ranked = sorted(
            dated_members,
            key=lambda pair: (
                quality_rank.get(str(pair[0].get("source_quality", "")), -1),
                pair[1],
                str(pair[0].get("canonical_url", "")).casefold(),
                str(pair[0].get("title", "")).casefold(),
            ),
            reverse=True,
        )
        readable = [
            (item, published, str(item.get("body", "")).strip())
            for item, published in ranked
            if str(item.get("body", "")).strip()
        ][:3]
        high_quality_readable = [
            row
            for row in readable
            if row[0].get("source_quality") in {"primary", "mixed"}
        ]
        selected_body = (high_quality_readable or readable)
        if selected_body:
            strongest_item, strongest_published, strongest_body = selected_body[0]
            dominant = strongest_body.split(". ", 1)[0].rstrip(".")[:500]
        else:
            strongest_item, strongest_published = ranked[0]
            dominant = "Body unavailable"
        thesis_text = f"{strongest_item.get('title', '')} {dominant}".strip()
        primary_sources = [
            str(item.get("canonical_url", ""))
            for item, _published, _body in high_quality_readable
            if str(item.get("canonical_url", "")).strip()
        ]
        publisher_identities: set[str] = set()
        for item, _published in dated_members:
            canonical_url = str(item.get("canonical_url", ""))
            hostname = urlsplit(canonical_url).hostname if canonical_url else None
            publisher_identities.add(
                (hostname or str(item.get("source", ""))).strip().casefold()
            )
        publisher_identities.discard("")
        freshest = max(published for _item, published in dated_members)
        if freshest > reference_time + timedelta(days=1):
            raise WorkflowError(
                f"Source timestamp {freshest.isoformat()} is implausibly in the future."
            )
        age_days = max(0, (reference_time - freshest).days)
        recency_score = (
            4
            if age_days <= 7
            else 3
            if age_days <= 30
            else 2
            if age_days <= 90
            else 1
            if age_days <= 365
            else 0
        )
        recency_sufficient = age_days <= 90
        recency_reason = (
            "recent evidence supports a why-now case"
            if recency_sufficient
            else "evidence is older than 90 days; why-now is not established"
        )
        clusters.append(
            {
                "slug": slug,
                "item_count": len(members),
                "source_count": len(publisher_identities),
                "momentum": min(
                    10, len(members) * 2 + len(publisher_identities) + recency_score
                ),
                "why_now": (
                    f"{len(members)} item(s) across {len(publisher_identities)} source "
                    f"hostname(s); freshest evidence is {age_days} day(s) old, so {recency_reason}. "
                    f"Strongest body: {str(strongest_item.get('title', ''))[:300]} "
                    f"({strongest_published.isoformat()})."
                ),
                "dominant_take": dominant,
                "missing_angle": (
                    "What product decision changes, and what evidence would falsify it?"
                ),
                "primary_sources": primary_sources,
                "source_quality_sufficient": bool(high_quality_readable),
                "body_read_sufficient": bool(readable),
                "recency_sufficient": recency_sufficient,
                "latest_published_at": freshest.isoformat(),
                "age_days": age_days,
                "stale": (
                    None
                    if recent_posts is None
                    else stale_against_recent(thesis_text, recent_posts)
                ),
            }
        )
    clusters.sort(
        key=lambda cluster: (
            -int(cluster["momentum"]),
            -int(cluster["source_count"]),
            str(cluster["slug"]),
        )
    )

    selected = clusters[0]
    if topic:
        topic_tokens = _lexical_tokens(topic) - TOPIC_CONNECTORS
        if not topic_tokens:
            raise WorkflowError(
                "Requested topic needs at least one meaningful token; nothing was inferred."
            )
        scored_clusters: list[tuple[int, dict[str, object]]] = []
        for cluster in clusters:
            members = grouped[str(cluster["slug"])]
            searchable = " ".join(
                [str(cluster["slug"]), *[str(item.get("title", "")) for item in members]]
            )
            searchable_tokens = _lexical_tokens(searchable)
            scored_clusters.append(
                (len(topic_tokens) if topic_tokens <= searchable_tokens else 0, cluster)
            )
        scored_clusters.sort(
            key=lambda pair: (
                -pair[0],
                -int(pair[1]["momentum"]),
                -int(pair[1]["source_count"]),
                str(pair[1]["slug"]),
            )
        )
        match_count, selected = scored_clusters[0]
        if match_count == 0:
            raise WorkflowError(
                f"No research cluster matches requested topic {topic!r}; nothing was inferred."
            )
    diverse = sum(cluster["source_count"] >= 2 for cluster in clusters)
    broad_sufficient = len(clusters) >= 7 and diverse >= 4
    return {
        "pass_1": {
            "item_count": len(items),
            "cluster_count": len(clusters),
            "source_diverse_cluster_count": diverse,
        },
        "pass_2": {"clusters": clusters, "selected": selected},
        "broad_discovery_sufficient": broad_sufficient,
        "broad_discovery_note": (
            "Broad discovery target met."
            if broad_sufficient
            else "Insufficient evidence for seven viable and four source-diverse clusters; proceeding only with the explicitly selected evidence."
        ),
        "selected_source_quality_sufficient": selected["source_quality_sufficient"],
        "selected_body_read_sufficient": selected["body_read_sufficient"],
        "selected_recency_sufficient": selected["recency_sufficient"],
        "selected_stale": selected["stale"],
    }


def resolve_strategic_goal(
    *,
    goal: str | None = None,
    week_slot: int | None = None,
    strong_current_signal: bool = False,
) -> str:
    """Resolve one explicit/default goal without inferring it from output format."""

    if type(strong_current_signal) is not bool:
        raise WorkflowError("Strong-current-signal must be a boolean assertion.")
    selected_goal = goal.strip().casefold() if isinstance(goal, str) else goal
    if selected_goal is not None and selected_goal not in STRATEGIC_GOALS:
        allowed = ", ".join(STRATEGIC_GOALS)
        raise WorkflowError(f"Strategic goal must be one of: {allowed}.")
    invalid_slot = (
        isinstance(week_slot, bool)
        or not isinstance(week_slot, int)
        or not 1 <= week_slot <= 5
    )
    if week_slot is not None and invalid_slot:
        raise WorkflowError("Weekly slot must be an integer from 1 to 5.")
    if strong_current_signal and week_slot != 5:
        raise WorkflowError("A strong current signal is only used to justify optional slot 5.")
    if week_slot is None:
        return selected_goal or "authority"
    if week_slot <= len(WEEKLY_GOAL_MIX):
        planned_goal = WEEKLY_GOAL_MIX[week_slot - 1]
        if selected_goal and selected_goal != planned_goal:
            raise WorkflowError(
                f"Weekly slot {week_slot} is reserved for {planned_goal}; "
                f"received {selected_goal}."
            )
        return planned_goal
    if not strong_current_signal:
        raise WorkflowError("Optional weekly slot 5 requires a strong current incident or launch.")
    if not selected_goal:
        raise WorkflowError("Optional weekly slot 5 requires an explicit strategic goal.")
    return selected_goal


def build_strategy_brief(
    selected_cluster: Mapping[str, object],
    *,
    strategy_inputs: Mapping[str, object],
    strategy_input_origin: str,
    goal: str | None = None,
    output_format: str | None = None,
    week_slot: int | None = None,
    strong_current_signal: bool = False,
) -> dict[str, object]:
    """Route analysed evidence into a small, non-drafting strategy brief."""

    if not isinstance(selected_cluster, Mapping):
        raise WorkflowError("Selected analysis must be a mapping.")
    if not isinstance(strategy_inputs, Mapping):
        raise WorkflowError("Strategy inputs must be a mapping.")
    if strategy_input_origin not in {"explicit-input", "synthetic-fixture"}:
        raise WorkflowError(
            "Strategy input origin must be 'explicit-input' or 'synthetic-fixture'."
        )
    chosen_format = (
        output_format.strip().casefold() if isinstance(output_format, str) else output_format
    )
    if chosen_format is not None and chosen_format not in OUTPUT_FORMATS:
        allowed = ", ".join(OUTPUT_FORMATS)
        raise WorkflowError(f"Output format must be one of: {allowed}.")
    chosen_goal = resolve_strategic_goal(
        goal=goal,
        week_slot=week_slot,
        strong_current_signal=strong_current_signal,
    )
    analysis_text_fields = (
        "slug",
        "why_now",
        "dominant_take",
        "missing_angle",
    )
    analysis_flag_fields = (
        "source_quality_sufficient",
        "body_read_sufficient",
        "recency_sufficient",
    )
    required_analysis = (*analysis_text_fields, *analysis_flag_fields, "stale", "primary_sources")
    missing = [name for name in required_analysis if name not in selected_cluster]
    if missing:
        raise WorkflowError(
            f"Selected analysis is missing required field(s): {', '.join(missing)}."
        )
    analysis_text: dict[str, str] = {}
    for name in analysis_text_fields:
        value = selected_cluster[name]
        if not isinstance(value, str) or not value.strip():
            raise WorkflowError(f"Selected analysis field {name!r} must be non-blank text.")
        analysis_text[name] = value.strip()
    analysis_flags: dict[str, bool] = {}
    for name in analysis_flag_fields:
        value = selected_cluster[name]
        if type(value) is not bool:
            raise WorkflowError(f"Selected analysis field {name!r} must be boolean.")
        analysis_flags[name] = value
    stale = selected_cluster["stale"]
    if stale is not None and type(stale) is not bool:
        raise WorkflowError("Selected analysis field 'stale' must be boolean or null.")

    raw_sources = selected_cluster["primary_sources"]
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise WorkflowError("Selected analysis primary_sources must be a list of URLs.")
    primary_sources: list[str] = []
    for index, source in enumerate(raw_sources, start=1):
        if not isinstance(source, str) or not source.strip():
            raise WorkflowError(f"Primary source {index} must be a non-blank URL.")
        try:
            canonical_source = canonicalise_url(source)
        except ValueError as exc:
            raise WorkflowError(f"Primary source {index} is invalid: {exc}") from exc
        if canonical_source not in primary_sources:
            primary_sources.append(canonical_source)

    strategic_fields: dict[str, str] = {}
    for name in STRATEGY_INPUT_FIELDS:
        value = strategy_inputs.get(name)
        if not isinstance(value, str) or not value.strip():
            raise WorkflowError(f"Strategy input {name!r} must be non-blank text.")
        strategic_fields[name] = value.strip()

    limitations: list[str] = []
    if not analysis_flags["source_quality_sufficient"]:
        limitations.append("readable-primary-or-mixed-source-missing")
    if not analysis_flags["body_read_sufficient"]:
        limitations.append("readable-body-missing")
    if not analysis_flags["recency_sufficient"]:
        limitations.append("recent-evidence-missing")
    if stale is True:
        limitations.append("topic-similar-to-recent-post")
    if not primary_sources:
        limitations.append("traceable-primary-source-missing")
    if stale is None:
        limitations.append("recent-post-similarity-not-evaluated")

    route = GOAL_ROUTES[chosen_goal]
    return {
        "topic_slug": analysis_text["slug"],
        "goal": chosen_goal,
        "goal_purpose": route["purpose"],
        "narrative_route": list(route["narrative_route"]),
        "output_format": chosen_format,
        "proof_required": route["proof_required"],
        "weekly_slot": week_slot,
        **strategic_fields,
        "strategy_input_origin": strategy_input_origin,
        "primary_sources": primary_sources,
        "evidence_status": {
            **analysis_flags,
            "stale": stale,
            "primary_source_count": len(primary_sources),
            "limitations": limitations,
        },
        "analysis": {
            "why_now": analysis_text["why_now"],
            "dominant_take": analysis_text["dominant_take"],
            "missing_angle": analysis_text["missing_angle"],
            **analysis_flags,
            "stale": stale,
        },
    }


def _replace_template(value: object, topic: str) -> object:
    if isinstance(value, str):
        return value.replace("{{topic}}", topic)
    if isinstance(value, list):
        return [_replace_template(item, topic) for item in value]
    if isinstance(value, dict):
        return {key: _replace_template(item, topic) for key, item in value.items()}
    return value


def load_fixture(
    path: Path | str = DEFAULT_FIXTURE, *, topic: str | None = None
) -> dict[str, object]:
    """Load and validate the deterministic, synthetic offline fixture."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"Fixture does not exist: {source}") from exc
    if not isinstance(payload, Mapping):
        raise WorkflowError("Fixture root must be a JSON object.")
    chosen_topic = topic or str(payload.get("topic", "")).strip()
    if not chosen_topic:
        raise WorkflowError("Fixture needs a topic.")
    replaced = _replace_template(dict(payload), chosen_topic)
    if replaced.get("fixture_mode") is not True or replaced.get("synthetic") is not True:
        raise WorkflowError("Offline fixture must be explicitly synthetic fixture data.")
    raw_as_of = replaced.get("as_of")
    if not isinstance(raw_as_of, str) or not raw_as_of.strip():
        raise WorkflowError("Fixture needs a non-blank as_of timestamp.")
    try:
        fixture_as_of = parse_published_at(raw_as_of.strip())
    except ValueError as exc:
        raise WorkflowError(f"Fixture as_of timestamp is invalid: {exc}") from exc
    items = replaced.get("research_items")
    if not isinstance(items, list):
        raise WorkflowError("Fixture needs a research_items list.")
    replaced["as_of"] = fixture_as_of.isoformat()
    replaced["topic"] = chosen_topic
    return replaced
