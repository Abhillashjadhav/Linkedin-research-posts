"""Calendar routing is deterministic; style never changes the shortlist rule."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import daily_cli, daily_spine_cli, post_styles, weekly_spine, workflow, quality_optimizer, best_effort, draft_delivery, v1_completion
from test_short_humorous_workflow import batch
from test_drafting import strategy_brief, evidence_record


class WeeklySpineTests(unittest.TestCase):
    def test_frozen_week_and_optional_tuesday(self):
        expected = {
            '2026-09-21': ('Monday', 'educational-resources', True),
            '2026-09-22': ('Tuesday', 'incident-mitigation', False),
            '2026-09-23': ('Wednesday', 'build-video', True),
            '2026-09-24': ('Thursday', 'incident-mitigation', True),
            '2026-09-25': ('Friday', 'short-humorous', True),
            '2026-09-26': ('Saturday', None, False),
            '2026-09-27': ('Sunday', None, False),
        }
        for day, values in expected.items():
            result = weekly_spine.plan(day)
            self.assertEqual((result['weekday'], result['style'], result['active']), values)
            self.assertEqual(result['selection']['shortlist_total_exclusive'], 18)
        self.assertTrue(weekly_spine.plan('2026-09-22', include_tuesday=True)['active'])

    def test_inventories_do_not_mix_weekday_content_or_different_builds(self):
        monday = weekly_spine.plan('2026-09-21')
        tuesday = weekly_spine.plan('2026-09-22', include_tuesday=True)
        thursday = weekly_spine.plan('2026-09-24')
        self.assertNotEqual(weekly_spine.inventory_path(monday), weekly_spine.inventory_path(thursday))
        self.assertEqual(weekly_spine.inventory_path(tuesday), weekly_spine.inventory_path(thursday))
        one = {**weekly_spine.plan('2026-09-23'), 'build': {'repo_url': 'https://github.com/example/one'}}
        two = {**one, 'build': {'repo_url': 'https://github.com/example/two'}}
        self.assertNotEqual(weekly_spine.inventory_path(one), weekly_spine.inventory_path(two))

    def test_post_date_overrides_research_date_and_legacy_style(self):
        args = SimpleNamespace(post_date='2026-09-18', as_of='2026-09-17T01:00:00Z', post_style='standard', topic='AI keys', week_slot=3)
        with redirect_stdout(io.StringIO()):
            selected = weekly_spine.prepare(args)
        self.assertEqual(selected['weekday'], 'Friday')
        self.assertEqual(args.post_style, 'short-humorous')
        self.assertIn('sarcastic', args.weekly_focus)
        self.assertEqual(args.topic, 'AI keys')
        self.assertIsNone(args.week_slot)
        self.assertEqual(args.as_of, '2026-09-17T01:00:00Z')

    def test_off_day_returns_before_private_profile_or_model_access(self):
        args = daily_spine_cli.parser().parse_args(['--profile','data/private/not-present.json','--post-date','2026-09-26','--generate-post'])
        with patch.object(daily_cli, '_private_json') as read, redirect_stdout(io.StringIO()):
            self.assertEqual(daily_spine_cli.command(args), 0)
        read.assert_not_called()

    def test_wednesday_requires_actual_video_input(self):
        args = SimpleNamespace(post_date='2026-09-23', post_style=None, topic=None, build_manifest=Path('/not-present/build.json'))
        with self.assertRaisesRegex(workflow.WorkflowError, 'real video'):
            weekly_spine.prepare(args)
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as folder:
            folder = Path(folder)
            video = folder / 'recording.mp4'
            video.write_bytes(b'synthetic attachment fixture')
            manifest = folder / 'build.json'
            daily_cli.write_private_json(manifest, {'repo_url':'https://github.com/example/build', 'summary':'An explicitly supplied test build.', 'video_path':str(video), 'built_by_author':True})
            args.build_manifest = manifest
            with redirect_stdout(io.StringIO()):
                selected = weekly_spine.prepare(args)
            self.assertEqual(selected['build']['video_path'], str(video))
            video.unlink()
            with self.assertRaisesRegex(workflow.WorkflowError, 'missing or empty'):
                weekly_spine.prepare(args)

    def test_weekday_prompts_do_not_all_force_incidents_or_humour(self):
        for style in post_styles.STYLE_NAMES:
            brief = strategy_brief()
            brief['post_style'] = style
            writer = workflow.build_writer_prompt(brief=brief,evidence=[evidence_record()],voice_guidance=workflow.load_voice_guidance())
            self.assertIn(post_styles.opening(brief), writer)
        self.assertIn('Curate a small useful set', post_styles.instructions({'post_style':'educational-resources'}))
        self.assertIn('actual build video', post_styles.instructions({'post_style':'build-video'}))
        self.assertIn('slightly sarcastic', post_styles.instructions({'post_style':'short-humorous'}))

    def test_every_live_style_uses_one_batch_and_the_same_shortlist(self):
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        for style in post_styles.STYLE_NAMES:
            with self.subTest(style=style), tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as folder:
                with patch.object(best_effort,'output_path',return_value=Path(folder)/'best-effort-post.md'), \
                     patch.object(quality_optimizer,'_ORIGINAL_RUN_ATTEMPT',return_value=batch()) as run, \
                     patch.object(v1_completion,'record_decision'), \
                     patch.object(v1_completion,'current_run_id',return_value='weekly-test'), redirect_stdout(io.StringIO()):
                    result = quality_optimizer._command_draft(SimpleNamespace(command='draft',post_style=style,dry_run=False,run_spec=None))
                    saved = draft_delivery.load()
                self.assertEqual(result,0)
                self.assertEqual(run.call_count,1)
                self.assertEqual(saved['selection']['candidate_id'],'candidate-2')
                self.assertEqual(len(saved['results']),3)


if __name__ == '__main__':
    unittest.main()
