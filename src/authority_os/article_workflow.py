"""Private Sunday article drafting with bounded, independently checked revisions."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Mapping

from .article_contract import article_hash, article_text, validate_article, validate_brief
from .model_runtime import ModelConfig, invoke_structured
from .workflow import WorkflowError

ROLES = ("writer", "narrative_reviewer", "factual_reviewer", "section_editor")
VERDICTS = frozenset({"PASS", "FAIL", "BLOCKED"})
STATUSES = frozenset({"SUPPORTED", "UNSUPPORTED", "UNCERTAIN"})


def _object(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


SECTION = _object({"id": {"type": "string"}, "heading": {"type": "string"},
                   "text": {"type": "string"}, "claim_ids": {"type": "array", "items": {"type": "string"}}},
                  ["id", "heading", "text", "claim_ids"])
ARTICLE = _object({"topic_id": {"type": "string"}, "thesis": {"type": "string"},
                   "title": {"type": "string"}, "sections": {"type": "array", "items": SECTION}},
                  ["topic_id", "thesis", "title", "sections"])
FINDING = _object({"section_id": {"type": "string"}, "code": {"type": "string"},
                   "message": {"type": "string"}, "severity": {"type": "string", "enum": ["blocking", "advisory"]}},
                  ["section_id", "code", "message", "severity"])
CHECK = _object({"claim_id": {"type": "string"}, "status": {"type": "string", "enum": sorted(STATUSES)},
                 "source_ids": {"type": "array", "items": {"type": "string"}}, "message": {"type": "string"}},
                ["claim_id", "status", "source_ids", "message"])
REVIEW_BASE = {"artifact_sha256": {"type": "string"}, "verdict": {"type": "string", "enum": sorted(VERDICTS)},
               "findings": {"type": "array", "items": FINDING}}
SCHEMAS = {
    "writer": ARTICLE,
    "narrative_reviewer": _object(REVIEW_BASE, list(REVIEW_BASE)),
    "factual_reviewer": _object({**REVIEW_BASE, "claim_checks": {"type": "array", "items": CHECK}},
                                [*REVIEW_BASE, "claim_checks"]),
    "section_editor": _object({"artifact_sha256": {"type": "string"},
                               "edits": {"type": "array", "items": SECTION}},
                              ["artifact_sha256", "edits"]),
}
_ROLE_FILES = {
    "writer": ("article_writer.md",),
    "narrative_reviewer": ("article_narrative_reviewer.md",),
    "factual_reviewer": ("article_factual_reviewer.md",),
    "section_editor": ("article_writer.md", "article_narrative_reviewer.md"),
}


def _role_profile(role: str) -> str:
    """Load only checked-in Sunday instructions, never paths from a brief."""
    if role not in _ROLE_FILES:
        raise WorkflowError("Unknown Sunday article role.")
    directory = Path(__file__).resolve().parents[2] / ".claude" / "agents"
    profiles = []
    for name in _ROLE_FILES[role]:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise WorkflowError(f"Sunday article role profile is unavailable: {name}.")
        try:
            profile = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise WorkflowError(f"Sunday article role profile cannot be read: {name}.") from exc
        if not profile.strip() or len(profile) > 20_000:
            raise WorkflowError(f"Sunday article role profile is invalid: {name}.")
        profiles.append(profile.strip())
    return "\n\n".join(profiles)


def load_models(raw: object) -> dict[str, ModelConfig]:
    """Require an explicit Codex configuration for every article stage."""
    if not isinstance(raw, dict) or set(raw) != set(ROLES):
        raise WorkflowError("Article models require exactly writer, narrative_reviewer, factual_reviewer, section_editor.")
    configs = {}
    for role in ROLES:
        value = raw[role]
        if not isinstance(value, dict) or set(value) != {"runtime", "model", "reasoning"}:
            raise WorkflowError(f"Invalid article model configuration: {role}.")
        if any(not isinstance(value[key], str) for key in value):
            raise WorkflowError(f"Invalid article model configuration: {role}.")
        configs[role] = ModelConfig(**value).validate()
    return configs


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_review(raw: object, role: str, article: dict, brief: dict) -> dict:
    """Reject malformed, stale, unknown and incomplete model reviews locally."""
    if role not in {"narrative_reviewer", "factual_reviewer"}:
        raise WorkflowError("Unknown article review role.")
    expected = {"artifact_sha256", "verdict", "findings"}
    if role == "factual_reviewer":
        expected.add("claim_checks")
    if not isinstance(raw, dict) or set(raw) != expected:
        raise WorkflowError(f"Malformed {role} review.")
    if raw["artifact_sha256"] != article_hash(article, brief) or not isinstance(raw["verdict"], str) or raw["verdict"] not in VERDICTS:
        raise WorkflowError(f"Stale hash or invalid verdict in {role} review.")
    section_ids = {section["id"] for section in article["sections"]}
    if not isinstance(raw["findings"], list):
        raise WorkflowError(f"Malformed {role} findings.")
    for finding in raw["findings"]:
        if (not isinstance(finding, dict) or set(finding) != {"section_id", "code", "message", "severity"}
                or not isinstance(finding["section_id"], str) or finding["section_id"] not in section_ids or not _nonblank(finding["code"])
                or not _nonblank(finding["message"]) or not isinstance(finding["severity"], str)
                or finding["severity"] not in {"blocking", "advisory"}):
            raise WorkflowError(f"Unknown section or malformed finding in {role} review.")
    if raw["verdict"] == "PASS" and any(f["severity"] == "blocking" for f in raw["findings"]):
        raise WorkflowError(f"Contradictory {role} review.")
    if role == "factual_reviewer":
        checks = raw["claim_checks"]
        used = {cid for section in article["sections"] for cid in section["claim_ids"]}
        claim_by_id = {claim["id"]: claim for claim in brief["claims"]}
        if not isinstance(checks, list) or len(checks) != len(used):
            raise WorkflowError("Factual review must cover every used claim exactly once.")
        seen = set()
        for check in checks:
            if (not isinstance(check, dict) or set(check) != {"claim_id", "status", "source_ids", "message"}
                    or not isinstance(check["claim_id"], str) or check["claim_id"] not in used or check["claim_id"] in seen
                    or not isinstance(check["status"], str) or check["status"] not in STATUSES or not _nonblank(check["message"])
                    or not isinstance(check["source_ids"], list)
                    or any(not isinstance(s, str) for s in check["source_ids"])
                    or len(set(check["source_ids"])) != len(check["source_ids"])
                    or not set(check["source_ids"]).issubset(set(claim_by_id[check["claim_id"]]["source_ids"]))
                    or (claim_by_id[check["claim_id"]]["kind"] == "finding" and
                        check["status"] == "SUPPORTED" and not check["source_ids"])):
                raise WorkflowError("Factual review has missing, duplicate, or unsupported claim/source mapping.")
            seen.add(check["claim_id"])
        if raw["verdict"] == "PASS" and any(c["status"] != "SUPPORTED" for c in checks):
            raise WorkflowError("Factual PASS contradicts claim checks.")
    return raw


def _blocked_sections(reviews: list[dict]) -> set[str]:
    return {finding["section_id"] for review in reviews for finding in review["findings"]
            if finding["severity"] == "blocking"}


def apply_edits(raw: object, article: dict, brief: dict, blocked: set[str]) -> dict:
    """Apply only replacements for previously blocked section IDs."""
    if (not isinstance(raw, dict) or set(raw) != {"artifact_sha256", "edits"}
            or raw["artifact_sha256"] != article_hash(article, brief)
            or not isinstance(raw["edits"], list) or not raw["edits"]):
        raise WorkflowError("Section editor returned malformed or stale edits.")
    ids = [edit.get("id") for edit in raw["edits"] if isinstance(edit, dict)]
    if len(ids) != len(raw["edits"]) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or not set(ids).issubset(blocked):
        raise WorkflowError("Section editor changed an unblocked or unknown section.")
    amended = deepcopy(article)
    lookup = {edit["id"]: edit for edit in raw["edits"]}
    for index, section in enumerate(amended["sections"]):
        if section["id"] in lookup:
            edit = lookup[section["id"]]
            if set(edit) != {"id", "heading", "text", "claim_ids"} or edit["heading"] != section["heading"]:
                raise WorkflowError("Section editor changed a heading or returned an invalid section.")
            amended["sections"][index] = edit
    amended = validate_article(amended, brief)
    if article_hash(amended, brief) == article_hash(article, brief):
        raise WorkflowError("Section editor made no change.")
    return amended


def _write(path: Path, payload: object, *, raw: bool = False) -> None:
    data = (str(payload) if raw else json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _create_run(output_dir: Path) -> Path:
    root = Path(__file__).resolve().parents[2]
    permitted = (root / "outputs").resolve()
    output = output_dir.expanduser().absolute()
    if output.is_symlink() or not output.is_relative_to(permitted) or output == permitted:
        raise WorkflowError("Article output must be a new folder under the repository outputs directory.")
    # Disallow symlink traversal including ancestors: private output must not escape.
    if any(parent.is_symlink() for parent in (output, *output.parents) if parent.is_relative_to(permitted)):
        raise WorkflowError("Article output path traverses a symlink.")
    if not output.resolve().is_relative_to(permitted) or output.resolve() == permitted:
        raise WorkflowError("Article output path escapes the private outputs directory.")
    try:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        output.chmod(0o700)
    except FileExistsError:
        raise WorkflowError("Article output directory already exists.") from None
    return output


def _call(role: str, models: Mapping[str, ModelConfig], brief: dict, payload: dict) -> dict:
    instructions = {
        "writer": "Write exactly one original long-form article for the supplied brief. Use only supplied sources, claims, author attestations and voice examples; do not invent experience or evidence. Map every factual assertion to claim IDs. Preserve topic ID and thesis and locked title. Return the structured article.",
        "narrative_reviewer": "Independently assess coherence, reader value, structure, voice and word range. Bind the review to the exact artifact SHA-256. Put a blocking finding on the relevant section for every necessary edit; do not infer human approval.",
        "factual_reviewer": "Independently inspect every sentence for uncited factual assertions, including when no claim IDs are used. Report a blocking finding on the relevant section for any unsupported assertion. Return one claim check per used claim (an empty list only when no IDs are used), with only its approved source IDs. Empty coverage alone is not evidence of factual alignment or a reason to PASS. Unsupported or uncertain claims prevent PASS. Bind to the exact artifact SHA-256. This model review does not certify facts; human verification remains required.",
        "section_editor": "Return replacements ONLY for blocked section IDs, preserving ID and heading and all unrelated sections. Use only brief evidence. Keep topic, thesis and title fixed. Target the reported findings; no whole-article regeneration. Bind edits to the exact artifact SHA-256.",
    }
    response = invoke_structured(config=models[role], role_prompt=_role_profile(role) + "\n\n" + instructions[role],
                                 task_prompt=json.dumps({"brief": brief, **payload}, sort_keys=True),
                                 schema=SCHEMAS[role], web_search=False, stage_label=f"Sunday article {role}")
    if not isinstance(response, dict):
        raise WorkflowError(f"Article {role} returned an invalid object.")
    return response


def run(brief_input: object, models: Mapping[str, ModelConfig], output_dir: Path) -> dict:
    """Draft, review and optionally edit; persist each completed stage, including failures."""
    brief = validate_brief(brief_input)
    if set(models) != set(ROLES) or any(not isinstance(m, ModelConfig) for m in models.values()):
        raise WorkflowError("Article model assignments are incomplete.")
    for model in models.values():
        model.validate()
    folder = _create_run(Path(output_dir))
    trace: dict = {"stages": [], "status": "RUNNING", "publication_status": "DISABLED"}
    manifest: dict = {"contract_version": "sunday-article-v1", "topic_id": brief["topic_id"],
                      "status": "RUNNING", "human_approval_status": "NOT_APPROVED",
                      "publishing_status": "DISABLED", "model_config": {r: models[r].trace() for r in ROLES},
                      "artifact_sha256": None, "review_rounds": 0}
    _write(folder / "brief.json", brief)
    try:
        article = validate_article(_call("writer", models, brief, {}), brief)
        _write(folder / "article-initial.json", article)
        trace["stages"].append({"stage": "writer", "artifact_sha256": article_hash(article, brief)})
        reviews = []
        for round_index in range(3):
            digest = article_hash(article, brief)
            reviews = []
            for role in ("narrative_reviewer", "factual_reviewer"):
                review = validate_review(_call(role, models, brief, {"article": article, "artifact_sha256": digest}), role, article, brief)
                reviews.append(review)
                _write(folder / f"{role}-round-{round_index}.json", review)
                trace["stages"].append({"stage": role, "round": round_index, "artifact_sha256": digest,
                                        "verdict": review["verdict"]})
            manifest["review_rounds"] = round_index + 1
            blocked = _blocked_sections(reviews)
            if all(r["verdict"] == "PASS" for r in reviews):
                break
            if round_index == 2 or not blocked:
                break
            edited = apply_edits(_call("section_editor", models, brief,
                                       {"article": article, "artifact_sha256": digest,
                                        "blocked_section_ids": sorted(blocked), "reviews": reviews}),
                                 article, brief, blocked)
            article = edited
            _write(folder / f"article-edit-{round_index + 1}.json", article)
            trace["stages"].append({"stage": "section_editor", "round": round_index + 1,
                                    "artifact_sha256": article_hash(article, brief)})
        digest = article_hash(article, brief)
        eligible = all(review["verdict"] == "PASS" for review in reviews)
        word_count = sum(len(re.findall(r"\b[\w]+(?:['’\-][\w]+)*\b", s["text"]))
                         for s in article["sections"])
        low, high = brief["word_range"]["min"], brief["word_range"]["max"]
        if not low <= word_count <= high:
            eligible = False
        status = "READY_FOR_HUMAN_REVIEW" if eligible else "BLOCKED"
        mapping = {"artifact_sha256": digest, "sections": [
            {"section_id": section["id"], "claim_ids": section["claim_ids"]} for section in article["sections"]],
                   "claims": brief["claims"], "sources": brief["sources"],
                   "author_attestations": brief["author"]["attestations"]}
        _write(folder / "article.json", article)
        _write(folder / "article.md", article_text(article, brief) + "\n", raw=True)
        _write(folder / "article-claim-map.json", mapping)
        _write(folder / "review.json", {"artifact_sha256": digest, "narrative": reviews[0],
                                         "factual": reviews[1], "word_count": word_count,
                                         "word_range": brief["word_range"], "status": status,
                                         "manual_fact_verification_required": True})
        manifest.update(status=status, artifact_sha256=digest, article_file="article.json",
                        review_file="review.json", claim_map_file="article-claim-map.json")
        trace["status"] = status
        return manifest
    except BaseException as exc:
        manifest["status"] = "BLOCKED"
        trace["status"] = "BLOCKED"
        trace["error"] = str(exc) if isinstance(exc, WorkflowError) else type(exc).__name__
        raise
    finally:
        _write(folder / "trace.json", trace)
        _write(folder / "manifest.json", manifest)


def fixture(output_dir: Path) -> dict:
    """Persist a synthetic, explicitly ineligible package without reading input or invoking models."""
    brief = validate_brief({
        "contract_version": "sunday-article-v1", "topic_id": "fixture-sunday-article",
        "topic": "Synthetic article workflow", "reader": {"audience": "Fixture reader", "stake": "Fixture stakes",
        "desired_outcome": "Inspect offline wiring"}, "thesis": "A fixture only demonstrates file routing.",
        "technical_concept": "Synthetic claim mapping", "worked_example": "An invented offline example",
        "author": {"name": "Fixture Author", "byline": "Synthetic test only", "attestations": []},
        "sources": [{"id": "fixture-source", "url": "https://example.com/fixture-only",
                     "title": "Synthetic fixture", "content": "Synthetic content; not evidence."}],
        "claims": [{"id": "fixture-claim", "text": "This is synthetic fixture prose.",
                    "kind": "finding", "source_ids": ["fixture-source"]}],
        "word_range": {"min": 8, "max": 50},
    })
    article = validate_article({"topic_id": brief["topic_id"], "thesis": brief["thesis"],
                                "title": "Offline fixture article", "sections": [{"id": "fixture-section",
                                "heading": "Fixture section", "text": "This synthetic section exercises private artifact wiring only. It is never eligible for publication.",
                                "claim_ids": ["fixture-claim"]}]}, brief)
    digest = article_hash(article, brief)
    folder = _create_run(Path(output_dir))
    review = {"artifact_sha256": digest, "narrative": {"artifact_sha256": digest, "verdict": "BLOCKED",
              "findings": [{"section_id": "fixture-section", "code": "FIXTURE_ONLY", "message": "No model review was run.",
                            "severity": "blocking"}]},
              "factual": {"artifact_sha256": digest, "verdict": "BLOCKED", "findings": [{"section_id": "fixture-section",
              "code": "FIXTURE_ONLY", "message": "No evidence was verified.", "severity": "blocking"}],
              "claim_checks": [{"claim_id": "fixture-claim", "status": "UNCERTAIN", "source_ids": ["fixture-source"],
                                "message": "Synthetic fixture has no verified claim."}]},
              "word_count": 14, "word_range": brief["word_range"], "status": "FIXTURE_ONLY",
              "manual_fact_verification_required": True}
    manifest = {"contract_version": "sunday-article-v1", "topic_id": brief["topic_id"],
                "status": "FIXTURE_ONLY", "human_approval_status": "NOT_APPROVED",
                "publishing_status": "DISABLED", "model_config": {}, "artifact_sha256": digest,
                "review_rounds": 0, "article_file": "article.json", "review_file": "review.json",
                "claim_map_file": "article-claim-map.json"}
    _write(folder / "brief.json", brief)
    _write(folder / "article.json", article)
    _write(folder / "article.md", article_text(article, brief) + "\n", raw=True)
    _write(folder / "article-claim-map.json", {"artifact_sha256": digest,
            "sections": [{"section_id": "fixture-section", "claim_ids": ["fixture-claim"]}],
            "claims": brief["claims"], "sources": brief["sources"], "author_attestations": []})
    _write(folder / "review.json", review)
    _write(folder / "trace.json", {"status": "FIXTURE_ONLY", "stages": [], "publication_status": "DISABLED",
                                    "model_calls": 0})
    _write(folder / "manifest.json", manifest)
    return manifest
