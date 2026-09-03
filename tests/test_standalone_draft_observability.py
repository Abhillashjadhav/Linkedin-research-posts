from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from authority_os import standalone_draft_observability, v1_completion


class StandaloneDraftObservabilityTests(unittest.TestCase):
    def test_non_draft_command_is_unchanged(self) -> None:
        seen: list[list[str]] = []
        result = standalone_draft_observability.run(
            lambda argv: seen.append(argv) or 7,
            ["doctor"],
        )
        self.assertEqual(result, 7)
        self.assertEqual(seen, [["doctor"]])

    def test_inherited_discovery_run_is_not_wrapped_twice(self) -> None:
        with patch.dict(os.environ, {v1_completion.RUN_ID_ENV: "linkedin-parent"}):
            with patch.object(v1_completion, "begin_run") as begin:
                result = standalone_draft_observability.run(
                    lambda _argv: 0,
                    ["draft", "--topic", "test"],
                )
        self.assertEqual(result, 0)
        begin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
