"""Contract tests for Scout discovery behavior."""

from __future__ import annotations

import unittest

from authority_os import daily_cli


class ScoutPromptTests(unittest.TestCase):
    def test_scout_role_uses_x_for_discovery_but_not_evidence(self) -> None:
        role = daily_cli._role("scout").casefold()
        self.assertIn("x/twitter discovery pass", role)
        self.assertIn("use x/twitter only to nominate candidate topics", role)
        self.assertIn("discovery-only", role)
        self.assertIn("a factual claim cannot rely on them alone", role)
        self.assertIn("verify the underlying factual claim", role)

    def test_scout_role_keeps_x_public_optional_and_non_authenticated(self) -> None:
        role = daily_cli._role("scout").casefold()
        self.assertIn("existing `websearch` and `webfetch` tools", role)
        self.assertIn("do not use an x api key", role)
        self.assertIn("paid api dependency", role)
        self.assertIn("authenticated browser/session", role)
        self.assertIn("missing social discovery must not fail the run", role)

    def test_scout_role_prefers_global_momentum_without_equating_popularity_with_truth(self) -> None:
        role = daily_cli._role("scout").casefold()
        self.assertIn("prefer globally relevant genai/product conversations", role)
        self.assertIn("repeated independent indicators of momentum", role)
        self.assertIn("do not infer that a claim is correct", role)

    def test_scout_prioritises_video_capabilities_without_bypassing_the_os(self) -> None:
        role = daily_cli._role("scout").casefold()
        self.assertIn("video-backed capability-launch priority", role)
        self.assertIn("sourcing priority, not", role)
        self.assertIn("a shortcut", role)
        self.assertIn("topic value", role)
        self.assertIn("critic", role)
        self.assertIn("visual qa", role)
        self.assertIn("same exact title", role)
        self.assertIn("do not download or republish a video", role)


if __name__ == "__main__":
    unittest.main()
