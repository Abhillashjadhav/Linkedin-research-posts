"""Private delivery files derived from a reviewed long-form article.

The package records machine-checkable provenance, not human approval or proof that
source text is true. Nothing here publishes content or invokes image generation.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import struct
import tempfile
import argparse
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

from . import article_contract, article_workflow
from .model_runtime import ModelConfig, invoke_structured
from .workflow import WorkflowError


COPY_SCHEMA: dict[str, object] = {
    "type": "object", "additionalProperties": False,
    "required": ["post", "first_comment"],
    "properties": {name: {
        "type": "object", "additionalProperties": False,
        "required": ["text", "claim_ids"],
        "properties": {"text": {"type": "string"}, "claim_ids": {
            "type": "array", "items": {"type": "string"}}},
    } for name in ("post", "first_comment")},
}
REVIEW_SCHEMA: dict[str, object] = {
    "type": "object", "additionalProperties": False,
    "required": ["covered_claim_ids", "source_ids", "missing_claim_ids",
                 "unreviewed_claim_ids", "factual_alignment", "notes"],
    "properties": {
        **{name: {"type": "array", "items": {"type": "string"}}
           for name in ("covered_claim_ids", "source_ids", "missing_claim_ids",
                        "unreviewed_claim_ids")},
        "factual_alignment": {"type": "boolean"}, "notes": {"type": "string"},
    },
}
OUTPUT_NAMES = ("article.md", "post.md", "source-comment.md", "sources.md",
                "article.html", "evaluation.json", "manifest.json", "final-package.md")
REPO_CTA = re.compile(
    r"\b(?:clone|fork|download|star|check\s+out|visit|grab)\b[^.!?\n]{0,65}"
    r"\b(?:github|repo(?:sitory)?)\b",
    re.IGNORECASE,
)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkflowError(f"Article package {label} must be an object.")
    return value


def _string(value: object, label: str, *, max_length: int = 100_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length or "\x00" in value:
        raise WorkflowError(f"Article package {label} must be nonempty safe text.")
    return value.strip()


def _ids(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", item) for item in value):
        raise WorkflowError(f"Article package {label} must contain valid IDs.")
    if len(value) != len(set(value)):
        raise WorkflowError(f"Article package {label} contains duplicate IDs.")
    return value


def _url(value: object, label: str) -> str:
    url = _string(value, label, max_length=2048)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or any(c.isspace() or ord(c) < 32 for c in url)
            or parsed.hostname.endswith(".") or "\\" in url):
        raise WorkflowError(f"Article package {label} must be a safe HTTPS URL.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise WorkflowError(f"Article package {label} has an invalid port.") from exc
    if port is not None and port != 443:
        raise WorkflowError(f"Article package {label} has an unsupported port.")
    return url


def _load(path: Path) -> tuple[dict[str, object], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise WorkflowError(f"Article package requires a regular, bounded {path.name}.")
    raw = path.read_bytes()
    try:
        return _object(json.loads(raw), path.name), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Article package {path.name} contains invalid JSON.") from exc


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reviewed_hash(article: dict[str, object], brief: dict[str, object], article_digest: str,
                   review: dict[str, object], manifest: dict[str, object]) -> str:
    """Accept the article contract's canonical hash in both review records."""
    if (manifest.get("contract_version") != article_contract.CONTRACT_VERSION
            or manifest.get("topic_id") != article["topic_id"]
            or any(manifest.get(key) != name for key, name in (
                ("article_file", "article.json"), ("review_file", "review.json"),
                ("claim_map_file", "article-claim-map.json")))):
        raise WorkflowError("Article manifest contract, topic or artifact names are incompatible.")
    if review.get("artifact_sha256") != article_digest or manifest.get("artifact_sha256") != article_digest:
        raise WorkflowError("Article review/manifest hash does not match the validated article.")
    narrative = _object(review.get("narrative"), "narrative review")
    factual = _object(review.get("factual"), "factual review")
    if narrative.get("artifact_sha256") != article_digest or factual.get("artifact_sha256") != article_digest:
        raise WorkflowError("Nested article review hash does not match the validated article.")
    statuses = [owner.get("status", owner.get("review_status")) for owner in (review, manifest)]
    if any(status != "READY_FOR_HUMAN_REVIEW" for status in statuses):
        if not all(status == "FIXTURE_ONLY" for status in statuses):
            raise WorkflowError("Article review and manifest have incompatible review statuses.")
    if (review.get("accepted") is True or review.get("human_approved") is True
            or manifest.get("human_approval_status") not in (None, "NOT_APPROVED")
            or manifest.get("publishing_status") not in (None, "DISABLED")):
        raise WorkflowError("Article package cannot record human approval.")
    if article.get("review_status") not in (None, *statuses):
        raise WorkflowError("Article content has incompatible review status.")
    if statuses[0] == "READY_FOR_HUMAN_REVIEW":
        if (not isinstance(manifest.get("model_config"), dict) or not manifest["model_config"]
                or type(manifest.get("review_rounds")) is not int
                or not 1 <= manifest["review_rounds"] <= 3):
            raise WorkflowError("Live article manifest lacks recorded model reviews.")
        if review.get("manual_fact_verification_required") is not True:
            raise WorkflowError("Article review lacks a passing narrative/factual judgment.")
        article_workflow.validate_review(narrative, "narrative_reviewer", article, brief)
        article_workflow.validate_review(factual, "factual_reviewer", article, brief)
        if narrative["verdict"] != "PASS" or factual["verdict"] != "PASS":
            raise WorkflowError("Article review lacks a passing narrative/factual judgment.")
        claim_by_id = {claim["id"]: claim for claim in brief["claims"]}
        for check in factual["claim_checks"]:
            if (claim_by_id[check["claim_id"]]["kind"] == "finding"
                    and not check["source_ids"]):
                raise WorkflowError("Article finding review requires a source reference.")
    elif manifest.get("model_config") != {} or manifest.get("review_rounds") != 0:
        raise WorkflowError("Fixture article must have no model invocation history.")
    return statuses[0]  # type: ignore[return-value]


