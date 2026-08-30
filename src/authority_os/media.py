"""Post-approval media selection and production brief generation.

Media is deliberately downstream of human post approval. The stage never changes the
post, never browses, and never publishes. It chooses whether the approved post benefits
from an image, PDF carousel, short video, or no media, then writes a private production
package. Image/video rendering remains a separate media-capable renderer concern.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import workflow
from .model_runtime import ModelConfig, invoke_structured

MEDIA_TYPES = ("IMAGE", "CAROUSEL_PDF", "VIDEO", "NONE")
MAX_POST_BYTES = 100_000
MAX_ITEMS = 8
MODEL = ModelConfig("codex", "gpt-5.6-sol", "high")
DEFAULT_ROOT = workflow.DEFAULT_PRIVATE_DATA / "media"


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "media_type": {"type": "string", "enum": list(MEDIA_TYPES)},
            "rationale": {"type": "string"},
            "reader_job": {"type": "string"},
            "headline": {"type": "string"},
            "visual_direction": {"type": "string"},
            "image_prompt": {"type": "string"},
            "slides": {
                "type": "array",
                "minItems": 0,
                "maxItems": MAX_ITEMS,
                "items": {"type": "string"},
            },
            "video_beats": {
                "type": "array",
                "minItems": 0,
                "maxItems": MAX_ITEMS,
                "items": {"type": "string"},
            },
            "alt_text": {"type": "string"},
        },
        "required": [
            "media_type",
            "rationale",
            "reader_job",
            "headline",
            "visual_direction",
            "image_prompt",
            "slides",
            "video_beats",
            "alt_text",
        ],
        "additionalProperties": False,
    }


def _safe_text(value: object, *, label: str, limit: int = 4_000, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise workflow.WorkflowError(f"Media {label} must be text.")
    cleaned = value.strip()
    if not cleaned and not allow_blank:
        raise workflow.WorkflowError(f"Media {label} must be non-blank.")
    if len(cleaned) > limit or any(ord(ch) < 9 for ch in cleaned):
        raise workflow.WorkflowError(f"Media {label} is unsafe or too long.")
    return cleaned


def validate_plan(raw: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "media_type",
        "rationale",
        "reader_job",
        "headline",
        "visual_direction",
        "image_prompt",
        "slides",
        "video_beats",
        "alt_text",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise workflow.WorkflowError("Media planner returned an invalid schema.")
    media_type = raw.get("media_type")
    if media_type not in MEDIA_TYPES:
        raise workflow.WorkflowError("Media planner returned an unsupported media type.")

    plan: dict[str, object] = {
        "media_type": media_type,
        "rationale": _safe_text(raw.get("rationale"), label="rationale", limit=1_500),
        "reader_job": _safe_text(raw.get("reader_job"), label="reader job", limit=800),
        "headline": _safe_text(raw.get("headline"), label="headline", limit=160, allow_blank=media_type == "NONE"),
        "visual_direction": _safe_text(raw.get("visual_direction"), label="visual direction", limit=1_500, allow_blank=media_type == "NONE"),
        "image_prompt": _safe_text(raw.get("image_prompt"), label="image prompt", limit=2_000, allow_blank=True),
        "alt_text": _safe_text(raw.get("alt_text"), label="alt text", limit=600, allow_blank=media_type == "NONE"),
    }
    for key in ("slides", "video_beats"):
        value = raw.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > MAX_ITEMS:
            raise workflow.WorkflowError(f"Media {key} must be a bounded list.")
        plan[key] = [_safe_text(item, label=key, limit=600) for item in value]

    slides = plan["slides"]
    beats = plan["video_beats"]
    assert isinstance(slides, list) and isinstance(beats, list)
    if media_type == "CAROUSEL_PDF" and not 4 <= len(slides) <= MAX_ITEMS:
        raise workflow.WorkflowError("Carousel media needs 4-8 concise slides.")
    if media_type == "VIDEO" and not 3 <= len(beats) <= MAX_ITEMS:
        raise workflow.WorkflowError("Video media needs 3-8 storyboard beats.")
    if media_type == "IMAGE" and not str(plan["image_prompt"]).strip():
        raise workflow.WorkflowError("Image media needs a concrete image prompt.")
    if media_type == "NONE" and (slides or beats or str(plan["image_prompt"]).strip()):
        raise workflow.WorkflowError("NONE media must not invent unused production assets.")
    return plan


def plan_media(post: str, topic: str, *, invoker=invoke_structured) -> dict[str, object]:
    task = f"""Choose the best supporting media for this already human-approved LinkedIn post.

The post text is locked. Do not rewrite it. Do not browse or add facts. Media should make the approved argument easier to understand, remember, or apply. It must not exist merely for decoration.

Choose exactly one:
- IMAGE: one strong visual idea is enough; use when a single metaphor, diagram, before/after, or annotated concept improves comprehension.
- CAROUSEL_PDF: use when the post contains a sequence, checklist, decision framework, 2-3 actions, or reusable artifact that benefits from 4-8 swipeable panels.
- VIDEO: use only when motion, demonstration, screen flow, or narrated progression materially improves the idea.
- NONE: use when media would add clutter, duplicate the post, or create fake authority.

Prefer CAROUSEL_PDF for practical frameworks/actions that can become an artifact. Prefer NONE over forcing media. Do not put unsupported claims or new evidence in the media. Keep slide text concise enough for a LinkedIn carousel. The visual must support one central argument.

TOPIC
{topic}

