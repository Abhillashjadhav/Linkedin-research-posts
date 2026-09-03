from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import v1_length_policy, workflow


class V1LengthPolicyTests(unittest.TestCase):
    def test_authority_range_is_calibrated_against_measured_conversion(self) -> None:
        original = dict(workflow.TEXT_WORD_LIMITS)
        try:
            with patch.object(v1_length_policy, "_INSTALLED", False):
                v1_length_policy.install()
            # Posts under 200 words had median lift 0.57; 280+ had 2.87. The
            # floor is what the evidence supports, and the old 300 cap sat below
            # his two strongest posts at 316 and 359 words.
            self.assertEqual(workflow.TEXT_WORD_LIMITS["authority"], (200, 380))
            self.assertEqual(workflow.TEXT_WORD_LIMITS["reach"], original["reach"])
            self.assertEqual(workflow.TEXT_WORD_LIMITS["opportunity"], original["opportunity"])
        finally:
            workflow.TEXT_WORD_LIMITS = original


if __name__ == "__main__":
    unittest.main()