def _dimensions(raw: bytes) -> tuple[str, int, int]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        if raw[12:16] != b"IHDR":
            raise WorkflowError("PNG asset lacks an IHDR header.")
        w, h = struct.unpack(">II", raw[16:24])
        kind = "image/png"
    elif raw.startswith(b"\xff\xd8"):
        pos = 2
        w = h = 0
        while pos + 4 <= len(raw):
            if raw[pos] != 0xFF:
                raise WorkflowError("Malformed JPEG marker sequence.")
            marker = raw[pos + 1]
            pos += 2
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                continue
            if marker in (0xD9, 0xDA):
                break
            length = int.from_bytes(raw[pos:pos + 2], "big")
            if length < 2 or pos + length > len(raw):
                raise WorkflowError("Malformed JPEG segment.")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if length < 7:
                    raise WorkflowError("Malformed JPEG dimensions.")
                h = int.from_bytes(raw[pos + 3:pos + 5], "big")
                w = int.from_bytes(raw[pos + 5:pos + 7], "big")
                break
            pos += length
        if not w or not h:
            raise WorkflowError("JPEG asset lacks readable dimensions.")
        kind = "image/jpeg"
    else:
        raise WorkflowError("Article assets must be PNG or JPEG image bytes.")
    if w <= 0 or h <= 0:
        raise WorkflowError("Article asset dimensions are invalid.")
    return kind, w, h


def _asset(path: Path, *, expected: tuple[int, int]) -> tuple[bytes, str]:
    if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents)
            or not path.is_file() or path.stat().st_size > 15_000_000):
        raise WorkflowError("Article asset must be a regular image under 15 MB.")
    raw = path.read_bytes()
    mime, w, h = _dimensions(raw)
    if (w, h) != expected:
        raise WorkflowError(f"Article asset dimensions must be {expected[0]}x{expected[1]}.")
    return raw, mime


