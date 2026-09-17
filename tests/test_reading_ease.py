"""Reading ease is measured on the retained prose and never owns acceptance."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import best_effort, draft_delivery, eval_dashboard_html, post_styles, quality_optimizer, reading_ease, v1_completion, workflow
from test_short_humorous_workflow import batch


class ReadingEaseTests(unittest.TestCase):
    def test_formula_on_known_monosyllabic_text_and_empty_input(self):
        result = reading_ease.measure('The cat sat on the mat.')
        self.assertEqual((result['words'], result['sentences'], result['syllables']), (6, 1, 6))
        self.assertEqual(result['score'], round(206.835 - 1.015 * 6 - 84.6, 1))
        self.assertIsNone(reading_ease.measure('https://example.com')['score'])
        self.assertEqual(reading_ease.measure('')['status'], 'NOT_EVALUATED')

    def test_links_and_decimal_points_do_not_inflate_sentences(self):
        plain = reading_ease.measure('Read this guide. It costs 2.5 dollars.')
        linked = reading_ease.measure('Read this [guide](https://example.com/a.b). It costs 2.5 dollars.')
        self.assertEqual(plain, linked)
        self.assertEqual(plain['sentences'], 2)

    def test_short_easy_metaphor_is_not_mistaken_for_verified_humour(self):
        result = reading_ease.measure('The gate grew eyes.', 'short-humorous')
        self.assertGreater(result['score'], 80)
        self.assertIn('not a humour score', reading_ease.label(result))
        self.assertTrue(result['advisory_only'])
        self.assertIn('first read', post_styles.instructions({'post_style': 'short-humorous'}))

    def test_diagnostics_do_not_change_selection_and_are_visible_with_exact_prose(self):
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            folder = Path(temporary)
            with patch.object(best_effort, 'output_path', return_value=folder / 'best-effort-post.md'), patch.object(
                quality_optimizer, '_ORIGINAL_RUN_ATTEMPT', return_value=batch()
            ) as invoke, patch.object(v1_completion, 'record_decision'), patch.object(
                v1_completion, 'current_run_id', return_value='readability-test'
            ), redirect_stdout(io.StringIO()) as output:
                quality_optimizer._command_draft(SimpleNamespace(command='draft', post_style='short-humorous', dry_run=False))
            saved = draft_delivery.load(folder)
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(saved['selection']['candidate_id'], 'candidate-2')
            for row in saved['results']:
                self.assertEqual(row['readability'], reading_ease.measure(row['candidate']['text'], 'short-humorous'))
            self.assertIn('Flesch Reading Ease (estimated)', output.getvalue())
            self.assertIn('Flesch Reading Ease (estimated)', (folder / 'all-candidates.md').read_text())
            self.assertIn('Flesch Reading Ease (estimated)', eval_dashboard_html.render_dashboard({'checks': []}, saved))
            self.assertEqual((folder / 'shortlisted-post.md').read_text(), batch().candidates[1].text + '\n')
