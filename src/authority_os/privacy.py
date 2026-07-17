"""Git-aware privacy and publishing-surface checks for the public repository."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Iterable


MAX_SCANNED_FILE_BYTES = 2_000_000
REQUIRED_IGNORES = frozenset(
    {
        "data/private/**",
        "*.sqlite",
        "*.sqlite-*",
        "*.db",
        "*.db-*",
        ".env",
        ".env.*",
        "outputs/**",
        "!outputs/.gitkeep",
        ".agents/",
    }
)

_GITHUB_FINE_GRAINED_BYTES = rb"github" + rb"_pat_"
_GITHUB_FINE_GRAINED_TEXT = r"github" + r"_pat_"

_SECRET_PATTERNS = (
    ("anthropic-token", re.compile(rb"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai-token", re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("github-token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}")),
    (
        "github-token",
        re.compile(_GITHUB_FINE_GRAINED_BYTES + rb"[A-Za-z0-9_]{60,}"),
    ),
    ("aws-access-key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    (
        "private-key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)
_SENSITIVE_PATH_PATTERN = re.compile(
    r"(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|"
    + _GITHUB_FINE_GRAINED_TEXT
    + r"[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{8,})",
    re.IGNORECASE,
)
_WORKFLOW_SCHEDULE_PATTERNS = (
    re.compile(
        rb"(?im)(?:^|[,{])\s*(?:!![A-Za-z0-9_-]+\s*)?[\"']?schedule[\"']?\s*:"
    ),
    re.compile(
        rb"(?im)^\s*(?:on\s*:\s*|-\s*)(?:!![A-Za-z0-9_-]+\s*)?[\"']?schedule[\"']?\s*(?:#.*)?$"
    ),
    re.compile(rb"(?im)^\s*on\s*:\s*\[[^\]\n]*[\"']?schedule[\"']?"),
)
_WRITE_SURFACES = (
    b"linkedin" + b".com",
    b"ugc" + b"Posts",
    b"import " + b"requests",
    b"from " + b"requests",
    b"import " + b"httpx",
    b"from " + b"httpx",
    b"urllib" + b".request",
    b"from " + b"urllib import request",
    b"request." + b"urlopen",
    b"request." + b"Request",
    b"http" + b".client",
    b"import " + b"playwright",
    b"from " + b"playwright",
    b"import " + b"selenium",
    b"from " + b"selenium",
    b"import " + b"pyautogui",
    b"from " + b"pyautogui",
)


def _safe_display(relative: str) -> str:
    if (
        not relative.isprintable()
        or _SENSITIVE_PATH_PATTERN.search(relative)
        or len(relative) > 240
    ):
        return "<redacted-path>"
    return relative


def _metadata_token(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _identity_token(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _read_positional_snapshot(descriptor: int, size: int) -> bytes | None:
    """Read one bounded snapshot without changing the descriptor offset."""

    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(65_536, size - offset), offset)
        if not chunk:
            return None
        chunks.append(chunk)
        offset += len(chunk)
    if os.pread(descriptor, 1, size):
        return None
    return b"".join(chunks)


def _git_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }


def candidate_files(root: Path) -> list[str]:
    """List tracked and prospective non-ignored files without reading ignored data."""

    environment = _git_environment()
    try:
        discovered = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if discovered.returncode != 0:
            raise ValueError("Privacy scan could not enumerate repository files.")
        try:
            top_level = Path(os.fsdecode(discovered.stdout).strip()).resolve(strict=True)
            expected = root.resolve(strict=True)
        except (OSError, ValueError):
            raise ValueError("Privacy scan could not enumerate repository files.") from None
        if top_level != expected:
            raise ValueError("Privacy scan could not enumerate repository files.")
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Privacy scan could not enumerate repository files.") from exc
    if completed.returncode != 0:
        raise ValueError("Privacy scan could not enumerate repository files.")
    entries = [os.fsdecode(item) for item in completed.stdout.split(b"\0") if item]
    if any("\0" in entry for entry in entries):
        raise ValueError("Privacy scan received an invalid repository path.")
    return entries


def _staged_entries(root: Path) -> tuple[list[tuple[str, str, str]], bytes]:
    """Return exact index paths, modes, and blob IDs plus the index snapshot."""

    try:
        completed = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=root,
            env=_git_environment(),
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Privacy scan could not inspect the Git index.") from exc
    if completed.returncode != 0:
        raise ValueError("Privacy scan could not inspect the Git index.")
    entries: list[tuple[str, str, str]] = []
    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        try:
            header, raw_path = item.split(b"\t", 1)
            mode, object_id, stage = header.split(b" ", 2)
            relative = os.fsdecode(raw_path)
            decoded_mode = mode.decode("ascii")
            decoded_object_id = object_id.decode("ascii")
            decoded_stage = stage.decode("ascii")
        except (UnicodeError, ValueError):
            raise ValueError("Privacy scan received invalid Git index metadata.") from None
        if (
            "\0" in relative
            or re.fullmatch(r"[0-7]{6}", decoded_mode) is None
            or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", decoded_object_id)
            is None
            or re.fullmatch(r"[0-3]", decoded_stage) is None
        ):
            raise ValueError("Privacy scan received invalid Git index metadata.")
        entries.append(
            (relative, decoded_mode, decoded_object_id)
            if decoded_stage == "0"
            else (relative, f"unmerged-{decoded_stage}", decoded_object_id)
        )
    return entries, completed.stdout


def _read_staged_blob(root: Path, object_id: str) -> tuple[bytes | None, str | None]:
    """Read one bounded immutable Git blob without path or filter interpretation."""

    environment = _git_environment()
    try:
        size_result = subprocess.run(
            ["git", "cat-file", "-s", object_id],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if size_result.returncode != 0:
            return None, "unreadable-staged-blob"
        try:
            size_text = size_result.stdout.decode("ascii").strip()
        except UnicodeError:
            return None, "unreadable-staged-blob"
        if re.fullmatch(r"[0-9]+", size_text) is None:
            return None, "unreadable-staged-blob"
        size = int(size_text)
        if size > MAX_SCANNED_FILE_BYTES:
            return None, "oversized-staged-file"
        blob_result = subprocess.run(
            ["git", "cat-file", "blob", object_id],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "unreadable-staged-blob"
    if blob_result.returncode != 0 or len(blob_result.stdout) != size:
        return None, "unreadable-staged-blob"
    return blob_result.stdout, None


def _path_rule(relative: str) -> str | None:
    lowered = relative.casefold().replace("\\", "/")
    parts = lowered.split("/")
    basename = parts[-1]
    if lowered == "data/private" or lowered.startswith("data/private/"):
        return "tracked-private-data"
    if (lowered == "outputs" or lowered.startswith("outputs/")) and lowered != "outputs/.gitkeep":
        return "tracked-generated-output"
    if lowered == ".agents" or lowered.startswith(".agents/"):
        return "tracked-local-agent-state"
    if basename == ".env" or basename.startswith(".env."):
        return "tracked-environment-file"
    if (
        basename.endswith((".sqlite", ".db"))
        or ".sqlite-" in basename
        or ".db-" in basename
    ):
        return "tracked-database-file"
    return None


def _read_candidate(root_descriptor: int, relative: str) -> tuple[bytes | None, str | None]:
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None, "unsafe-repository-path"
    directory_descriptors: list[tuple[int, os.stat_result]] = []
    descriptor = -1
    opening_leaf = False
    try:
        current_descriptor = os.dup(root_descriptor)
        directory_descriptors.append(
            (current_descriptor, os.fstat(current_descriptor))
        )
        for part in path.parts[:-1]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current_descriptor,
            )
            if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                os.close(next_descriptor)
                return None, "unsafe-intermediate-component"
            current_descriptor = next_descriptor
            directory_descriptors.append(
                (current_descriptor, os.fstat(current_descriptor))
            )
        opening_leaf = True
        descriptor = os.open(
            path.parts[-1],
            os.O_RDONLY
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=current_descriptor,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None, "non-regular-candidate-not-scanned"
        if metadata.st_size > MAX_SCANNED_FILE_BYTES:
            return None, "oversized-unscanned-file"
        positional_snapshot = _read_positional_snapshot(
            descriptor, int(metadata.st_size)
        )
        if positional_snapshot is None:
            return None, "file-changed-during-scan"
        chunks: list[bytes] = []
        remaining = int(metadata.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                return None, "incomplete-file-read"
            chunks.append(chunk)
            remaining -= len(chunk)
        streamed_snapshot = b"".join(chunks)
        if (
            streamed_snapshot != positional_snapshot
            or os.read(descriptor, 1)
            or _metadata_token(os.fstat(descriptor)) != _metadata_token(metadata)
        ):
            return None, "file-changed-during-scan"
        for index, part in enumerate(path.parts[:-1]):
            parent_descriptor = directory_descriptors[index][0]
            child_descriptor, child_metadata = directory_descriptors[index + 1]
            try:
                live_child = os.stat(
                    part,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                return None, "file-changed-during-scan"
            if (
                _identity_token(live_child) != _identity_token(child_metadata)
                or _identity_token(os.fstat(child_descriptor))
                != _identity_token(child_metadata)
            ):
                return None, "file-changed-during-scan"
        try:
            live_leaf = os.stat(
                path.parts[-1],
                dir_fd=directory_descriptors[-1][0],
                follow_symlinks=False,
            )
        except OSError:
            return None, "file-changed-during-scan"
        if _metadata_token(live_leaf) != _metadata_token(metadata):
            return None, "file-changed-during-scan"
        return streamed_snapshot, None
    except OSError:
        # Inspect the leaf relative to the already verified parent descriptor.
        if opening_leaf and directory_descriptors:
            try:
                metadata = os.stat(
                    path.parts[-1],
                    dir_fd=directory_descriptors[-1][0],
                    follow_symlinks=False,
                )
                if stat.S_ISLNK(metadata.st_mode):
                    return None, "symlink-candidate-not-scanned"
            except OSError:
                pass
        return None, (
            "unsafe-intermediate-component"
            if not opening_leaf
            else "unreadable-candidate-file"
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for directory_descriptor, _metadata in reversed(directory_descriptors):
            os.close(directory_descriptor)


def _scan_payload(
    relative: str,
    payload: bytes,
    findings: set[str],
    *,
    staged: bool,
) -> None:
    display = _safe_display(relative)
    prefix = "staged-" if staged else ""
    if payload.startswith(b"SQLite format 3\x00"):
        findings.add(f"{display}: {prefix}sqlite-content-signature")
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(payload):
            findings.add(f"{display}: {prefix}credential-signature:{name}")
    lowered_payload = payload.lower()
    for token in _WRITE_SURFACES:
        if token.lower() in lowered_payload:
            findings.add(f"{display}: {prefix}linkedin-or-browser-write-surface")
            break
    normalized = relative.replace("\\", "/")
    if normalized.startswith(".github/workflows/") and any(
        pattern.search(payload) for pattern in _WORKFLOW_SCHEDULE_PATTERNS
    ):
        findings.add(f"{display}: {prefix}scheduled-workflow")


def _check_ignore_payload(
    payload: bytes,
    findings: set[str],
    *,
    staged: bool,
) -> None:
    prefix = "staged-" if staged else ""
    try:
        ignore_lines = set(payload.decode("utf-8").splitlines())
    except UnicodeError:
        findings.add(f".gitignore: {prefix}unreadable-ignore-policy")
        return
    for rule in sorted(REQUIRED_IGNORES - ignore_lines):
        findings.add(f".gitignore: {prefix}missing-ignore-rule:{rule}")


def scan_repository(root: Path, *, candidates: Iterable[str] | None = None) -> list[str]:
    """Return redacted rule findings; an empty list means the repository is safe."""

    repository = Path(root)
    findings: set[str] = set()
    required = (
        getattr(os, "O_DIRECTORY", 0),
        getattr(os, "O_NOFOLLOW", 0),
        getattr(os, "O_NONBLOCK", 0),
        callable(getattr(os, "pread", None)),
        os.open in getattr(os, "supports_dir_fd", ()),
        os.stat in getattr(os, "supports_dir_fd", ()),
        os.stat in getattr(os, "supports_follow_symlinks", ()),
    )
    if not all(required):
        raise ValueError("Secure repository privacy scanning is unavailable.")
    root_descriptor = -1
    try:
        root_descriptor = os.open(
            repository,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        root_metadata = os.fstat(root_descriptor)
        root_current = os.stat(repository, follow_symlinks=False)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or _identity_token(root_current) != _identity_token(root_metadata)
        ):
            raise ValueError("Secure repository privacy scanning is unavailable.")
        ignore_payload, ignore_rule = _read_candidate(root_descriptor, ".gitignore")
        if ignore_payload is None or ignore_rule is not None:
            findings.add(
                ".gitignore: file-changed-during-scan"
                if ignore_rule == "file-changed-during-scan"
                else ".gitignore: unreadable-ignore-policy"
            )
        else:
            _check_ignore_payload(ignore_payload, findings, staged=False)

        paths = candidate_files(repository) if candidates is None else list(candidates)
        for relative in paths:
            display = _safe_display(relative)
            rule = _path_rule(relative)
            if rule is not None:
                findings.add(f"{display}: {rule}")
                # Never inspect a path already classified as private.
                continue
            payload, read_rule = _read_candidate(root_descriptor, relative)
            if read_rule is not None:
                findings.add(f"{display}: {read_rule}")
                continue
            if payload is None:
                continue
            _scan_payload(relative, payload, findings, staged=False)

        if candidates is None:
            staged_entries, staged_snapshot = _staged_entries(repository)
            staged_payloads: dict[str, bytes] = {}
            for relative, mode, object_id in staged_entries:
                display = _safe_display(relative)
                rule = _path_rule(relative)
                if rule is not None:
                    findings.add(f"{display}: staged-{rule}")
                    continue
                if mode not in {"100644", "100755"}:
                    findings.add(f"{display}: non-regular-staged-file")
                    continue
                payload = staged_payloads.get(object_id)
                if payload is None:
                    payload, read_rule = _read_staged_blob(repository, object_id)
                    if read_rule is not None:
                        findings.add(f"{display}: {read_rule}")
                        continue
                    if payload is None:
                        continue
                    staged_payloads[object_id] = payload
                if relative == ".gitignore":
                    _check_ignore_payload(payload, findings, staged=True)
                _scan_payload(relative, payload, findings, staged=True)
            _after_entries, staged_snapshot_after = _staged_entries(repository)
            if staged_snapshot_after != staged_snapshot:
                findings.add("<git-index>: changed-during-scan")
        root_after = os.stat(repository, follow_symlinks=False)
        if (
            _identity_token(os.fstat(root_descriptor))
            != _identity_token(root_metadata)
            or _identity_token(root_after) != _identity_token(root_metadata)
        ):
            raise ValueError("Secure repository privacy scanning is unavailable.")
    except OSError as exc:
        raise ValueError("Secure repository privacy scanning is unavailable.") from exc
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)
    return sorted(findings)
