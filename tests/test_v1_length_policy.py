from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import v1_length_policy, workflow


class V1LengthPolicyTests(unittest.TestCase):
    def test_authority_has_no_material_lower_bound_and_keeps_300_word_cap(self) -> None:
        original = dict(workflow.TEXT_WORD_LIMITS)
        try:
            with patch.object(v1_length_policy, "_INSTALLED", False):
                v1_length_policy.install()
            self.assertEqual(workflow.TEXT_WORD_LIMITS["authority"], (1, 300))
            self.assertEqual(workflow.TEXT_WORD_LIMITS["reach"], original["reach"])
            self.assertEqual(workflow.TEXT_WORD_LIMITS["opportunity"], original["opportunity"])
        finally:
            workflow.TEXT_WORD_LIMITS = original


if __name__ == "__main__":
    unittest.main()
