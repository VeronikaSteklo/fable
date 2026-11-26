import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fable.config import Settings
from fable.evaluation.configurations import PRESETS
from fable.evaluation.scenarios import load_scenarios
from fable.evaluation.runner import run_experiments


class EvaluationUsageTests(unittest.TestCase):
    def test_dry_run_usage_and_summary_columns(self):
        settings = Settings(_env_file=None, api_key='offline', base_url='http://offline.invalid', model='m',
                            model_prices={'m': {'input': 1, 'output': 2}, 'fake-judge': {'input': 1, 'output': 2}})
        with TemporaryDirectory() as directory:
            out = Path(directory)
            run_experiments(load_scenarios(Path('eval/scenarios'))[:1], [PRESETS['agentic_full']], ['m'],
                            settings, out, dry_run=True, turns=1, progress=lambda _: None)
            records = [json.loads(line) for line in (out / 'runs.jsonl').read_text().splitlines()]
            self.assertEqual(records[0]['usage']['by_role']['master']['calls'], 1)
            self.assertEqual(records[0]['usage']['by_role']['consistency']['calls'], 1)
            self.assertEqual(records[0]['usage']['total_tokens'], 120)
            self.assertFalse(records[0]['usage']['estimated'])
            row = list(csv.DictReader((out / 'summary.csv').read_text().splitlines()))[0]
            self.assertEqual(float(row['mean_total_tokens_per_turn']), 120)
            self.assertEqual(float(row['mean_llm_calls_per_turn']), 2)
            self.assertGreater(float(row['total_cost_usd']), 0)
            self.assertEqual(float(row['estimated_usage_share']), 0)
            self.assertIn('Токены ср./ход', (out / 'summary.md').read_text())
            snapshot = json.loads(next((out / 'snapshots').glob('*.json')).read_text())
            self.assertGreater(snapshot['judge']['usage']['by_role']['judge']['calls'], 0)

    def test_dry_run_usage_is_reproducible(self):
        settings = Settings(_env_file=None, api_key='offline', base_url='http://offline.invalid', model='m')
        results = []
        with TemporaryDirectory() as directory:
            for name in ('one', 'two'):
                out = Path(directory) / name
                run_experiments(load_scenarios(Path('eval/scenarios'))[:1], [PRESETS['agentic_full']], ['m'],
                                settings, out, dry_run=True, turns=2, progress=lambda _: None)
                results.append([json.loads(line)['usage'] for line in (out / 'runs.jsonl').read_text().splitlines()])
        self.assertEqual(results[0], results[1])

    def test_unknown_cost_and_estimated_share(self):
        from fable.evaluation.reporting import aggregate, write_summary
        from fable.infrastructure.checks.judge import SCORE_KEYS
        run = dict(scenario='s', config='c', model='m', turns=[
            dict(ttft_ms=1, total_ms=2, reply_chars=3, error=None,
                 usage=dict(total_tokens=10, llm_calls=1, estimated=False, cost_usd=.001)),
            dict(ttft_ms=None, total_ms=2, reply_chars=3, error='failed',
                 usage=dict(total_tokens=20, llm_calls=2, estimated=True, cost_usd=None)),
        ], judge=dict(valid=True, **dict.fromkeys(SCORE_KEYS, 3), probes=[]))
        row = aggregate([run])[0]
        self.assertEqual(row['mean_total_tokens_per_turn'], 15)
        self.assertEqual(row['mean_llm_calls_per_turn'], 1.5)
        self.assertEqual(row['estimated_usage_share'], .5)
        self.assertIsNone(row['total_cost_usd'])
        with TemporaryDirectory() as directory:
            write_summary(Path(directory), [run], [], dry_run=True)
            row = list(csv.DictReader(Path(directory, 'summary.csv').read_text().splitlines()))[0]
            self.assertEqual(row['total_cost_usd'], '—')
