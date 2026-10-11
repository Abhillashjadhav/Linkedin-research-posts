"""Structural contracts for the opt-in Sunday explanatory article route.

Sources and attestations are supplied by the caller. Validation establishes
traceability and shape, not the truth of the evidence or quality of the prose.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .workflow import WorkflowError


CONTRACT_VERSION = "sunday-article-v1"
DEFAULT_WORD_RANGE = {"min": 1000, "max": 1150}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_WORD = re.compile(r"\b[\w]+(?:['’\-][\w]+)*\b", re.UNICODE)
_PLACEHOLDER = re.compile(
    r"\b(?:TODO|TBD|TK)\b|\[(?:insert|placeholder|todo|tbd)[^\]]*\]|"
    r"\{\{[^{}]+\}\}|<\s*(?:insert|placeholder|todo|tbd)\b[^>]*>",
    re.IGNORECASE,
)


def _object(value: object, path: str, required: set[str], optional: set[str] = frozenset()) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise WorkflowError(f"{path} must be an object.")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise WorkflowError(f"{path} has missing or unsupported fields.")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{path} must be non-empty text.")
    return value.strip()


def _id(value: object, path: str) -> str:
    clean = _text(value, path)
    if not _ID.fullmatch(clean):
        raise WorkflowError(f"{path} must be a stable identifier without spaces.")
    return clean


def _url(value: object, path: str) -> str:
    clean = _text(value, path)
    try:
        parsed = urlsplit(clean)
        # Accessing hostname/port also validates bracketed hosts and port syntax.
        hostname, port = parsed.hostname, parsed.port
        username, password = parsed.username, parsed.password
    except ValueError as exc:
        raise WorkflowError(f"{path} must be a valid HTTP(S) URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or username is not None
        or password is not None
        or any(char.isspace() for char in clean)
        or parsed.netloc.endswith(":")
        or (port is not None and port < 1)
    ):
        raise WorkflowError(f"{path} must be an HTTP(S) URL without credentials.")
    return clean


def _list(value: object, path: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        raise WorkflowError(f"{path} must be {'a non-empty' if nonempty else 'a'} list.")
    return value


def _ids(value: object, path: str, *, nonempty: bool = False) -> list[str]:
    clean = [_id(item, f"{path} item") for item in _list(value, path, nonempty=nonempty)]
    if len(clean) != len(set(clean)):
        raise WorkflowError(f"{path} must have unique IDs.")
    return clean


def _unique(records: list[dict[str, Any]], path: str) -> set[str]:
    ids = [item["id"] for item in records]
    if len(ids) != len(set(ids)):
        raise WorkflowError(f"{path} IDs must be unique.")
    return set(ids)


def _known(references: list[str], known: set[str], path: str) -> None:
    if not set(references) <= known:
        raise WorkflowError(f"{path} contains an unknown ID.")


def validate_brief(value: object) -> dict[str, Any]:
    """Return a detached, normalized brief with checked evidence references.

    This never fetches a URL or establishes whether supplied content is accurate.
    """
    raw = _object(value, "brief", {
        "contract_version", "topic_id", "topic", "reader", "thesis", "technical_concept",
        "worked_example", "author", "sources", "claims",
    }, {"voice_examples", "locked_title", "word_range", "resource"})
    if raw["contract_version"] != CONTRACT_VERSION:
        raise WorkflowError("brief contract_version must be sunday-article-v1.")
    reader = _object(raw["reader"], "reader", {"audience", "stake", "desired_outcome"})
    author = _object(raw["author"], "author", {"name", "byline", "attestations"})
    attestations = []
    for item in _list(author["attestations"], "author.attestations"):
        record = _object(item, "attestation", {"id", "text"})
        attestations.append({"id": _id(record["id"], "attestation.id"), "text": _text(record["text"], "attestation.text")})
    attestation_ids = _unique(attestations, "attestation")

    sources = []
    for item in _list(raw["sources"], "sources", nonempty=True):
        record = _object(item, "source", {"id", "url", "title", "content"}, {"version", "retrieved_at"})
        source = {
            "id": _id(record["id"], "source.id"), "url": _url(record["url"], "source.url"),
            "title": _text(record["title"], "source.title"),
            "content": _text(record["content"], "source.content"),
        }
        for field in ("version", "retrieved_at"):
            if field in record:
                source[field] = _text(record[field], f"source.{field}")
        sources.append(source)
    source_ids = _unique(sources, "source")

    claims = []
    for item in _list(raw["claims"], "claims", nonempty=True):
        record = _object(item, "claim", {"id", "text", "kind", "source_ids"}, {"attestation_id", "limitations"})
        kind = record["kind"]
        if not isinstance(kind, str) or kind not in {"finding", "author_attestation", "interpretation", "proposal"}:
            raise WorkflowError("claim.kind is unsupported.")
        refs = _ids(record["source_ids"], "claim.source_ids", nonempty=(kind == "finding"))
        _known(refs, source_ids, "claim.source_ids")
        claim = {
            "id": _id(record["id"], "claim.id"), "text": _text(record["text"], "claim.text"),
            "kind": kind, "source_ids": refs,
        }
        if kind == "author_attestation":
            if "attestation_id" not in record:
                raise WorkflowError("author_attestation claim requires attestation_id.")
            claim["attestation_id"] = _id(record["attestation_id"], "claim.attestation_id")
            _known([claim["attestation_id"]], attestation_ids, "claim.attestation_id")
        elif "attestation_id" in record:
            raise WorkflowError("Only author_attestation claims may use attestation_id.")
        if "limitations" in record:
            claim["limitations"] = _text(record["limitations"], "claim.limitations")
        claims.append(claim)
    claim_ids = _unique(claims, "claim")

    range_raw = _object(raw.get("word_range", DEFAULT_WORD_RANGE), "word_range", {"min", "max"})
    low, high = range_raw["min"], range_raw["max"]
    if type(low) is not int or type(high) is not int or low < 1 or high < low:
        raise WorkflowError("word_range must have positive integer min and max, min <= max.")
    normalized: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "topic_id": _id(raw["topic_id"], "topic_id"),
        "topic": _text(raw["topic"], "topic"),
        "reader": {field: _text(reader[field], f"reader.{field}") for field in ("audience", "stake", "desired_outcome")},
        "thesis": _text(raw["thesis"], "thesis"),
        "technical_concept": _text(raw["technical_concept"], "technical_concept"),
        "worked_example": _text(raw["worked_example"], "worked_example"),
        "author": {"name": _text(author["name"], "author.name"), "byline": _text(author["byline"], "author.byline"), "attestations": attestations},
        "sources": sources, "claims": claims, "word_range": {"min": low, "max": high},
        "voice_examples": [_text(item, "voice_examples item") for item in _list(raw.get("voice_examples", []), "voice_examples")],
    }
    if "locked_title" in raw:
        normalized["locked_title"] = _text(raw["locked_title"], "locked_title")
    if "resource" in raw:
        record = _object(raw["resource"], "resource", {"name", "url", "source_ids"}, {"description", "claim_ids", "license"})
        refs = _ids(record["source_ids"], "resource.source_ids", nonempty=True)
        _known(refs, source_ids, "resource.source_ids")
        resource: dict[str, Any] = {
            "name": _text(record["name"], "resource.name"),
            "url": _url(record["url"], "resource.url"), "source_ids": refs,
        }
        if "description" in record:
            resource["description"] = _text(record["description"], "resource.description")
        if "claim_ids" in record:
            resource["claim_ids"] = _ids(record["claim_ids"], "resource.claim_ids", nonempty=True)
            _known(resource["claim_ids"], claim_ids, "resource.claim_ids")
        if "license" in record:
            resource["license"] = _text(record["license"], "resource.license")
            linked = [claim for claim in claims if claim["id"] in resource.get("claim_ids", [])
                      and claim["kind"] == "finding" and set(claim["source_ids"]) & set(refs)]
            if not linked:
                raise WorkflowError("resource.license requires a linked finding claim from resource sources.")
        normalized["resource"] = resource
    return normalized


def validate_article(article: object, brief: Mapping[str, object]) -> dict[str, Any]:
    """Validate structure and locks; editorial/factual review remains separate."""
    safe_brief = validate_brief(brief)
    raw = _object(article, "article", {"topic_id", "thesis", "title", "sections"})
    if raw["topic_id"] != safe_brief["topic_id"] or raw["thesis"] != safe_brief["thesis"]:
        raise WorkflowError("Article must preserve the brief's topic_id and thesis exactly.")
    title = _text(raw["title"], "article.title")
    if "locked_title" in safe_brief and title != safe_brief["locked_title"]:
        raise WorkflowError("Article must preserve locked_title exactly.")
    if _PLACEHOLDER.search(title):
        raise WorkflowError("Article contains an editorial placeholder.")
    known = {item["id"] for item in safe_brief["claims"]}
    sections = []
    for item in _list(raw["sections"], "article.sections", nonempty=True):
        section = _object(item, "article section", {"id", "heading", "text", "claim_ids"})
        heading = _text(section["heading"], "section.heading")
        body = _text(section["text"], "section.text")
        if _PLACEHOLDER.search(heading) or _PLACEHOLDER.search(body):
            raise WorkflowError("Article contains an editorial placeholder.")
        refs = _ids(section["claim_ids"], "section.claim_ids")
        _known(refs, known, "section.claim_ids")
        sections.append({"id": _id(section["id"], "section.id"), "heading": heading, "text": body, "claim_ids": refs})
    _unique(sections, "section")
    count = sum(len(_WORD.findall(section["text"])) for section in sections)
    bounds = safe_brief["word_range"]
    if not bounds["min"] <= count <= bounds["max"]:
        raise WorkflowError(f"Article body has {count} words; expected {bounds['min']}–{bounds['max']}.")
    return {"topic_id": safe_brief["topic_id"], "thesis": safe_brief["thesis"], "title": title, "sections": sections}


def article_text(article: object, brief: Mapping[str, object]) -> str:
    """Render the validated article with the supplied byline."""
    safe = validate_article(article, brief)
    byline = validate_brief(brief)["author"]["byline"]
    return "\n\n".join([safe["title"], byline, *(
        f"{section['heading']}\n\n{section['text']}" for section in safe["sections"]
    )]) + "\n"


def article_hash(article: object, brief: Mapping[str, object]) -> str:
    """Hash the validated article and its complete normalized input brief."""
    safe_brief = validate_brief(brief)
    safe_article = validate_article(article, safe_brief)
    payload = json.dumps(
        {"brief": safe_brief, "article": safe_article},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
