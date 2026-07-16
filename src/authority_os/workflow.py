"""Small offline foundation for the Authority OS workflow."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "private" / "authority_os.sqlite"
DEFAULT_FIXTURE = REPO_ROOT / "data" / "samples" / "dry-run.json"
DEFAULT_OUTPUTS = REPO_ROOT / "outputs"
SOURCE_QUALITIES = {"primary", "secondary", "mixed"}


class WorkflowError(RuntimeError):
    """A safe, user-actionable workflow failure."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        source = str(item.get("source", "")).strip()
        published_at = str(item.get("published_at", item.get("timestamp", ""))).strip()
        quality = str(item.get("source_quality", "")).strip().lower()
        url = str(item.get("canonical_url", item.get("url", ""))).strip()
        if not title or not source or not published_at or not url:
            raise ValueError(
                f"research item {index} needs title, source, timestamp, and URL"
            )
        if quality not in SOURCE_QUALITIES:
            raise ValueError(
                f"research item {index} source_quality must be primary, secondary, or mixed"
            )
        prepared.append(
            {
                "canonical_url": canonicalise_url(url),
                "title": title,
                "body": body,
                "source": source,
                "author": str(item.get("author", "")).strip(),
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
        items = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise WorkflowError("Research input must be a JSON list or an object with items[]")
    return prepare_research_items(items)


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
    items = replaced.get("research_items")
    if not isinstance(items, list):
        raise WorkflowError("Fixture needs a research_items list.")
    replaced["topic"] = chosen_topic
    return replaced
