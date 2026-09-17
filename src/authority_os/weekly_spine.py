"""The owner's frozen publication calendar, resolved by posting date in India."""

from __future__ import annotations

import json
import hashlib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import workflow

CONFIG = workflow.REPO_ROOT / "config" / "weekly-spine.json"


def contract() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def plan(post_date: str | None = None, *, include_tuesday: bool = False) -> dict:
    spec = contract()
    day = date.fromisoformat(post_date) if post_date else datetime.now(ZoneInfo(spec["timezone"])).date()
    weekday = day.strftime("%A")
    route = spec["days"].get(weekday)
    active = route is not None and (not route["optional"] or include_tuesday)
    return {
        "post_date": day.isoformat(), "weekday": weekday, "timezone": spec["timezone"],
        "active": active, "style": route["style"] if route else None,
        "focus": route["focus"] if route else "No post planned.",
        "optional": bool(route and route["optional"]),
        "selection": spec["selection"], "runtime_target_minutes": spec["runtime_target_minutes"],
        "runtime_target_verified": False,
    }


def inventory_path(selected: dict) -> Path:
    scope = selected["style"]
    if selected.get("build"):
        scope += "-" + hashlib.sha256(selected["build"]["repo_url"].encode()).hexdigest()[:12]
    return workflow.DEFAULT_PRIVATE_DATA / "weekly-inventory" / f"{scope}.json"


def prepare(args: object) -> dict | None:
    # Older internal callers can still invoke the discovery primitive directly.
    # The public parser always supplies post_date and uses the frozen calendar.
    if not hasattr(args, "post_date"):
        return None
    resume = getattr(args, "resume_from", None)
    if resume:
        from . import daily_cli
        saved_path = daily_cli._under_private(Path(resume)) / "weekly-plan.json"
        if not saved_path.is_file():
            # Explicitly resuming an older run preserves its original input scope.
            args.post_style = getattr(args, "post_style", None) or "standard"
            return None
        saved = daily_cli._private_json(saved_path, "Saved weekly plan")
        if args.post_date and args.post_date != saved["post_date"]:
            raise workflow.WorkflowError("Resume preserves its original posting date; start a new run to change the day.")
        args.post_date = saved["post_date"]
        if saved["weekday"] == "Tuesday":
            args.include_tuesday = True
    selected = plan(args.post_date, include_tuesday=getattr(args, "include_tuesday", False))
    if not selected["active"]:
        print(f"NO_POST_PLANNED: {selected['post_date']} ({selected['weekday']})."
              + (" Add --include-tuesday to opt in." if selected["optional"] else ""))
        return selected
    supplied = getattr(args, "post_style", None)
    if supplied and supplied != selected["style"]:
        print(f"Frozen calendar selects {selected['style']}; --post-style {supplied} is superseded.")
    args.post_style = selected["style"]
    args.week_slot = None  # Legacy reach/authority/opportunity slots are not weekdays.
    focus = selected["focus"]
    if selected["weekday"] == "Wednesday":
        from . import daily_cli
        path = getattr(args, "build_manifest", None) or workflow.DEFAULT_PRIVATE_DATA / "latest-build.json"
        if not Path(path).is_file():
            raise workflow.WorkflowError(
                "Wednesday needs the completed build and a real video. Supply --build-manifest "
                "or data/private/latest-build.json with repo_url, summary, video_path and built_by_author=true."
            )
        build = daily_cli._private_json(Path(path), "Completed build")
        if not isinstance(build, dict) or build.get("built_by_author") is not True:
            raise workflow.WorkflowError("Wednesday build must be explicitly identified as the author's work.")
        if not isinstance(build.get("summary"), str) or not build["summary"].strip():
            raise workflow.WorkflowError("Wednesday build needs a factual summary of its demonstrated behaviour.")
        url = workflow.canonicalise_url(str(build.get("repo_url", "")))
        raw_video = build.get("video_path")
        if not isinstance(raw_video, str) or not raw_video.strip():
            raise workflow.WorkflowError("Wednesday build needs the actual video_path.")
        video = Path(raw_video).expanduser()
        if not video.is_absolute():
            video = workflow.REPO_ROOT / video
        if not video.is_file() or video.suffix.lower() not in {".mp4", ".mov", ".webm"} or video.stat().st_size == 0:
            raise workflow.WorkflowError("Wednesday video is missing or empty; a storyboard does not count as a recording.")
        selected["build"] = {"repo_url": url, "summary": build["summary"].strip(),
                             "video_path": str(video.resolve()), "ownership": "author-attested"}
        focus += f" Only feature our build at {url}. Demonstrated behaviour: {build['summary'].strip()}"
    selected["focus"] = focus
    args.weekly_focus = focus
    print(f"Frozen spine: {selected['post_date']} ({selected['weekday']}) — {selected['style']}.")
    return selected
