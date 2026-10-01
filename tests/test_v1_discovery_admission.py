from __future__ import annotations

import unittest

from authority_os import v1_discovery_admission as admission


class V1DiscoveryAdmissionTests(unittest.TestCase):
    def _candidate(self, *, total: int, authority: int, platforms: int, eligible: bool = False):
        return {
            "id": f"topic-{total}-{authority}-{platforms}",
            "topic": "Example topic",
            "total": total,
            "observed_axes": 4,
            "platforms": [f"surface-{index}" for index in range(platforms)],
            "momentum_eligible": eligible,
            "authority_fit": {"total": authority, "scores": {}},
        }

    def test_two_surface_high_authority_topic_can_rescue(self) -> None:
        candidate = self._candidate(total=7, authority=23, platforms=2)
        self.assertTrue(admission.qualifies_for_rescue(candidate))

    def test_single_surface_topic_cannot_rescue_even_with_high_authority(self) -> None:
        candidate = self._candidate(total=13, authority=24, platforms=1)
        self.assertFalse(admission.qualifies_for_rescue(candidate))

    def test_weak_authority_or_momentum_cannot_rescue(self) -> None:
        self.assertFalse(admission.qualifies_for_rescue(self._candidate(total=6, authority=25, platforms=3)))
        self.assertFalse(admission.qualifies_for_rescue(self._candidate(total=12, authority=21, platforms=3)))

    def test_existing_momentum_lane_is_never_relabelled_as_rescue(self) -> None:
        candidate = self._candidate(total=14, authority=23, platforms=2, eligible=True)
        self.assertFalse(admission.qualifies_for_rescue(candidate))


if __name__ == "__main__":
    unittest.main()
