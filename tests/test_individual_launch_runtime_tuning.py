from __future__ import annotations

import unittest

from authority_os import individual_launch_runtime_tuning as tuning
from authority_os import topic_value


class IndividualLaunchRuntimeTuningTests(unittest.TestCase):
    def test_install_adds_accelerated_learning_value_type(self) -> None:
        tuning.install()
        self.assertIn(tuning.ACCELERATED_LEARNING, topic_value.VALUE_TYPES)

    def test_scout_guidance_requires_individual_builder_launches(self) -> None:
        guidance = tuning.SCOUT_GUIDANCE.casefold()
        for term in (
            "individual builders",
            "small teams",
            "open-source projects",
            "working prototypes",
            "inspect",
            "individual_launch",
        ):
            self.assertIn(term, guidance)

    def test_topic_value_task_names_accelerated_learning_route(self) -> None:
        task = (
            "Accepted reader-value routes are capability discovery, decision change, "
            "and immediate utility."
        )
        augmented = tuning._augment_task(task).casefold()
        self.assertIn("accelerated learning", augmented)
        self.assertIn("inspected, tested, reproduced", augmented)

    def test_accelerated_learning_gets_learning_priority(self) -> None:
        candidate = {
            "status": "PASS",
            "reader_value_type": tuning.ACCELERATED_LEARNING,
            "scores": {
                "reader_relevance": 4,
                "reader_value": 4,
                "gravity": 3,
                "evidence_strength": 4,
                "authority_fit": 4,
            },
        }
        self.assertEqual(tuning.priority_for(candidate), "LEARNING")


if __name__ == "__main__":
    unittest.main()