def _atomic_write(path: Path, data: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=".article-package-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def package_reviewed_article(
    run_dir: str | Path, *, output_dir: str | Path | None = None,
    model_config: ModelConfig | None = None,
    invoker: Callable[..., dict[str, object]] = invoke_structured,
    live_consent: bool = False,
    assets: Mapping[str, str | Path] | None = None,
    article_url: str | None = None,
    required_asset_placements: Sequence[str] = ("cover",),
) -> dict[str, object]:
    """Create private copyable files; return evaluation, manifest and output paths.

    ``assets`` keys are ``cover`` or ``inline:<section-id>``. A cover is always
    required for full-package completion; callers may require inline placements.
    The fixture path never calls a model. Live generation requires consent/config.
    """
    root = Path(run_dir)
    private_root = (Path(__file__).resolve().parents[2] / "outputs").resolve()
    if (".." in root.parts or root.is_symlink() or not root.is_dir()
            or any(parent.is_symlink() for parent in root.parents)
            or not root.resolve().is_relative_to(private_root)
            or root.resolve() == private_root):
        raise WorkflowError("Article run must be a real directory inside the ignored outputs directory.")
    article, article_file_hash = _load(root / "article.json")
    brief, brief_hash = _load(root / "brief.json")
    review, review_hash = _load(root / "review.json")
    source_manifest, source_manifest_hash = _load(root / "manifest.json")
    claim_map, claim_map_file_hash = _load(root / "article-claim-map.json")
    brief = article_contract.validate_brief(brief)
    article = article_contract.validate_article(article, brief)
    article_hash = article_contract.article_hash(article, brief)
    review_status = _reviewed_hash(article, brief, article_hash, review, source_manifest)
    if (claim_map.get("artifact_sha256") != article_hash
            or claim_map.get("sections") != [
                {"section_id": section["id"], "claim_ids": section["claim_ids"]}
                for section in article["sections"]]
            or claim_map.get("claims") != brief["claims"]
            or claim_map.get("sources") != brief["sources"]
            or claim_map.get("author_attestations") != brief["author"]["attestations"]):
        raise WorkflowError("Article claim map does not match the reviewed article and brief.")
    fixture = review_status == "FIXTURE_ONLY"
    if not fixture and (live_consent is not True or model_config is None):
        raise WorkflowError("Live article companions require explicit model consent and configuration.")
    if article_url is not None:
        article_url = _url(article_url, "article URL")
    title = _string(article.get("title"), "title", max_length=500)
    thesis = _string(article.get("thesis"), "thesis")
    topic_id = _string(article.get("topic_id"), "topic ID", max_length=100)
    if brief.get("topic_id") != topic_id:
        raise WorkflowError("Article and brief topic IDs disagree.")
    sources = brief.get("sources")
    claims = brief.get("claims")
    sections = article.get("sections")
    if not isinstance(sources, list) or not isinstance(claims, list) or not isinstance(sections, list) or not sections:
        raise WorkflowError("Article requires brief sources/claims and nonempty sections.")
    source_by_id = {}
    for item in sources:
        source = _object(item, "source")
        sid = _string(source.get("id"), "source ID", max_length=100)
        if sid in source_by_id:
            raise WorkflowError("Duplicate source ID.")
        source_by_id[sid] = {"id": sid, "title": _string(source.get("title"), "source title"),
                             "url": _url(source.get("url"), "source URL")}
    claim_by_id = {}
    for item in claims:
        claim = _object(item, "claim")
        cid = _string(claim.get("id"), "claim ID", max_length=100)
        if cid in claim_by_id:
            raise WorkflowError("Duplicate claim ID.")
        references = _ids(claim.get("source_ids"), "claim source IDs")
        if set(references) - source_by_id.keys():
            raise WorkflowError("Claim references unknown sources.")
        claim_by_id[cid] = references
    section_ids = set()
    article_claim_ids: set[str] = set()
    validated_sections = []
    for item in sections:
        section = _object(item, "section")
        sid = _string(section.get("id"), "section ID", max_length=100)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", sid) or sid in section_ids:
            raise WorkflowError("Article section ID is unsafe or duplicated.")
        section_ids.add(sid)
        refs = _ids(section.get("claim_ids"), "section claim IDs")
        if set(refs) - claim_by_id.keys():
            raise WorkflowError("Article section references unknown claims.")
        article_claim_ids.update(refs)
        validated_sections.append((sid, _string(section.get("heading"), "section heading", max_length=500),
                                   _string(section.get("text"), "section text"), refs))
    rendered_article = article_contract.article_text(article, brief)
    if REPO_CTA.search(rendered_article):
        raise WorkflowError("Reviewed article contains an explicit repository call to action.")
    if not article_claim_ids:
        raise WorkflowError("Article has no sourced claims to package.")
    resource = brief.get("resource")
    resource_ledger = None
    if isinstance(resource, dict):
        resource_ledger = {"name": resource["name"], "url": _url(resource["url"], "resource URL"),
                           "source_ids": resource["source_ids"],
                           "claim_ids": resource.get("claim_ids", []),
                           "license": resource.get("license")}
        claim_kinds = {claim["id"]: claim["kind"] for claim in brief["claims"]}
        resource_ledger["eligible_claim_ids"] = sorted(
            cid for cid in resource_ledger["claim_ids"]
            if claim_kinds[cid] == "finding"
            and set(claim_by_id[cid]) & set(resource_ledger["source_ids"])
        )
    resource_only_claim_ids = (set(resource_ledger["eligible_claim_ids"]) - article_claim_ids
                               if resource_ledger is not None else set())
    allowed_companion_claim_ids = article_claim_ids | resource_only_claim_ids
    if (not isinstance(required_asset_placements, Sequence)
            or isinstance(required_asset_placements, (str, bytes))):
        raise WorkflowError("Required asset placements must be a sequence.")
    required_assets = {"cover"}
    for placement in required_asset_placements:
        if (not isinstance(placement, str) or
                (placement != "cover" and
                 (not placement.startswith("inline:") or placement[7:] not in section_ids))):
            raise WorkflowError("Required asset placement must name cover or an existing section.")
        required_assets.add(placement)
    asset_files = assets or {}
    if not isinstance(asset_files, Mapping):
        raise WorkflowError("Assets must map placements to local files.")
    image_data: dict[str, tuple[bytes, str]] = {}
    for key, value in asset_files.items():
        if key != "cover" and (not isinstance(key, str) or not key.startswith("inline:") or key[7:] not in section_ids):
            raise WorkflowError("Asset placement must be cover or an existing inline section ID.")
        if not isinstance(value, (str, Path)):
            raise WorkflowError("Asset path must be a local path.")
        path = Path(value)
        if ".." in path.parts:
            raise WorkflowError("Article asset paths cannot contain traversal segments.")
        image_data[key] = _asset(path, expected=(1920, 1080) if key == "cover" else (1200, 900))
    if fixture:
        first_claim = sorted(article_claim_ids)[0]
        copy: dict[str, object] = {
            "post": {"text": f"[SYNTHETIC FIXTURE — NOT FOR PUBLICATION] {title}: {thesis}", "claim_ids": [first_claim]},
            "first_comment": {"text": "[SYNTHETIC FIXTURE — NOT FOR PUBLICATION] Sources are listed in sources.md.", "claim_ids": [first_claim]},
        }
    else:
        context = {"article": article, "article_claim_ids": sorted(article_claim_ids),
                   "resource_companion_claim_ids": sorted(resource_only_claim_ids),
                   "claims": claims, "sources": sources,
                   "author_attestations": brief["author"]["attestations"],
                   "resource": resource_ledger, "article_url": article_url}
        copy = _object(invoker(
            config=model_config, role_prompt="Write a concise LinkedIn post and first source comment from the reviewed article. A supplied resource finding may be introduced in companion copy when supported by source content even if absent from the article. Attach IDs for every factual claim. Use the resource URL only when its eligible linked finding claim is cited. Never invent an article URL, license, proof, or source.",
            task_prompt=json.dumps(context, ensure_ascii=False, sort_keys=True),
            schema=COPY_SCHEMA, web_search=False, stage_label="Article companion copy",
        ), "model copy")
    copy_review = {}
    for name in ("post", "first_comment"):
        item = _object(copy.get(name), name)
        body = _string(item.get("text"), name + " text", max_length=20_000)
        ids = _ids(item.get("claim_ids"), name + " claim IDs")
        if not ids or set(ids) - allowed_companion_claim_ids:
            raise WorkflowError(f"{name} contains unsupported or missing companion claim IDs.")
        source_ids = sorted({sid for cid in ids for sid in claim_by_id[cid]})
        permitted_urls = {source_by_id[sid]["url"] for sid in source_ids}
        if article_url is not None:
            permitted_urls.add(article_url)
        if resource_ledger is not None and set(ids) & set(resource_ledger["eligible_claim_ids"]):
            permitted_urls.add(resource_ledger["url"])
        for match in re.findall(r"(?:https?://|www\.)[^\s)<>]+", body):
            if match.rstrip(".,") not in permitted_urls:
                raise WorkflowError(f"{name} contains a URL outside cited sources or the configured article URL.")
        if (resource_ledger is not None and resource_ledger["url"] in body
                and resource_ledger["license"] is None
                and re.search(r"\b(?:licensed under|MIT license|Apache license|GPL license|BSD license|CC[- ]BY license)\b",
                              body, re.IGNORECASE)):
            raise WorkflowError(f"{name} mentions a resource license that was not supplied.")
        body_hash = _hash(body.encode("utf-8"))
        if fixture:
            judgment = {"covered_claim_ids": ids, "source_ids": source_ids,
                        "missing_claim_ids": [], "unreviewed_claim_ids": [],
                        "factual_alignment": False, "notes": "Synthetic fixture; no factual model review."}
        else:
            judgment = _object(invoker(
                config=model_config,
                role_prompt="Independently assess factual alignment of this copy against the reviewed article, FULL supplied source content and author attestations. Companion-only resource findings are new to this copy: verify them independently against source content; do not inherit the article PASS or infer truth from IDs/URLs. Check license assertions against supplied evidence. Report missing or unreviewed claims. Return strict JSON.",
                task_prompt=json.dumps({"output": name, "text": body, "claim_ids": ids,
                                        "article": article, "article_claim_ids": sorted(article_claim_ids),
                                        "resource_companion_claim_ids": sorted(resource_only_claim_ids),
                                        "claims": claims, "sources": sources,
                                        "author_attestations": brief["author"]["attestations"],
                                        "resource": resource_ledger},
                                       ensure_ascii=False, sort_keys=True),
                schema=REVIEW_SCHEMA, web_search=False,
                stage_label=f"Article {name} factual review",
            ), name + " review")
        covered = _ids(judgment.get("covered_claim_ids"), name + " covered claims")
        cited = _ids(judgment.get("source_ids"), name + " review sources")
        missing = _ids(judgment.get("missing_claim_ids"), name + " missing claims")
        unreviewed = _ids(judgment.get("unreviewed_claim_ids"), name + " unreviewed claims")
        if (set(covered) - allowed_companion_claim_ids or set(cited) - source_by_id.keys()
                or set(missing) - allowed_companion_claim_ids or type(judgment.get("factual_alignment")) is not bool
                or not isinstance(judgment.get("notes"), str)):
            raise WorkflowError(f"{name} factual review is malformed.")
        used_resource_claims = sorted(set(ids) & resource_only_claim_ids)
        reviewed_resource_claims = sorted(set(covered) & set(used_resource_claims))
        copy_review[name] = {"text_sha256": body_hash, "article_sha256": article_hash,
                             "claim_ids": ids, "source_ids": source_ids,
                             "companion_only_resource_claim_ids": used_resource_claims,
                             "reviewed_resource_claim_ids": reviewed_resource_claims,
                             "covered_claim_ids": covered, "review_source_ids": cited,
                             "missing_claim_ids": missing, "unreviewed_claim_ids": unreviewed,
                             "factual_alignment": judgment["factual_alignment"],
                             "notes": judgment["notes"],
                             "eligible": not fixture and set(covered) == set(ids)
                             and set(cited) == set(source_ids) and not missing and not unreviewed
                             and judgment["factual_alignment"] is True}
        copy_review[name]["resource_claim_review_status"] = (
            "REVIEWED" if used_resource_claims and copy_review[name]["eligible"] else
            "NEEDS_REVIEW" if used_resource_claims else "NOT_USED")
        item["text"] = body
    status = "FIXTURE_ONLY" if fixture else ("READY_FOR_HUMAN_REVIEW" if all(
        row["eligible"] for row in copy_review.values()) else "NEEDS_REVIEW")
    missing_assets = sorted(required_assets - image_data.keys())
    package_status = "INCOMPLETE" if not image_data or missing_assets else (
        "COMPLETE_FOR_HUMAN_REVIEW" if status == "READY_FOR_HUMAN_REVIEW" else status)
    article_md = f"# {title}\n\n{brief['author']['byline']}\n\n" + "\n\n".join(
        f"## {heading}\n\n{text}" for _, heading, text, _ in validated_sections) + "\n"
    source_lines = ["# Sources", "", "Source IDs trace claims; links do not independently verify their contents.", ""]
    for sid, source in sorted(source_by_id.items()):
        source_lines.append(f"- {sid} — {source['title']}: {source['url']}")
    source_lines += ["", "## Claim mapping", ""]
    used_companion_claim_ids = {cid for row in copy_review.values() for cid in row["claim_ids"]}
    for cid in sorted(article_claim_ids | used_companion_claim_ids):
        source_lines.append(f"- {cid}: {', '.join(claim_by_id[cid])}")
    if resource_ledger is not None:
        source_lines.extend(["", "## Supplied resource", "",
                             f"- {resource_ledger['name']}: {resource_ledger['url']}",
                             f"- Linked claims: {', '.join(resource_ledger['claim_ids']) or '(none supplied)'}",
                             f"- Source IDs: {', '.join(resource_ledger['source_ids'])}"])
        if resource_ledger["license"] is not None:
            source_lines.append(f"- Supplied license: {resource_ledger['license']}")
    html_parts = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>",
                  html.escape(title), "</title></head><body><article><h1>", html.escape(title),
                  "</h1><p class=\"byline\">", html.escape(brief["author"]["byline"]), "</p>"]
    import base64
    # The cover remains outside the article body and is recorded in the ledger.
    for sid, heading, body, _ in validated_sections:
        html_parts.extend(["<section id=\"", html.escape(sid, quote=True), "\"><h2>",
                           html.escape(heading), "</h2>"])
        for paragraph in re.split(r"\n\s*\n", body):
            html_parts.extend(["<p>", html.escape(paragraph).replace("\n", "<br>"), "</p>"])
        if f"inline:{sid}" in image_data:
            raw, mime = image_data[f"inline:{sid}"]
            html_parts.extend(["<img alt=\"Editorial illustration\" src=\"data:", mime,
                               ";base64,", base64.b64encode(raw).decode("ascii"), "\">"])
        html_parts.append("</section>")
    html_parts.append("</article></body></html>\n")
    evaluation = {"status": status, "full_package_status": package_status,
                  "article_sha256": article_hash, "copy_reviews": copy_review,
                  "resource": resource_ledger,
                  "asset_plan": {"cover": "1920x1080", "inline": "1200x900 per section"},
                  "required_asset_placements": sorted(required_assets),
                  "missing_required_assets": missing_assets,
                  "provided_assets": {key: {"sha256": _hash(raw), "mime": mime}
                                      for key, (raw, mime) in image_data.items()},
                  "limitations": ["Source mapping is not semantic truth verification.",
                                  "Embedded image data URLs may not survive every clipboard/editor paste."]}
    files = {"article.md": article_md, "post.md": str(_object(copy["post"], "post")["text"]) + "\n",
             "source-comment.md": str(_object(copy["first_comment"], "first comment")["text"]) + "\n",
             "sources.md": "\n".join(source_lines) + "\n", "article.html": "".join(html_parts),
             "evaluation.json": json.dumps(evaluation, indent=2, sort_keys=True) + "\n"}
    payloads = {name: content.encode("utf-8") for name, content in files.items()}
    asset_names = {}
    for key, (raw, mime) in image_data.items():
        filename = ("cover" if key == "cover" else "inline-" + key[7:]) + (
            ".png" if mime == "image/png" else ".jpg")
        payloads[filename] = raw
        asset_names[key] = filename
    payloads["final-package.md"] = (f"# Article delivery — {title}\n\nArticle review: {status}. "
                                 f"Full package: {package_status}. Human review still required.\n\n"
                                 f"Missing required assets: {', '.join(missing_assets) if missing_assets else 'none'}.\n\n"
                                 "Files: article.md, post.md, source-comment.md, sources.md, article.html, "
                                 "evaluation.json, manifest.json.\n\n"
                                 "The cover is a separate upload; inline assets are embedded in article.html. "
                                 "Image placement is not proof of final rendering or paste compatibility.\n").encode()
    manifest = {"schema_version": 1, "managed_by": "authority_os.article_package", "topic_id": topic_id, "review_status": status,
                "full_package_status": package_status, "article_sha256": article_hash,
                "input_sha256": {"article.json": article_file_hash,
                                 "brief.json": brief_hash, "review.json": review_hash,
                                 "manifest.json": source_manifest_hash,
                                 "article-claim-map.json": claim_map_file_hash},
                "files_sha256": {name: _hash(content) for name, content in payloads.items()},
                "article_url": article_url, "human_approved": False,
                "required_asset_placements": sorted(required_assets),
                "missing_required_assets": missing_assets,
                "asset_placements": asset_names}
    payloads["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    destination = Path(output_dir) if output_dir is not None else root / "package"
    if (".." in destination.parts or destination.is_symlink()
            or any(parent.is_symlink() for parent in destination.parents)
            or not destination.resolve().is_relative_to(root.resolve())
            or destination.resolve() == root.resolve()):
        raise WorkflowError("Package output directory must be inside the ignored article run.")
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or any((destination / name).is_symlink() for name in payloads):
        raise WorkflowError("Package output cannot replace symbolic links.")
    present = [name for name in payloads if (destination / name).exists()]
    stale_assets: list[Path] = []
    if present or (destination / "manifest.json").exists():
        old_manifest = destination / "manifest.json"
        if not old_manifest.is_file():
            raise WorkflowError("Package output contains files not owned by the article packager.")
        try:
            previous = _object(json.loads(old_manifest.read_text()), "existing manifest")
        except json.JSONDecodeError as exc:
            raise WorkflowError("Existing package manifest is malformed.") from exc
        if previous.get("managed_by") != "authority_os.article_package":
            raise WorkflowError("Package output contains files not owned by the article packager.")
        previous_hashes = _object(previous.get("files_sha256"), "previous file hashes")
        for name, digest in previous_hashes.items():
            if (not isinstance(name, str) or not re.fullmatch(
                    r"(?:article\.md|post\.md|source-comment\.md|sources\.md|article\.html|evaluation\.json|final-package\.md|(?:cover|inline-[A-Za-z0-9_-]+)\.(?:png|jpg))", name)
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise WorkflowError("Existing package file ledger is malformed.")
            old = destination / name
            if old.is_symlink() or not old.is_file() or _hash(old.read_bytes()) != digest:
                raise WorkflowError("Existing package file changed since its manifest was written.")
        if not set(OUTPUT_NAMES) - {"manifest.json"} <= previous_hashes.keys():
            raise WorkflowError("Existing package file ledger is incomplete.")
        if any(name in present and name not in previous_hashes and name != "manifest.json" for name in present):
            raise WorkflowError("Package output contains an unowned file.")
        for old in _object(previous.get("asset_placements"), "previous asset placements").values():
            if not isinstance(old, str) or not re.fullmatch(r"(?:cover|inline-[A-Za-z0-9_-]+)\.(?:png|jpg)", old):
                raise WorkflowError("Existing package asset ledger is malformed.")
            if old not in payloads:
                file = destination / old
                if file.is_symlink() or (file.exists() and _hash(file.read_bytes()) != previous_hashes.get(old)):
                    raise WorkflowError("Existing package asset changed since its manifest was written.")
                stale_assets.append(file)
    for name, digest in (("article.json", article_file_hash), ("brief.json", brief_hash),
                         ("review.json", review_hash), ("manifest.json", source_manifest_hash),
                         ("article-claim-map.json", claim_map_file_hash)):
        if _hash((root / name).read_bytes()) != digest:
            raise WorkflowError("Article run changed during package generation.")
    for name, content in payloads.items():
        _atomic_write(destination / name, content)
    for old in stale_assets:
        old.unlink(missing_ok=True)
    return {"status": status, "full_package_status": package_status,
            "missing_required_assets": missing_assets,
            "output_dir": str(destination), "manifest": manifest, "evaluation": evaluation,
            "files": {name: str(destination / name) for name in payloads}}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point called by the installed command routing layer."""
    parser = argparse.ArgumentParser(prog="article-package")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--allow-model-egress", action="store_true")
    parser.add_argument("--assets", type=Path, help="JSON file mapping cover/inline:<section-id> to local images")
    parser.add_argument("--require-asset", action="append", default=[],
                        help="Additional required asset placement; cover is always required")
    parser.add_argument("--article-url")
    args = parser.parse_args(argv)
    config = None
    if args.model_config is not None:
        raw = _object(json.loads(args.model_config.read_text(encoding="utf-8")), "model config")
        config = ModelConfig(**raw).validate()
    assets = None
    if args.assets is not None:
        assets = _object(json.loads(args.assets.read_text(encoding="utf-8")), "assets")
    result = package_reviewed_article(args.run, output_dir=args.output, model_config=config,
                                      live_consent=args.allow_model_egress, assets=assets,
                                      article_url=args.article_url,
                                      required_asset_placements=("cover", *args.require_asset))
    print(json.dumps({"status": result["status"], "full_package_status": result["full_package_status"],
                      "missing_required_assets": result["missing_required_assets"],
                      "output_dir": result["output_dir"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
