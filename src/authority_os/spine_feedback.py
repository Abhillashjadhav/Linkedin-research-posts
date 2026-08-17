"""Private, observation-only performance records for narrative-spine experiments."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from . import workflow


CONTENT_SPINES = (
    "counterposition",
    "failure_reversal",
    "research_discovery",
    "operator_tradeoff",
    "unresolved_tension",
)
ATTENTION_SOURCES = ("x", "web", "x_and_web", "curated", "other")
OPTIONAL_METRICS = (
    "qualified_comments",
    "reposts",
    "saves",
    "profile_visits",
    "relevant_followers",
)
IMMUTABLE_CONTEXT_FIELDS = (
    "post_id",
    "published_at",
    "weekday",
    "topic",
    "attention_source",
    "selected_spine",
    "is_breakout_outlier",
)
RECORD_FIELDS = frozenset(
    {
        "post_url",
        "post_id",
        "published_at",
        "weekday",
        "topic",
        "attention_source",
        "selected_spine",
        "impressions",
        "engagements",
        *OPTIONAL_METRICS,
        "is_breakout_outlier",
        "observed_at",
        "recorded_at",
    }
)
DEFAULT_FEEDBACK_FILE = workflow.DEFAULT_PRIVATE_DATA / "spine-performance.jsonl"
MAX_FILE_BYTES = 5_000_000
MAX_RECORDS = 5_000
MIN_COMPARABLE_SAMPLE = 5
LINKEDIN_HOST = "linkedin" + ".com"
WWW_LINKEDIN_HOST = "www." + LINKEDIN_HOST


def _timestamp(value: object, *, field: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not value.strip():
        raise workflow.WorkflowError(f"{field} must be a timezone-aware timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
            raise ValueError
        normalised = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise workflow.WorkflowError(
            f"{field} must be a whole-second timezone-aware timestamp."
        ) from exc
    return normalised.isoformat().replace("+00:00", "Z"), parsed


def _local_timestamp(parsed: datetime) -> str:
    rendered = parsed.isoformat()
    return rendered.replace("+00:00", "Z") if parsed.utcoffset() == timezone.utc.utcoffset(parsed) else rendered


def _metric(value: object, *, field: str, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        parsed = int(value)
    else:
        raise workflow.WorkflowError(f"{field} must be a non-negative whole number.")
    if not 0 <= parsed <= 9_223_372_036_854_775_807:
        raise workflow.WorkflowError(f"{field} is outside the supported range.")
    return parsed


def _text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise workflow.WorkflowError(f"{field} must be text.")
    cleaned = " ".join(value.strip().split())
    if (
        not cleaned
        or len(cleaned) > maximum
        or any(ord(character) < 32 for character in cleaned)
    ):
        raise workflow.WorkflowError(f"{field} is invalid.")
    return cleaned


def _post_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise workflow.WorkflowError("post_url must be a public LinkedIn URL.")
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise workflow.WorkflowError("post_url must be a public LinkedIn URL.") from exc
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or host not in {LINKEDIN_HOST, WWW_LINKEDIN_HOST}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise workflow.WorkflowError("post_url must be a public LinkedIn URL.")
    if not parsed.path.startswith(("/posts/", "/feed/update/")):
        raise workflow.WorkflowError("post_url must identify a LinkedIn post.")
    return urlunsplit(("https", WWW_LINKEDIN_HOST, parsed.path, "", ""))


def validate_record(record: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(record, Mapping) or set(record) != RECORD_FIELDS:
        raise workflow.WorkflowError("Spine performance record has an invalid schema.")
    published_utc, published_local = _timestamp(
        record["published_at"], field="published_at"
    )
    observed_at, _ = _timestamp(record["observed_at"], field="observed_at")
    recorded_at, _ = _timestamp(record["recorded_at"], field="recorded_at")
    if observed_at < published_utc:
        raise workflow.WorkflowError("observed_at cannot precede published_at.")
    if recorded_at < observed_at:
        raise workflow.WorkflowError("recorded_at cannot precede observed_at.")

    weekday = published_local.strftime("%A")
    if record["weekday"] != weekday:
        raise workflow.WorkflowError(
            "weekday must match the supplied publication timestamp."
        )
    if record["attention_source"] not in ATTENTION_SOURCES:
        raise workflow.WorkflowError("attention_source is unsupported.")
    if record["selected_spine"] not in CONTENT_SPINES:
        raise workflow.WorkflowError("selected_spine is unsupported.")

    post_id = record["post_id"]
    if post_id is not None and (
        not isinstance(post_id, str)
        or re.fullmatch(r"[A-Za-z0-9:_-]{1,200}", post_id) is None
    ):
        raise workflow.WorkflowError("post_id is invalid.")
    if type(record["is_breakout_outlier"]) is not bool:
        raise workflow.WorkflowError("is_breakout_outlier must be boolean.")

    validated: dict[str, object] = {
        "post_url": _post_url(record["post_url"]),
        "post_id": post_id,
        "published_at": _local_timestamp(published_local),
        "weekday": weekday,
        "topic": _text(record["topic"], field="topic", maximum=240),
        "attention_source": record["attention_source"],
        "selected_spine": record["selected_spine"],
        "impressions": _metric(record["impressions"], field="impressions"),
        "engagements": _metric(record["engagements"], field="engagements"),
        "is_breakout_outlier": record["is_breakout_outlier"],
        "observed_at": observed_at,
        "recorded_at": recorded_at,
    }
    for field in OPTIONAL_METRICS:
        validated[field] = _metric(record[field], field=field, optional=True)
    return validated


def prepare_record(
    *,
    post_url: object,
    post_id: object,
    published_at: object,
    topic: object,
    attention_source: object,
    selected_spine: object,
    impressions: object,
    engagements: object,
    qualified_comments: object = None,
    reposts: object = None,
    saves: object = None,
    profile_visits: object = None,
    relevant_followers: object = None,
    is_breakout_outlier: object = False,
    observed_at: object,
    recorded_at: object | None = None,
) -> dict[str, object]:
    _normalised, local_published = _timestamp(published_at, field="published_at")
    return validate_record(
        {
            "post_url": post_url,
            "post_id": post_id,
            "published_at": _local_timestamp(local_published),
            "weekday": local_published.strftime("%A"),
            "topic": topic,
            "attention_source": attention_source,
            "selected_spine": selected_spine,
            "impressions": impressions,
            "engagements": engagements,
            "qualified_comments": qualified_comments,
            "reposts": reposts,
            "saves": saves,
            "profile_visits": profile_visits,
            "relevant_followers": relevant_followers,
            "is_breakout_outlier": is_breakout_outlier,
            "observed_at": observed_at,
            "recorded_at": workflow.now_iso() if recorded_at is None else recorded_at,
        }
    )


def _private_root(root: Path) -> int:
    required = (
        getattr(os, "O_DIRECTORY", 0),
        getattr(os, "O_NOFOLLOW", 0),
        hasattr(os, "geteuid"),
    )
    if not all(required):
        raise workflow.WorkflowError("Secure private feedback operations are unavailable.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(root, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise workflow.WorkflowError(
            "Private feedback directory is unavailable or unsafe."
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise workflow.WorkflowError(
            "Private feedback directory must be owner-only (0700)."
        )
    return descriptor


def _feedback_location(
    path: Path | str,
    *,
    private_root: Path | str,
    allow_test_root: bool,
) -> tuple[Path, str]:
    root = Path(private_root).absolute()
    if not allow_test_root and root != workflow.DEFAULT_PRIVATE_DATA.absolute():
        raise workflow.WorkflowError("Spine feedback must remain under data/private.")
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workflow.REPO_ROOT / candidate
    candidate = candidate.absolute()
    if candidate.parent != root or candidate.name in {"", ".", ".."}:
        raise workflow.WorkflowError(
            "Spine feedback must remain directly under data/private."
        )
    return root, candidate.name


def _valid_feedback_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_size <= MAX_FILE_BYTES
    )


def _open_append_file(root_fd: int, filename: str) -> int:
    common = (
        os.O_WRONLY
        | os.O_APPEND
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    created = False
    try:
        try:
            descriptor = os.open(
                filename,
                common | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=root_fd,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(filename, common, dir_fd=root_fd)
        if created:
            os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if not _valid_feedback_file(metadata):
            raise workflow.WorkflowError(
                "Private spine feedback file is unavailable or unsafe."
            )
        return descriptor
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written < 1:
            raise workflow.WorkflowError(
                "Spine performance record was not written completely."
            )
        offset += written


def append_record(
    record: Mapping[str, object],
    *,
    path: Path | str = DEFAULT_FEEDBACK_FILE,
    private_root: Path | str = workflow.DEFAULT_PRIVATE_DATA,
    _allow_test_root: bool = False,
) -> Path:
    validated = validate_record(record)
    root, filename = _feedback_location(
        path,
        private_root=private_root,
        allow_test_root=_allow_test_root,
    )
    root_fd = _private_root(root)
    descriptor = -1
    try:
        descriptor = _open_append_file(root_fd, filename)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        if not _valid_feedback_file(metadata):
            raise workflow.WorkflowError(
                "Private spine feedback file is unavailable or unsafe."
            )
        payload = (
            json.dumps(validated, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        if metadata.st_size + len(payload) > MAX_FILE_BYTES:
            raise workflow.WorkflowError(
                "Private spine feedback file reached its size limit."
            )
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    except OSError as exc:
        raise workflow.WorkflowError(
            "Private spine feedback file is unavailable or unsafe."
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_fd)
    return root / filename


def load_records(
    *,
    path: Path | str = DEFAULT_FEEDBACK_FILE,
    private_root: Path | str = workflow.DEFAULT_PRIVATE_DATA,
    _allow_test_root: bool = False,
) -> list[dict[str, object]]:
    root, filename = _feedback_location(
        path,
        private_root=private_root,
        allow_test_root=_allow_test_root,
    )
    root_fd = _private_root(root)
    descriptor = -1
    try:
        try:
            descriptor = os.open(
                filename,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            return []
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        metadata = os.fstat(descriptor)
        if not _valid_feedback_file(metadata):
            raise workflow.WorkflowError(
                "Private spine feedback file is unavailable or unsafe."
            )
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise workflow.WorkflowError(
                    "Private spine feedback file changed while reading."
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
        ):
            raise workflow.WorkflowError(
                "Private spine feedback file changed while reading."
            )
        raw = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise workflow.WorkflowError(
            "Private spine feedback file is not valid UTF-8."
        ) from exc
    except OSError as exc:
        raise workflow.WorkflowError(
            "Private spine feedback file is unavailable or unsafe."
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_fd)

    if not raw:
        return []
    lines = raw.splitlines()
    if len(lines) > MAX_RECORDS:
        raise workflow.WorkflowError("Private spine feedback has too many records.")
    records: list[dict[str, object]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise workflow.WorkflowError(
                "Private spine feedback contains invalid JSONL."
            ) from exc
        if not isinstance(parsed, Mapping):
            raise workflow.WorkflowError(
                "Private spine feedback contains an invalid record."
            )
        records.append(validate_record(parsed))
    return records


def _latest_records(
    records: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for raw in records:
        record = validate_record(raw)
        key = str(record["post_url"])
        previous = latest.get(key)
        if previous is not None and any(
            previous[field] != record[field] for field in IMMUTABLE_CONTEXT_FIELDS
        ):
            raise workflow.WorkflowError(
                "Spine performance snapshots change immutable post context."
            )
        if previous is None or (
            str(record["observed_at"]),
            str(record["recorded_at"]),
        ) > (
            str(previous["observed_at"]),
            str(previous["recorded_at"]),
        ):
            latest[key] = record
    return sorted(
        latest.values(),
        key=lambda item: _timestamp(item["published_at"], field="published_at")[0],
    )


def _median(values: Sequence[float | int]) -> float | int | None:
    if not values:
        return None
    result = median(values)
    return round(float(result), 4) if isinstance(result, float) else result


def summarise(
    records: Sequence[Mapping[str, object]],
    *,
    include_outliers: bool = False,
) -> dict[str, object]:
    if type(include_outliers) is not bool:
        raise workflow.WorkflowError("include_outliers must be boolean.")
    latest = _latest_records(records)
    breakouts = [record for record in latest if bool(record["is_breakout_outlier"])]
    baseline = (
        latest
        if include_outliers
        else [record for record in latest if not bool(record["is_breakout_outlier"])]
    )
    by_spine: dict[str, dict[str, object]] = {}
    for spine in CONTENT_SPINES:
        cohort = [
            record for record in baseline if record["selected_spine"] == spine
        ]
        rates = [
            100.0 * int(record["engagements"]) / int(record["impressions"])
            for record in cohort
            if int(record["impressions"]) > 0
        ]
        by_spine[spine] = {
            "observation_count": len(cohort),
            "median_impressions": _median(
                [int(record["impressions"]) for record in cohort]
            ),
            "median_engagements": _median(
                [int(record["engagements"]) for record in cohort]
            ),
            "median_engagement_rate_pct": _median(rates),
            "sample_status": (
                "READY_TO_COMPARE"
                if len(cohort) >= MIN_COMPARABLE_SAMPLE
                else "INSUFFICIENT_SAMPLE"
            ),
        }
    return {
        "latest_post_records": len(latest),
        "baseline_records": len(baseline),
        "excluded_breakout_outliers": 0 if include_outliers else len(breakouts),
        "include_outliers": include_outliers,
        "minimum_comparable_sample": MIN_COMPARABLE_SAMPLE,
        "strategy_mutated": False,
        "by_spine": by_spine,
        "breakout_cases": [
            {
                "post_url": record["post_url"],
                "selected_spine": record["selected_spine"],
                "impressions": record["impressions"],
                "engagements": record["engagements"],
            }
            for record in breakouts
        ],
    }


def _nonnegative(value: str) -> int:
    parsed = _metric(value, field="metric")
    assert isinstance(parsed, int)
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="linkedin-os spine-feedback")
    subparsers = result.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser(
        "record",
        help="Append one private spine-performance snapshot.",
    )
    record.add_argument("--post-url", required=True)
    record.add_argument("--post-id")
    record.add_argument("--published-at", required=True)
    record.add_argument("--topic", required=True)
    record.add_argument(
        "--attention-source", choices=ATTENTION_SOURCES, required=True
    )
    record.add_argument("--spine", choices=CONTENT_SPINES, required=True)
    record.add_argument("--impressions", type=_nonnegative, required=True)
    record.add_argument("--engagements", type=_nonnegative, required=True)
    for field in OPTIONAL_METRICS:
        record.add_argument(f"--{field.replace('_', '-')}", type=_nonnegative)
    record.add_argument("--observed-at", required=True)
    record.add_argument("--breakout-outlier", action="store_true")

    review = subparsers.add_parser(
        "review",
        help="Summarise private spine performance by robust medians.",
    )
    review.add_argument("--include-outliers", action="store_true")
    return result


def command_record(args: argparse.Namespace) -> int:
    record = prepare_record(
        post_url=args.post_url,
        post_id=args.post_id,
        published_at=args.published_at,
        topic=args.topic,
        attention_source=args.attention_source,
        selected_spine=args.spine,
        impressions=args.impressions,
        engagements=args.engagements,
        qualified_comments=args.qualified_comments,
        reposts=args.reposts,
        saves=args.saves,
        profile_visits=args.profile_visits,
        relevant_followers=args.relevant_followers,
        is_breakout_outlier=args.breakout_outlier,
        observed_at=args.observed_at,
    )
    path = append_record(record)
    print(
        "Private spine performance recorded: "
        f"{path.relative_to(workflow.REPO_ROOT)}"
    )
    print(
        f"Spine: {record['selected_spine']}; weekday={record['weekday']}; "
        f"breakout={str(record['is_breakout_outlier']).lower()}."
    )
    print("Publishing status: DISABLED. No LinkedIn action was taken.")
    return 0


def command_review(args: argparse.Namespace) -> int:
    summary = summarise(load_records(), include_outliers=args.include_outliers)
    print(
        "Spine review: "
        f"latest_posts={summary['latest_post_records']}; "
        f"baseline={summary['baseline_records']}; "
        f"excluded_breakouts={summary['excluded_breakout_outliers']}."
    )
    by_spine = summary["by_spine"]
    assert isinstance(by_spine, Mapping)
    for spine in CONTENT_SPINES:
        row = by_spine[spine]
        assert isinstance(row, Mapping)
        rate = row["median_engagement_rate_pct"]
        rate_text = "n/a" if rate is None else f"{rate}%"
        print(
            f"{spine}: n={row['observation_count']}; "
            f"median_impressions={row['median_impressions']}; "
            f"median_engagements={row['median_engagements']}; "
            f"median_engagement_rate={rate_text}; status={row['sample_status']}."
        )
    print("Strategy mutation: DISABLED. Review is observational only.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return command_record(args) if args.command == "record" else command_review(args)
    except (workflow.WorkflowError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
