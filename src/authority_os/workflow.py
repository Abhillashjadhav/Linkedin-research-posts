"""Small offline foundation for the Authority OS workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "private" / "authority_os.sqlite"
DEFAULT_FIXTURE = REPO_ROOT / "data" / "samples" / "dry-run.json"
DEFAULT_OUTPUTS = REPO_ROOT / "outputs"


class WorkflowError(RuntimeError):
    """A safe, user-actionable workflow failure."""


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