APPROVED_POST
{post}
"""
    raw = invoker(
        config=MODEL,
        role_prompt=(
            "You are a post-approval media director. Preserve the approved post's factual boundaries. "
            "Select media for comprehension and utility, not decoration or engagement bait."
        ),
        task_prompt=task,
        schema=_schema(),
        timeout=180,
        web_search=False,
        stage_label="Approved post media planner",
    )
    return validate_plan(raw)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    except FileExistsError as exc:
        raise workflow.WorkflowError("Media output already exists; use a new output directory.") from exc
    except OSError as exc:
        raise workflow.WorkflowError("Media output could not be written safely.") from exc


def _carousel_html(headline: str, slides: Sequence[str]) -> str:
    cards = []
    for index, slide in enumerate(slides, start=1):
        cards.append(
            '<section class="slide"><div class="count">%d / %d</div><h1>%s</h1><p>%s</p></section>'
            % (index, len(slides), html.escape(headline if index == 1 else ""), html.escape(slide))
        )
    return """<!doctype html><html><head><meta charset=\"utf-8\"><style>
@page { size: 1080px 1080px; margin: 0; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #fff; }
.slide { box-sizing: border-box; width: 1080px; height: 1080px; page-break-after: always; padding: 96px; display: flex; flex-direction: column; justify-content: center; }
.count { position: absolute; margin-top: -820px; font-size: 28px; opacity: .55; }
h1 { font-size: 64px; line-height: 1.05; margin: 0 0 48px; }
p { font-size: 48px; line-height: 1.22; margin: 0; white-space: pre-wrap; }
</style></head><body>%s</body></html>""" % "".join(cards)


def write_package(plan: Mapping[str, object], *, post: str, topic: str, output_dir: Path) -> Path:
    media_type = str(plan["media_type"])
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "human_approval_confirmed": True,
        "publishing_status": "DISABLED",
        "media_type": media_type,
        "topic": topic,
        "post_sha256": __import__("hashlib").sha256(post.encode()).hexdigest(),
        "render_status": "BRIEF_READY" if media_type in {"IMAGE", "VIDEO"} else "LOCAL_ASSET_READY" if media_type == "CAROUSEL_PDF" else "NOT_REQUIRED",
        "plan": dict(plan),
    }
    _write_private(output_dir / "media-plan.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if media_type == "IMAGE":
        _write_private(
            output_dir / "image-brief.md",
            f"# Image brief\n\n## Headline\n{plan['headline']}\n\n## Visual direction\n{plan['visual_direction']}\n\n## Generation prompt\n{plan['image_prompt']}\n\n## Alt text\n{plan['alt_text']}\n",
        )
    elif media_type == "CAROUSEL_PDF":
        slides = plan["slides"]
        assert isinstance(slides, list)
        markdown = ["# Carousel", "", f"## Headline\n{plan['headline']}", ""]
        for index, slide in enumerate(slides, start=1):
            markdown.extend([f"## Slide {index}", str(slide), ""])
        markdown.extend(["## Alt text", str(plan["alt_text"]), ""])
        _write_private(output_dir / "carousel.md", "\n".join(markdown))
        _write_private(output_dir / "carousel.html", _carousel_html(str(plan["headline"]), slides))
    elif media_type == "VIDEO":
        beats = plan["video_beats"]
        assert isinstance(beats, list)
        markdown = ["# Video storyboard", "", f"## Headline\n{plan['headline']}", "", f"## Visual direction\n{plan['visual_direction']}", ""]
        for index, beat in enumerate(beats, start=1):
            markdown.extend([f"## Beat {index}", str(beat), ""])
        markdown.extend(["## Alt text / transcript summary", str(plan["alt_text"]), ""])
        _write_private(output_dir / "video-storyboard.md", "\n".join(markdown))
    return output_dir


def _read_post(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or metadata.st_size > MAX_POST_BYTES:
            raise workflow.WorkflowError("Approved post file is unsafe or too large.")
        text = path.read_text(encoding="utf-8").strip()
    except workflow.WorkflowError:
        raise
    except OSError as exc:
        raise workflow.WorkflowError("Approved post file is unavailable.") from exc
    if not text:
        raise workflow.WorkflowError("Approved post file is blank.")
    return text


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="linkedin-os media", description="Create a private media package only after human post approval.")
    result.add_argument("--post-file", type=Path, required=True)
    result.add_argument("--topic", required=True)
    result.add_argument("--output-dir", type=Path)
    result.add_argument("--confirm-approved", action="store_true")
    result.add_argument("--allow-model-egress", action="store_true")
    return result


def command(args: argparse.Namespace) -> int:
    if not args.confirm_approved:
        raise workflow.WorkflowError("Media generation requires --confirm-approved after the human approves the final post.")
    if not args.allow_model_egress:
        raise workflow.WorkflowError("Media planning requires --allow-model-egress before the approved post reaches the model.")
    post = _read_post(args.post_file.expanduser().resolve())
    topic = " ".join(str(args.topic).split())
    if not topic:
        raise workflow.WorkflowError("Media planning requires a non-blank topic.")
    plan = plan_media(post, topic)
    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = DEFAULT_ROOT / stamp
    output_dir = output_dir.expanduser().resolve()
    try:
        output_dir.relative_to(workflow.REPO_ROOT)
    except ValueError:
        raise workflow.WorkflowError("Media output must remain inside the repository private runtime.") from None
    path = write_package(plan, post=post, topic=topic, output_dir=output_dir)
    print(f"Media type: {plan['media_type']}")
    print(f"Media package: {path.relative_to(workflow.REPO_ROOT).as_posix()}")
    print("Human approval was required before this stage. Publishing remains disabled.")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return command(parser().parse_args(argv))
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
