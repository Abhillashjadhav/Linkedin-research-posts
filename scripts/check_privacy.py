#!/usr/bin/env python3
"""Fail when a tracked/intended file crosses the public-repository boundary."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_IGNORES = {
    "data/private/**",
    "*.sqlite",
    "*.db",
    ".env",
    ".env.*",
    "outputs/**",
    "!outputs/.gitkeep",
    ".agents/",
}
SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
RUNTIME_PREFIXES = ("src/", "bin/", ".github/", ".claude/agents/")
PUBLISHING_TOKENS = (
    "api." + "linkedin.com",
    "linkedin.com/" + "v2/",
    "linkedin.com/" + "rest/",
    "ugc" + "Posts",
    "selen" + "ium",
    "play" + "wright",
    "pyauto" + "gui",
)


def candidate_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [item.decode() for item in completed.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    ignore_path = ROOT / ".gitignore"
    ignore_lines = set(ignore_path.read_text(encoding="utf-8").splitlines())
    missing = sorted(REQUIRED_IGNORES - ignore_lines)
    if missing:
        findings.append(f".gitignore missing: {', '.join(missing)}")

    for relative in candidate_files():
        path = Path(relative)
        lowered = relative.casefold()
        if lowered.startswith("data/private/"):
            findings.append(f"private path would be committed: {relative}")
        if lowered.startswith("outputs/") and relative != "outputs/.gitkeep":
            findings.append(f"generated output would be committed: {relative}")
        if path.suffix.casefold() in {".sqlite", ".db"} or path.name.startswith(".env"):
            findings.append(f"private file type would be committed: {relative}")
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"credential-like value in {relative}")
        if relative.startswith(RUNTIME_PREFIXES):
            for token in PUBLISHING_TOKENS:
                if token.casefold() in text.casefold():
                    findings.append(f"publishing/browser surface {token!r} in {relative}")
        if relative.startswith(".github/workflows/") and re.search(
            r"(?m)^\s*schedule\s*:", text
        ):
            findings.append(f"scheduled workflow in {relative}")

    if findings:
        for finding in sorted(set(findings)):
            print(f"PRIVACY FAIL: {finding}", file=sys.stderr)
        return 1
    print("Privacy check passed: no private tracked paths, credential patterns, schedule, or LinkedIn write surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
