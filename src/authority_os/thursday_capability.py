"""Shared editorial contract for Thursday's capability-discovery lane.

Routing is explicit: the four-post weekly planner calls Thursday slot 3,
whereas five-day campaigns identify it by day. Never infer a lane from source
text, source metadata, or a topic mentioning Thursday.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from urllib.parse import urlsplit

POLICY_VERSION = "thursday-capability-v1"


def is_thursday(
    *,
    brief: Mapping[str, object] | None = None,
    day: str | None = None,
    week_slot: int | None = None,
) -> bool:
    """Named campaign day wins over the different weekly-slot numbering."""
    context = brief or {}
    named_day = day if day is not None else context.get("day")
    if isinstance(named_day, str) and named_day.strip():
        return named_day.strip().casefold() == "thursday"
    slot = week_slot if week_slot is not None else context.get("weekly_slot")
    if slot is not None:
        return type(slot) is int and slot == 3
    return context.get("editorial_workflow") == POLICY_VERSION


_GUIDANCE = {
    "discovery": """
THURSDAY CAPABILITY DISCOVERY
Find a surprising, usable AI capability that gives the reader a concrete benefit.
Thursday is capability-first. Incident, outage, and warning stories belong in
their own lane. Do not make agent skills, prompt packs, or courses the primary
Thursday capability. Include independent builders and small teams alongside labs.
Search GitHub releases/trending, Show HN, Hugging Face, official release notes,
and original demos. Discovery pages are leads; inspect primary evidence before
making factual claims. Compare plausible candidates, including a final 48-hour
freshness sweep. Default to a seven-day lookback. Record first usable release,
substantive update, and article dates separately; an old tool needs a documented
new capability or explicit freshness exception. A shallow clone does not prove
the first commit date. Do not silently widen the window to fill a slot.
For each candidate capture primary URLs, runnable artifact/repository if relevant,
demo URL, supported benefit, mechanism, hardware/cost/version/test conditions,
limitations, and what the video can actually show. Distinguish source-reported
results from independently reproduced results; a compelling demo is not a benchmark.
Record attention as observed count + metric + source + observation time, or null
when unknown. Prefer independent corroboration; stars, reposts, and trending rank
are different signals. Do not infer virality, causality, or audience response.
Choose by supported surprise, reader usefulness, freshness, mechanism clarity,
reproducibility, demo quality, and evidenced attention, not a familiar brand alone.
""",
    "writer": """
THURSDAY CAPABILITY WRITING
Open with the concrete capability and reader benefit in the first two lines.
Use a striking number only when evidence supports it with matching conditions;
otherwise use a specific qualitative capability. Never substitute XX placeholders
or manufacture a result, personal test, cost saving, comparison, or audience reaction.
Develop a clear benefit, a concrete demonstrated example, the useful mechanism,
and the main practical condition or limitation. Let supported surprise carry the
energy; avoid generic hype and do not force an incident or failure narrative.
Keep the post readable; put deeper mechanism, sources, and test conditions in the
first comment/video. A link promise must resolve to a real supplied link. Do not
say a video is attached when only a storyboard exists. Credit the original creator.
Preserve the author's established voice and explicit edits over score chasing.
Use capital I naturally; do not impose lowercase-only or punctuation rituals.
Historical examples teach structure, not reusable current facts or numeric claims.
""",
    "comment": """
THURSDAY FIRST COMMENT
Write a usable companion comment, not just a list of links. Credit the creator;
include the verified original source/repository when relevant and original demo
when promised. Explain the mechanism plainly, then hardware/version/test
conditions, the main limitation, and a practical way for the reader to evaluate it.
Match the source precisely (for example, 'all' and 'remaining' are not interchangeable).
Label source-reported results and disclose whether the author actually reproduced
them. For comparisons evaluate task correctness, time, and cost where evidence
exists; blind indistinguishability alone does not establish any of those outcomes.
If a promised artifact or URL is missing, remove the promise or mark the package
incomplete. Never invent a URL or silently replace it with a different resource.
""",
    "video": """
THURSDAY VIDEO HANDOFF
Start with a real demonstration of the capability, then explain its mechanism
on one coherent visual canvas with purposeful camera movement and brief captions.
Use the user's supplied visual references when available; do not replace this
with a slide deck of abstract claims. Tie each shot/caption to its source and
separate recorded output from illustrative animation. Label illustrative routing,
memory splits, or timings; never imply a simulated diagram is a measured trace.
Provide an actionable shot list, asset/source ledger, narration or caption script,
timing, dimensions, and production requirements. Credit sources and use the author's
watermark where supplied. Carry the original conditions and limitations into captions.
A VIDEO_PLAN is a production handoff, not a rendered video. Only mark an MP4
complete after rendering, playback, visual/claim review, and file verification.
Keep missing source footage, runtime, and render dependencies visible. Package
the post, first comment, and actual video or clearly labelled pending handoff together.
""",
    "review": """
