"""Tests for the fail-closed, Git-aware repository privacy gate."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import privacy


IGNORE_TEXT = "\n".join(sorted(privacy.REQUIRED_IGNORES)) + "\n"


class PrivacyScannerTests(unittest.TestCase):
    def make_root(self, temporary: str) -> Path:
        root = Path(temporary)
        (root / ".gitignore").write_text(IGNORE_TEXT, encoding="utf-8")
        return root

    def test_clean_candidates_pass_without_reading_ignored_private_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            (root / "safe.py").write_text("print('safe')\n", encoding="utf-8")
            private = root / "data" / "private"
            private.mkdir(parents=True)
            sentinel = private / "do-not-open.txt"
            sentinel.write_text("sentinel-private-value", encoding="utf-8")
            sentinel.chmod(0)
            try:
                findings = privacy.scan_repository(root, candidates=["safe.py"])
            finally:
                sentinel.chmod(0o600)
            self.assertEqual(findings, [])

    def test_private_path_database_and_sidecar_variants_are_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            findings = privacy.scan_repository(
                root,
                candidates=[
                    "data/private/private.json",
                    "outputs/2026-07-16/report.json",
                    ".agents/local.md",
                    "config/.env.production",
                    "state.sqlite",
                    "state.sqlite-wal",
                    "state.db",
                    "state.db-shm",
                ],
            )
        rules = "\n".join(findings)
        self.assertIn("tracked-private-data", rules)
        self.assertIn("tracked-generated-output", rules)
        self.assertIn("tracked-local-agent-state", rules)
        self.assertIn("tracked-environment-file", rules)
        self.assertEqual(rules.count("tracked-database-file"), 4)

    def test_content_signatures_are_detected_without_echoing_values(self) -> None:
        token = "gh" + "p_" + ("A" * 30)
        fine_grained = "github" + "_pat_" + ("B" * 82)
        pem = "-----BEGIN " + "PRIVATE KEY-----"
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            (root / "renamed.bin").write_bytes(b"SQLite format 3\x00payload")
            (root / "credentials.txt").write_text(
                token + "\n" + pem + "\n", encoding="utf-8"
            )
            (root / "fine-grained.txt").write_text(
                fine_grained + "\n", encoding="utf-8"
            )
            findings = privacy.scan_repository(
                root,
                candidates=[
                    "renamed.bin",
                    "credentials.txt",
                    "fine-grained.txt",
                ],
            )
        output = "\n".join(findings)
        self.assertIn("sqlite-content-signature", output)
        self.assertIn("credential-signature:github-token", output)
        self.assertIn(
            "fine-grained.txt: credential-signature:github-token", output
        )
        self.assertIn("credential-signature:private-key", output)
        self.assertNotIn(token, output)
        self.assertNotIn(fine_grained, output)
        self.assertNotIn(pem, output)

    def test_schedule_and_runtime_write_surfaces_are_rejected(self) -> None:
        endpoint = "https://api." + "linkedin" + ".com/" + "rest/posts"
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            workflow = root / ".github" / "workflows" / "unsafe.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("on:\n  schedule:\n    - cron: weekly\n", encoding="utf-8")
            inline = workflow.with_name("unsafe-inline.yml")
            inline.write_text("on: [push, schedule]\n", encoding="utf-8")
            sequence = workflow.with_name("unsafe-sequence.yml")
            sequence.write_text("on:\n  - push\n  - schedule\n", encoding="utf-8")
            quoted = workflow.with_name("unsafe-quoted.yml")
            quoted.write_text(
                "on:\n  'schedule':\n    - cron: weekly\n", encoding="utf-8"
            )
            tagged = workflow.with_name("unsafe-tagged.yml")
            tagged.write_text("on: !!map {\"schedule\": []}\n", encoding="utf-8")
            runtime = root / "scripts" / "publish.py"
            runtime.parent.mkdir()
            runtime.write_text(f"ENDPOINT = {endpoint!r}\n", encoding="utf-8")
            findings = privacy.scan_repository(
                root,
                candidates=[
                    ".github/workflows/unsafe.yml",
                    ".github/workflows/unsafe-inline.yml",
                    ".github/workflows/unsafe-sequence.yml",
                    ".github/workflows/unsafe-quoted.yml",
                    ".github/workflows/unsafe-tagged.yml",
                    "scripts/publish.py",
                ],
            )
        output = "\n".join(findings)
        self.assertEqual(output.count("scheduled-workflow"), 5)
        self.assertIn("linkedin-or-browser-write-surface", output)

    def test_generic_linkedin_network_client_in_scripts_is_rejected(self) -> None:
        client_import = "import http" + ".client"
        client_reference = "http" + ".client"
        host = "www." + "linkedin" + ".com"
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            runtime = root / "scripts" / "publish.py"
            runtime.parent.mkdir()
            runtime.write_text(
                f"{client_import}\n"
                f"connection = {client_reference}.HTTPSConnection({host!r})\n"
                "connection.request('POST', '/feed/update', body=b'content')\n",
                encoding="utf-8",
            )

            findings = privacy.scan_repository(
                root, candidates=["scripts/publish.py"]
            )

        self.assertEqual(
            findings,
            ["scripts/publish.py: linkedin-or-browser-write-surface"],
        )

    def test_standard_library_url_client_is_rejected_without_literal_endpoint(self) -> None:
        client_import = "from urllib import " + "request"
        client_constructor = "request." + "Request"
        client_call = "request." + "urlopen"
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            runtime = root / "scripts" / "publish.py"
            runtime.parent.mkdir()
            runtime.write_text(
                f"{client_import}\n"
                "import os\n"
                f"outbound = {client_constructor}("
                "os.environ['CONTENT_ENDPOINT'], data=b'content')\n"
                f"{client_call}(outbound)\n",
                encoding="utf-8",
            )

            findings = privacy.scan_repository(
                root, candidates=["scripts/publish.py"]
            )

        self.assertEqual(
            findings,
            ["scripts/publish.py: linkedin-or-browser-write-surface"],
        )

    def test_symlink_candidate_is_not_followed_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            secret = root / "secret.txt"
            secret.write_text("private", encoding="utf-8")
            (root / "linked.txt").symlink_to(secret)
            findings = privacy.scan_repository(root, candidates=["linked.txt"])
        self.assertEqual(findings, ["linked.txt: symlink-candidate-not-scanned"])

    def test_intermediate_symlink_is_never_followed_outside_repository(self) -> None:
        token = "gh" + "p_" + ("A" * 30)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            outside = root.parent / f"{root.name}-outside"
            outside.mkdir()
            self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
            secret = outside / "secret.txt"
            secret.write_text(token, encoding="utf-8")
            linked = root / "linked-dir"
            linked.symlink_to(outside, target_is_directory=True)
            findings = privacy.scan_repository(
                root, candidates=["linked-dir/secret.txt"]
            )
            secret.unlink()
        self.assertEqual(
            findings,
            ["linked-dir/secret.txt: unsafe-intermediate-component"],
        )
        self.assertNotIn(token, "\n".join(findings))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO support")
    def test_non_regular_candidate_fails_closed_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            (root / "submodule-like").mkdir()
            os.mkfifo(root / "pipe")
            findings = privacy.scan_repository(
                root, candidates=["submodule-like", "pipe"]
            )
        self.assertEqual(
            findings,
            [
                "pipe: non-regular-candidate-not-scanned",
                "submodule-like: non-regular-candidate-not-scanned",
            ],
        )

    def test_oversized_candidate_fails_closed_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            path = root / "large.bin"
            with path.open("wb") as handle:
                handle.truncate(privacy.MAX_SCANNED_FILE_BYTES + 1)
            findings = privacy.scan_repository(root, candidates=["large.bin"])
        self.assertEqual(findings, ["large.bin: oversized-unscanned-file"])

    def test_same_size_candidate_mutation_fails_closed(self) -> None:
        token = ("gh" + "p_" + ("A" * 30)).encode("ascii")
        replacement = b"x" * len(token)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            candidate = root / "candidate.txt"
            candidate.write_bytes(token)
            identity = (candidate.stat().st_dev, candidate.stat().st_ino)
            real_read = privacy.os.read
            mutated = False

            def mutate_before_read(descriptor: int, size: int) -> bytes:
                nonlocal mutated
                metadata = os.fstat(descriptor)
                if not mutated and (metadata.st_dev, metadata.st_ino) == identity:
                    candidate.write_bytes(replacement)
                    mutated = True
                return real_read(descriptor, size)

            with patch.object(privacy.os, "read", side_effect=mutate_before_read):
                findings = privacy.scan_repository(
                    root, candidates=["candidate.txt"]
                )

        self.assertTrue(mutated)
        self.assertEqual(
            findings,
            ["candidate.txt: file-changed-during-scan"],
        )
        self.assertNotIn(token.decode("ascii"), "\n".join(findings))

    def test_intermediate_directory_replacement_fails_closed(self) -> None:
        token = ("gh" + "p_" + ("A" * 30)).encode("ascii")
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            nested = root / "sub"
            nested.mkdir()
            candidate = nested / "candidate.txt"
            candidate.write_bytes(b"x" * len(token))
            identity = (candidate.stat().st_dev, candidate.stat().st_ino)
            parked = root / "parked-sub"
            real_read = privacy.os.read
            replaced = False

            def replace_parent_before_read(descriptor: int, size: int) -> bytes:
                nonlocal replaced
                metadata = os.fstat(descriptor)
                if not replaced and (metadata.st_dev, metadata.st_ino) == identity:
                    nested.rename(parked)
                    nested.mkdir()
                    (nested / "candidate.txt").write_bytes(token)
                    replaced = True
                return real_read(descriptor, size)

            with patch.object(
                privacy.os, "read", side_effect=replace_parent_before_read
            ):
                findings = privacy.scan_repository(
                    root, candidates=["sub/candidate.txt"]
                )

        self.assertTrue(replaced)
        self.assertEqual(
            findings,
            ["sub/candidate.txt: file-changed-during-scan"],
        )
        self.assertNotIn(token.decode("ascii"), "\n".join(findings))

    def test_repository_root_replacement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            candidate = root / "candidate.txt"
            candidate.write_bytes(b"safe")
            identity = (candidate.stat().st_dev, candidate.stat().st_ino)
            parked = root.with_name(root.name + "-parked")
            real_read = privacy.os.read
            replaced = False

            def replace_root_before_read(descriptor: int, size: int) -> bytes:
                nonlocal replaced
                metadata = os.fstat(descriptor)
                if not replaced and (metadata.st_dev, metadata.st_ino) == identity:
                    root.rename(parked)
                    root.mkdir()
                    replaced = True
                return real_read(descriptor, size)

            try:
                with patch.object(
                    privacy.os, "read", side_effect=replace_root_before_read
                ):
                    with self.assertRaisesRegex(
                        ValueError, "Secure repository privacy scanning"
                    ):
                        privacy.scan_repository(root, candidates=["candidate.txt"])
            finally:
                if parked.exists():
                    root.rmdir()
                    parked.rename(root)

        self.assertTrue(replaced)

    def test_same_size_gitignore_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            ignore_file = root / ".gitignore"
            original = ignore_file.read_bytes()
            replacement = b"x" + original[1:]
            identity = (ignore_file.stat().st_dev, ignore_file.stat().st_ino)
            real_read = privacy.os.read
            mutated = False

            def mutate_before_read(descriptor: int, size: int) -> bytes:
                nonlocal mutated
                metadata = os.fstat(descriptor)
                if not mutated and (metadata.st_dev, metadata.st_ino) == identity:
                    ignore_file.write_bytes(replacement)
                    mutated = True
                return real_read(descriptor, size)

            with patch.object(privacy.os, "read", side_effect=mutate_before_read):
                findings = privacy.scan_repository(root, candidates=[])

        self.assertTrue(mutated)
        self.assertEqual(findings, [".gitignore: file-changed-during-scan"])

    def test_git_enumeration_failure_is_not_a_clean_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            with patch(
                "authority_os.privacy.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"failure"),
            ):
                with self.assertRaisesRegex(ValueError, "could not enumerate"):
                    privacy.candidate_files(root)
            with patch(
                "authority_os.privacy.subprocess.run",
                side_effect=FileNotFoundError,
            ):
                with self.assertRaisesRegex(ValueError, "could not enumerate"):
                    privacy.candidate_files(root)

    def test_staged_blob_is_scanned_when_worktree_copy_is_benign(self) -> None:
        token = "github" + "_pat_" + ("A" * 82)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            tracked = root / "tracked.txt"
            tracked.write_text(token + "\n", encoding="utf-8")
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "add", "--", ".gitignore", "tracked.txt"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            tracked.write_text("x" * len(token) + "\n", encoding="utf-8")

            findings = privacy.scan_repository(root)

        self.assertIn(
            "tracked.txt: staged-credential-signature:github-token",
            findings,
        )
        self.assertNotIn(token, "\n".join(findings))

    def test_git_paths_are_nul_safe_and_do_not_shell_expand(self) -> None:
        listing = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"odd\nname.txt\0literal*name\0", stderr=b""
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            discovered = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=os.fsencode(root) + b"\n", stderr=b""
            )
            with patch.dict(
                os.environ,
                {
                    "GIT_DIR": "/private/decoy.git",
                    "GIT_WORK_TREE": "/private/decoy",
                    "GIT_INDEX_FILE": "/private/decoy-index",
                },
            ), patch(
                "authority_os.privacy.subprocess.run",
                side_effect=[discovered, listing],
            ) as invoked:
                paths = privacy.candidate_files(root)
        self.assertEqual(paths, ["odd\nname.txt", "literal*name"])
        self.assertEqual(
            invoked.call_args_list[1].args[0],
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        )
        for call in invoked.call_args_list:
            environment = call.kwargs["env"]
            self.assertFalse(any(key.upper().startswith("GIT_") for key in environment))

    def test_missing_secure_open_capability_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            with patch.object(privacy.os, "O_NOFOLLOW", 0):
                with self.assertRaisesRegex(ValueError, "Secure repository"):
                    privacy.scan_repository(root, candidates=[])

    def test_sensitive_filename_is_redacted(self) -> None:
        token_name = "sk-" + ("Z" * 32) + ".txt"
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            findings = privacy.scan_repository(root, candidates=[token_name])
        self.assertEqual(findings, ["<redacted-path>: unreadable-candidate-file"])
        self.assertNotIn(token_name, findings[0])

    def test_fine_grained_github_token_filename_is_redacted(self) -> None:
        token_name = "github" + "_pat_" + ("Z" * 82) + ".txt"
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            findings = privacy.scan_repository(root, candidates=[token_name])
        self.assertEqual(findings, ["<redacted-path>: unreadable-candidate-file"])
        self.assertNotIn(token_name, findings[0])


if __name__ == "__main__":
    unittest.main()
