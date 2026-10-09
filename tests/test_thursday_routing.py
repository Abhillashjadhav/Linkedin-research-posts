from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import social_media_gate_policy, thursday_capability


class ThursdayRoutingTests(unittest.TestCase):
    def test_campaign_day_takes_precedence_over_weekly_slot_number(self) -> None:
        self.assertTrue(thursday_capability.is_thursday(brief={"day": "Thursday", "weekly_slot": 4}))
        self.assertFalse(thursday_capability.is_thursday(brief={"day": "Wednesday", "weekly_slot": 3}))
        self.assertTrue(thursday_capability.is_thursday(week_slot=3))
        self.assertFalse(thursday_capability.is_thursday(week_slot=4))

    def test_unknown_route_and_source_text_do_not_activate_lane(self) -> None:
        self.assertFalse(thursday_capability.is_thursday())
        self.assertFalse(thursday_capability.is_thursday(brief={"topic": "Thursday demo", "weekly_slot": True}))
        self.assertFalse(thursday_capability.is_thursday(brief={"weekly_slot": "3"}))

    def test_thursday_overlay_does_not_reintroduce_unmeasured_numeric_hooks(self) -> None:
        with patch.object(social_media_gate_policy, "_ORIGINAL_BUILD_WRITER_PROMPT", return_value="GROUNDED WRITER"):
            thursday = social_media_gate_policy._build_writer_prompt_social(
                brief={"weekly_slot": 3}, evidence=(), voice_guidance={}
            )
            ordinary = social_media_gate_policy._build_writer_prompt_social(
                brief={"weekly_slot": 2}, evidence=(), voice_guidance={}
            )
        self.assertEqual(thursday, "GROUNDED WRITER")
        self.assertIn("XX%", ordinary)


if __name__ == "__main__":
    unittest.main()