THURSDAY CAPABILITY REVIEW
Check the hook against the primary evidence and matching conditions; validate
release/update dates, capability fit, runnable/demo evidence, claim provenance,
limitations, attention observations, and all promised links/assets. Missing metrics
stay unknown. Do not call a candidate viral or guarantee reach without evidence.
Review the post and comment as one factual package. Review video captions against
the source, and distinguish illustrative scenes from real output. Do not mark a
storyboard as a finished media deliverable. Apply the current installed rubric and
acceptance policy; historical 50-point scoring is not the active contract. An author-
approved rewrite takes precedence over cosmetic score optimization. A high critic
score is an editorial signal, not a prediction of engagement or audience approval.
""",
}


def guidance(stage: str) -> str:
    """Return one bounded stage contract; reject typos rather than omit policy."""
    try:
        return f"[{POLICY_VERSION}]\n{_GUIDANCE[stage].strip()}"
    except KeyError as exc:
        raise ValueError(f"Unknown Thursday workflow stage: {stage}") from exc


CAPSULE_MARKER = "\nTHURSDAY_CAPABILITY_EVIDENCE_JSON\n"


def evidence_schema() -> dict[str, object]:
    """Structured factual handoff, separate from routing and editorial instructions."""
    nullable_text = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    properties = {key: {"type": "string"} for key in (
        "creator", "capability", "reader_benefit", "mechanism", "change_evidence",
        "limitation", "conditions", "demo_observation", "attention_evidence",
    )}
    properties.update({key: nullable_text for key in (
        "original_release_date", "substantive_change_date", "primary_url",
        "executable_url", "demo_url", "attention_url", "attention_observed_at", "attention_metric",
    )})
    properties["kind"] = {"type": "string", "enum": ["EXECUTABLE_CAPABILITY", "INCIDENT", "SKILL_LIST", "PROMPT_PACK", "OTHER"]}
    properties["change_kind"] = {"type": "string", "enum": ["RELEASE", "SUBSTANTIVE_UPDATE", "NONE"]}
    properties["result_provenance"] = {"type": "string", "enum": ["SOURCE_REPORTED", "INDEPENDENTLY_REPRODUCED"]}
    properties["attention_count"] = {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def validate_evidence(obj: object) -> dict[str, object]:
    """Validate schema, not truth or Thursday eligibility; evidence stays untrusted."""
    properties = evidence_schema()["properties"]
    if not isinstance(obj, Mapping) or set(obj) != set(properties):
        raise ValueError("Thursday capability evidence has an invalid schema.")
    result = dict(obj)
    for key, schema in properties.items():
        value = result[key]
        if key == "attention_count":
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("Thursday attention count must be non-negative or null.")
        elif "enum" in schema:
            if value not in schema["enum"]:
                raise ValueError(f"Thursday evidence has an invalid {key}.")
        elif value is None and "anyOf" in schema:
            continue
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"Thursday evidence needs {key} or a permitted null.")
        if isinstance(value, str) and (len(value) > 4000 or any(ord(char) < 32 and char not in "\n\t" for char in value)):
            raise ValueError(f"Thursday evidence {key} exceeds text limits or has control characters.")
        if key.endswith("_url") and value is not None:
            from . import workflow
            parsed = urlsplit(str(value))
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or len(value) > 2048 or any(char.isspace() for char in value):
                raise ValueError(f"Thursday evidence has an invalid public {key}.")
            workflow.canonicalise_url(value)
    if result["attention_count"] is not None and not all(result[key] for key in ("attention_url", "attention_observed_at", "attention_metric")):
        raise ValueError("Thursday numeric attention requires its metric, public URL and observation time.")
    return result


def extract_evidence(body: object) -> dict[str, object] | None:
    """Recover factual metadata before body truncation; never use it to choose a lane."""
    if not isinstance(body, str) or CAPSULE_MARKER not in body:
        return None
    try:
        capsule = json.loads(body.rsplit(CAPSULE_MARKER, 1)[1])
        if not isinstance(capsule, Mapping) or set(capsule) != {"policy_version", "evidence"} or capsule["policy_version"] != POLICY_VERSION:
            return None
        return validate_evidence(capsule["evidence"])
    except (ValueError, TypeError):
        return None
