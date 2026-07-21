"""Regression tests for the public repository narrative and local documentation links."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PUBLIC_DOCS = (
    README,
    ROOT / "docs" / "PRODUCT_DECISIONS.md",
    ROOT / "docs" / "HUMAN_JUDGMENT.md",
    ROOT / "docs" / "WHAT_I_LEARNED.md",
    ROOT / "docs" / "SECURITY_AND_PRIVACY.md",
)
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class PublicSurfaceTests(unittest.TestCase):
    def test_readme_leads_with_problem_architecture_and_human_boundary(self) -> None:
        text = README.read_text(encoding="utf-8")
        problem = (
            "Fluent content can still be generic, unsupported, strategically empty, "
            "or disconnected from the author's actual work."
        )
        architecture = (
            "research → analysis → strategic routing → voice-grounded drafting"
        )
        self.assertIn(problem, text)
        self.assertIn(architecture, text)
        self.assertIn("independent critique → deterministic gates → human review", text)
        self.assertIn("Authority statement", text)
        self.assertIn("Proof approval", text)
        self.assertIn("Final publication", text)
        self.assertLess(text.index(problem), text.index("## 60-second synthetic walkthrough"))
        self.assertLess(
            text.index("## 60-second synthetic walkthrough"),
            text.index("## What each boundary prevents"),
        )

    def test_review_package_is_explained_file_by_file(self) -> None:
        text = README.read_text(encoding="utf-8")
        for filename in (
            "manifest.json",
            "brief.md",
            "candidates.md",
            "evaluation.json",
            "sources.md",
            "final-package.md",
        ):
            with self.subTest(filename=filename):
                self.assertGreaterEqual(text.count(filename), 2)
        self.assertIn("written last as the package commit marker", text)

    def test_required_decisions_and_human_judgements_are_explicit(self) -> None:
        product = (ROOT / "docs" / "PRODUCT_DECISIONS.md").read_text(
            encoding="utf-8"
        )
        for heading in (
            "## Research and proof are distinct",
            "## Goal and format are separate",
            "## Critic scoring cannot approve",
            "## Deterministic gates follow model critique",
            "## Publishing is disabled",
            "## Performance learning waits for mature checkpoints",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, product)

        judgement = (ROOT / "docs" / "HUMAN_JUDGMENT.md").read_text(
            encoding="utf-8"
        )
        for decision in (
            "Target reader",
            "Reader problem",
            "Core hypothesis",
            "Product decision",
            "Authority statement",
            "Manual proof approval",
            "Publication is a separate human-controlled action",
        ):
            with self.subTest(decision=decision):
                self.assertIn(decision, judgement)
        self.assertIn("Manual approval is required for every personal voice section", judgement)

    def test_lessons_remain_manual_review_material(self) -> None:
        text = (ROOT / "docs" / "WHAT_I_LEARNED.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("**HUMAN REVIEW REQUIRED**"), 7)
        self.assertIn("not a first-person account", text)
        self.assertIn("Do not describe the routing as strategically successful", text)

    def test_public_claims_remain_restrained(self) -> None:
        combined = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_DOCS)
        forbidden = (
            "AI content " + "machine",
            "growth" + "-hacking",
            "viral" + " posts",
            "creates" + " viral",
            "guarantees reach",
        )
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.casefold(), combined.casefold())
        self.assertIn(
            "authority: demonstrated expertise",
            combined.casefold(),
        )
        self.assertIn("The system does not promise reach or strategic quality", combined)

    def test_public_docs_do_not_speak_for_the_owner_in_first_person(self) -> None:
        first_person = re.compile(r"\b(?:I|I'm|I've|my|mine|we|we're|we've|our|ours)\b", re.I)
        for path in PUBLIC_DOCS:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(first_person.search(path.read_text(encoding="utf-8")))

    def test_local_markdown_links_resolve_inside_the_repository(self) -> None:
        for path in PUBLIC_DOCS:
            text = path.read_text(encoding="utf-8")
            for raw_target in LINK_PATTERN.findall(text):
                target = raw_target.strip().strip("<>")
                parsed = urlparse(target)
                if parsed.scheme or target.startswith("#"):
                    continue
                local_part = unquote(target.split("#", 1)[0])
                resolved = (path.parent / local_part).resolve()
                with self.subTest(path=path.relative_to(ROOT), target=target):
                    self.assertTrue(resolved.is_relative_to(ROOT.resolve()))
                    self.assertTrue(resolved.exists())


if __name__ == "__main__":
    unittest.main()
