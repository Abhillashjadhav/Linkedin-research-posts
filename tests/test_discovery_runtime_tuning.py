from __future__ import annotations

import unittest

from authority_os import discovery_runtime_tuning, momentum_batched


class DiscoveryRuntimeTuningTests(unittest.TestCase):
    def test_surface_guidance_names_required_public_families(self) -> None:
        guidance = discovery_runtime_tuning.SURFACE_GUIDANCE.casefold()
        for term in (
            "google",
            "reddit",
            "hacker news",
            "youtube",
            "x/twitter",
            "linkedin",
            "substack",
            "newsletters",
            "primary",
            "reporting",
        ):
            self.assertIn(term, guidance)
        self.assertIn("authenticated", guidance)
        self.assertIn("forbidden", guidance)

    def test_install_bounds_topic_discovery_timeout(self) -> None:
        discovery_runtime_tuning.install()
        self.assertEqual(momentum_batched.TOPIC_DISCOVERY_TIMEOUT, 120)
        self.assertEqual(momentum_batched.MOMENTUM_BATCH_TIMEOUT, 150)
        self.assertIs(momentum_batched.research_batch, discovery_runtime_tuning._research_batch_bounded)

    def test_scout_role_receives_surface_guidance(self) -> None:
        discovery_runtime_tuning.install()
        role = discovery_runtime_tuning._role("scout")
        self.assertIn("DISCOVERY_SURFACE_COVERAGE", role)
        self.assertIn("Substack/public", role)


if __name__ == "__main__":
    unittest.main()
