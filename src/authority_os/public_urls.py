"""One public-link projection, separate from private evidence URL identity."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class PublicURL:
    url: str | None
    reason: str | None = None


_TRACKING_KEYS = {"fbclid", "gclid"}
_SENSITIVE_KEYS = {
    "access_token", "api_key", "apikey", "auth", "authorization", "code",
    "credential", "key", "password", "secret", "sig", "signature", "token",
}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_BARE_FILE_SUFFIXES = {"md", "py", "json", "txt", "csv", "tsv", "mp4", "png", "jpg",
                       "jpeg", "pdf", "docx", "xlsx", "pptx", "sqlite", "yaml", "yml", "toml"}
_URL_TEXT = re.compile(
    r"(?<![@\w])(?:[a-z][a-z0-9+.-]*://|(?:https?|file):(?=\S)|localhost(?=[:/\\\s]|$)|"
    r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|\[[0-9a-f:]+\]|"
    r"(?:www\.)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,})"
    r"(?:(?!\]\()[^\s<>\"'])*", re.IGNORECASE,
)


def project_public_url(value: object) -> PublicURL:
    """Return a usable public URL or a safe reason; never expose denied bytes.

    Evidence canonicalization is deliberately untouched. Only this derived view
    crosses the public/model boundary. Query meaning is allowlisted by host/path.
    """
    from . import workflow

    if not isinstance(value, str) or not value.strip():
        return PublicURL(None, "missing-url")
    raw = value.strip()
    if len(raw) > 2048 or "\\" in raw or any(
        char.isspace() or unicodedata.category(char) in {"Cc", "Cf", "Cs"}
        for char in value
    ):
        return PublicURL(None, "invalid-url")
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return PublicURL(None, "non-public-scheme")
        if parts.username is not None or parts.password is not None:
            return PublicURL(None, "credentials-not-public")
        hostname = parts.hostname.casefold().rstrip(".")
        if "." not in hostname and ":" not in hostname:
            return PublicURL(None, "local-destination")
        if "%" in hostname or hostname.endswith((".internal", ".lan", ".home", ".home.arpa", ".localdomain", ".local", ".localhost", ".test", ".invalid")) or hostname in {"localhost", "home.arpa"}:
            return PublicURL(None, "local-destination")
        canonical = workflow.canonicalise_url(raw)
        normalized = urlsplit(canonical)
        if re.search(r"%(?![0-9a-fA-F]{2})", parts.query):
            return PublicURL(None, "invalid-query")
        pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=100)
    except (ValueError, UnicodeError):
        return PublicURL(None, "invalid-public-url")
    semantic = [(key, val) for key, val in pairs
                if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_KEYS]
    if any(key.casefold() in _SENSITIVE_KEYS or key.casefold().startswith("x-amz-")
           for key, _val in semantic):
        return PublicURL(None, "sensitive-query")
    is_watch = normalized.hostname in _YOUTUBE_HOSTS and normalized.path == "/watch"
    if is_watch:
        if normalized.port is not None or len(semantic) != 1 or semantic[0][0] != "v":
            return PublicURL(None, "unsupported-query")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", semantic[0][1]) or semantic[0][1].casefold() in {"video_id___", "placeholder"}:
            return PublicURL(None, "invalid-video-id")
    elif semantic:
        return PublicURL(None, "unsupported-query")
    # A bare question mark and tracking-only queries carry no resource identity.
    return PublicURL(urlunsplit((normalized.scheme, normalized.netloc, normalized.path,
                                urlencode(semantic), "")))


def require_public_url(value: object) -> str:
    projection = project_public_url(value)
    if projection.url is None:
        raise ValueError(f"Public URL withheld: {projection.reason}.")
    return projection.url


def _text_url(raw: str) -> tuple[str, str]:
    # Keep balanced URL path parentheses and bracketed IPv6 authorities while
    # removing the surrounding sentence/Markdown delimiters.
    end = len(raw)
    while end:
        char = raw[end - 1]
        if char in ".,;:!":
            end -= 1
        elif char in ")]}":
            opening = {")": "(", "]": "[", "}": "{"}[char]
            candidate = raw[:end]
            if candidate.count(char) > candidate.count(opening):
                end -= 1
            else:
                break
        else:
            break
    return raw[:end], raw[end:]


def _prose_candidate(raw: str) -> str | None:
    if "://" in raw or re.match(r"^(?:https?|file):", raw, re.I):
        return raw
    # Ordinary filenames are not evidence links. An explicit URL can still use
    # a real domain such as readme.md; bare README.md remains literal prose.
    host = raw.split("/", 1)[0].split("?", 1)[0].casefold()
    if host.rsplit(".", 1)[-1] in _BARE_FILE_SUFFIXES:
        return None
    return f"https://{raw}"


def redact_public_urls(
    text: str, source_ids_by_url: Mapping[str, str] | None = None,
) -> tuple[str, int]:
    """Normalize safe embedded links and withhold unsafe links with safe markers."""
    from . import workflow

    changed = 0
    identities = source_ids_by_url or {}

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        raw, suffix = _text_url(match.group(0))
        candidate = _prose_candidate(raw)
        if candidate is None:
            return match.group(0)
        projected = project_public_url(candidate)
        if projected.url is not None:
            if candidate != raw:
                # Preserve bare-link spelling, including ordinary prose that
                # resembles a domain; normalization never invents a scheme.
                return (projected.url.removeprefix("https://") if "?" in raw else raw) + suffix
            return (raw if projected.url == candidate else projected.url) + suffix
        changed += 1
        try:
            source_id = identities.get(workflow.canonicalise_url(candidate))
        except ValueError:
            source_id = None
        marker = (f"[citation URL for {source_id} requires review]" if source_id else
                  f"[query URL withheld for citation review: {projected.reason}]" if "?" in raw else
                  f"[URL withheld: {projected.reason}]")
        return marker + suffix

    return _URL_TEXT.sub(replace, text), changed


def extract_public_urls(text: str) -> list[str]:
    """Find actual usable links; a withheld placeholder cannot become a link."""
    result: set[str] = set()
    for match in _URL_TEXT.finditer(text):
        raw, _suffix = _text_url(match.group(0))
        candidate = _prose_candidate(raw)
        if candidate is None:
            continue
        projection = project_public_url(candidate)
        if projection.url is not None:
            result.add(projection.url)
    return sorted(result)


def public_url_spans(text: str) -> list[tuple[int, int, str]]:
    """Locate validated public links so prose privacy checks can preserve them."""
    result: list[tuple[int, int, str]] = []
    for match in _URL_TEXT.finditer(text):
        raw, _suffix = _text_url(match.group(0))
        candidate = _prose_candidate(raw)
        if candidate is None:
            continue
        projection = project_public_url(candidate)
        if projection.url is not None:
            result.append((match.start(), match.start() + len(raw), projection.url))
    return result
