from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from authority_os import compare_versions, compare_versions_entry


class CompareRefResolutionTests(unittest.TestCase):
    def test_origin_tracking_ref_is_used_when_local_ref_is_missing(self) -> None:
        missing = subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="fatal: Needed a single revision\n"
        )
        found = subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout=("a" * 40) + "\n"
        )
        with mock.patch.object(
            compare_versions_entry.subprocess,
            "run",
            side_effect=[missing, found],
        ) as runner:
            resolved = compare_versions_entry.resolve_ref(
                Path("/repo"), "baseline/v0-pre-eval-v1"
            )

        self.assertEqual(resolved, "a" * 40)
        self.assertEqual(runner.call_count, 2)
        first_command = runner.call_args_list[0].args[0]
        second_command = runner.call_args_list[1].args[0]
        self.assertIn("baseline/v0-pre-eval-v1^{commit}", first_command)
        self.assertIn("origin/baseline/v0-pre-eval-v1^{commit}", second_command)

    def test_explicit_origin_ref_is_not_prefixed_twice(self) -> None:
        found = subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout=("b" * 40) + "\n"
        )
        with mock.patch.object(
            compare_versions_entry.subprocess,
            "run",
            return_value=found,
        ) as runner:
            resolved = compare_versions_entry.resolve_ref(
                Path("/repo"), "origin/baseline/v0-pre-eval-v1"
            )

        self.assertEqual(resolved, "b" * 40)
        self.assertEqual(runner.call_count, 1)
        command = runner.call_args.args[0]
        self.assertIn("origin/baseline/v0-pre-eval-v1^{commit}", command)

    def test_missing_ref_error_is_actionable(self) -> None:
        missing = subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="fatal: Needed a single revision\n"
        )
        with mock.patch.object(
            compare_versions_entry.subprocess,
            "run",
            return_value=missing,
        ):
            with self.assertRaisesRegex(
                compare_versions.ComparisonError,
                "git fetch origin",
            ):
                compare_versions_entry.resolve_ref(
                    Path("/repo"), "baseline/v0-pre-eval-v1"
                )


if __name__ == "__main__":
    unittest.main()
