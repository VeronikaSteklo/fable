import json
from pathlib import Path
import tempfile
import unittest


class ConfigurationTests(unittest.TestCase):
    def test_presets_and_plain_agent(self):
        from dataclasses import replace
        from fable.config import Settings
        from fable.evaluation.configurations import PRESETS, configure_settings, plain_prompt
        from fable.evaluation.scenarios import load_scenarios
        from fable.infrastructure.plain_agent import PlainStreamingAgent
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='fake', embedding_model='embed')
        for name, preset in PRESETS.items():
            configured = configure_settings(settings, preset, 'other')
            self.assertEqual(configured.model, 'other')
            self.assertEqual(configured.summary_enabled, preset.summary)
            self.assertEqual(configured.consistency_check_enabled, preset.consistency)
            self.assertEqual(configured.companions_enabled, preset.companions)
            self.assertEqual(bool(configured.embedding_model), preset.memory)
            self.assertFalse(configured.moderation_enabled)
        self.assertFalse(PRESETS['static'].tools)
        self.assertFalse(PRESETS['static'].summary)
        self.assertTrue(PRESETS['agentic_full'].consistency)
        self.assertEqual(configure_settings(settings, replace(PRESETS['static'], history_limit=4), 'fake').history_limit, 4)
        setup = load_scenarios(Path('eval/scenarios'))[0].setup
        prompt = plain_prompt(setup)
        self.assertIn(setup.character.name, prompt)
        self.assertNotIn('read_game_state', prompt)
        class Model:
            def stream(self, messages):
                self.messages = messages
                yield type('Chunk', (), {'text': 'Ответ'})()
        model = Model()
        self.assertEqual(list(PlainStreamingAgent(model, prompt).stream([{'role': 'user', 'content': 'ход'}])), ['Ответ'])
        self.assertEqual(model.messages[0], {'role': 'system', 'content': prompt})


    def test_plain_model_uses_same_generation_options(self):
        from unittest.mock import patch
        from fable.config import Settings
        from fable.infrastructure.plain_agent import PlainStreamingAgent
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='X',
                            enable_thinking='low', temperature=.3)
        with patch('langchain_openai.ChatOpenAI') as model:
            PlainStreamingAgent.from_settings(settings, 'роль')
        kwargs = model.call_args.kwargs
        self.assertEqual(kwargs['temperature'], .3)
        self.assertEqual(kwargs['extra_body']['reasoning_effort'], 'low')
        self.assertTrue(kwargs['extra_body']['chat_template_kwargs']['enable_thinking'])

    def test_runtime_context_ablation_and_summary_trigger(self):
        from fable.config import Settings
        from fable.evaluation.factory import create_runtime
        from fable.evaluation.configurations import PRESETS
        from fable.evaluation.scenarios import load_scenarios
        scenario = next(s for s in load_scenarios(Path('eval/scenarios')) if s.id == 'long_recall')
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='fake')
        class Agent:
            def stream(self, messages):
                self.messages = messages
                yield str(len(messages))
        for name in ['static', 'static_summary', 'agentic_full']:
            agent = Agent()
            runtime = create_runtime(settings, scenario.setup, PRESETS[name], 'fake', dry_run=True,
                                     agent_factory=lambda *args: agent)
            runtime.session.start()
            for action in scenario.actions:
                runtime.session.send_action(action)
            self.assertLessEqual(len(agent.messages), 16)
            self.assertEqual(bool(runtime.session.summary), name != 'static')
            self.assertEqual(runtime.options['context_provider'] is not None, name == 'agentic_full')
            self.assertEqual(runtime.options['checker'] is not None, name == 'agentic_full')


class JudgeTests(unittest.TestCase):
    def test_json_parsing(self):
        from fable.infrastructure.evaluation_judge import SCORE_KEYS, parse_judgment, parse_probe
        valid: dict = dict.fromkeys(SCORE_KEYS, 4)
        valid['justification'] = 'Связный ответ.'
        self.assertEqual(parse_judgment('```json\n' + json.dumps(valid) + '\n```')['coherence'], 4)
        for raw in ['мусор', '{}', json.dumps({**valid, 'coherence': 6}), json.dumps({**valid, 'player_agency': True})]:
            self.assertIsNone(parse_judgment(raw))
        self.assertEqual(parse_probe('{"status":"respected","justification":"Ключ упомянут"}')['status'], 'respected')
        self.assertIsNone(parse_probe('{"status":"maybe"}'))

    def test_judge_uses_only_later_replies_for_probes(self):
        from fable.infrastructure.evaluation_judge import LLMJudge, SCORE_KEYS
        from fable.evaluation.scenarios import load_scenarios
        class Model:
            def __init__(self):
                self.calls = []
            def invoke(self, messages):
                self.calls.append(messages)
                value = ({**dict.fromkeys(SCORE_KEYS, 3), 'justification': 'Проверено'} if len(self.calls) == 1
                         else {'status': 'ignored', 'justification': 'Не упомянуто'})
                return type('Reply', (), {'text': json.dumps(value)})()
        model = Model()
        scenario = next(s for s in load_scenarios(Path('eval/scenarios')) if s.id == 'long_recall')
        result = LLMJudge(model).evaluate(scenario, [dict(turn=2, reply='EARLY', model='HIDDEN', config='static'), dict(turn=18, reply='LATE')])
        self.assertTrue(result['valid'])
        self.assertNotIn('HIDDEN', model.calls[0][1]['content'])
        self.assertNotIn('static', model.calls[0][1]['content'])
        payload = json.loads(model.calls[1][1]['content'])
        self.assertEqual(payload['replies'], [{'turn': 18, 'reply': 'LATE'}])
        self.assertEqual(result['probes'][0]['status'], 'ignored')

    def test_judge_api_failure_and_unexposed_probe(self):
        from fable.infrastructure.evaluation_judge import LLMJudge
        from fable.evaluation.scenarios import load_scenarios
        class Model:
            def invoke(self, messages):
                raise RuntimeError('судья недоступен')
        scenario = load_scenarios(Path('eval/scenarios'))[0]
        judge = LLMJudge(Model())
        result = judge.evaluate(scenario, [dict(turn=0, reply='начало')])
        self.assertFalse(result['valid'])
        self.assertIn('недоступен', result['error'])
        self.assertFalse(result['probes'][0]['eligible'])
        result = judge.evaluate(scenario, [dict(turn=1, reply='поздний ответ')])
        self.assertFalse(result['probes'][0]['valid'])
        self.assertTrue(result['probes'][0]['eligible'])

    def test_consistency_invalid_json_is_not_silently_valid(self):
        from fable.infrastructure.evaluation_judge import ObservedConsistencyChecker
        class Model:
            def invoke(self, messages):
                return type('Reply', (), {'text': 'garbage'})()
        checker = ObservedConsistencyChecker(Model())
        checker.check('', [], 'ответ')
        self.assertFalse(checker.last['valid'])
        self.assertIsNone(checker.last['consistent'])


class RunnerTests(unittest.TestCase):
    def test_timings_failure_and_artifacts(self):
        from fable.config import Settings
        from fable.evaluation.configurations import PRESETS
        from fable.evaluation.scenarios import load_scenarios
        from fable.evaluation.runner import run_experiments
        class Agent:
            def __init__(self, state):
                self.calls = 0
                self.state = state
            def stream(self, messages):
                self.calls += 1
                if self.calls == 2:
                    self.state.update(add_inventory=['ошибочный предмет'])
                    yield 'часть'
                    raise RuntimeError('сбой')
                if self.state.inventory:
                    raise AssertionError('Состояние не было откачено')
                yield 'А'
                yield 'Б'
        ticks = iter(i / 100 for i in range(100))
        scenario = load_scenarios(Path('eval/scenarios'))[0]
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='fake')
        with tempfile.TemporaryDirectory() as directory:
            result = run_experiments([scenario], [PRESETS['agentic_full']], ['fake'], settings,
                                     Path(directory), dry_run=True, turns=2, clock=lambda: next(ticks),
                                     agent_factory=lambda settings, setup, state, config: Agent(state), progress=lambda text: None)
            records = [json.loads(line) for line in Path(directory, 'runs.jsonl').read_text().splitlines()]
            self.assertEqual(len(records), 3)
            self.assertAlmostEqual(records[0]['ttft_ms'], 10)
            self.assertAlmostEqual(records[0]['total_ms'], 20)
            self.assertEqual(records[0]['reply_chars'], 2)
            self.assertIn('сбой', records[1]['error'])
            self.assertIsNone(records[1]['consistency'])
            self.assertEqual(records[2]['reply'], 'АБ')
            self.assertTrue(records[2]['consistency']['valid'])
            snapshot = json.loads(next(Path(directory, 'snapshots').glob('*.json')).read_text())
            self.assertEqual(snapshot['state']['inventory'], [])
            history = snapshot['session']['history']
            self.assertNotIn('часть', [m['content'] for m in history])
            self.assertEqual(len(list(Path(directory, 'transcripts').glob('*.md'))), 1)
            self.assertTrue(Path(directory, 'summary.csv').is_file())
            self.assertEqual(result, Path(directory, 'summary.md'))
            self.assertIn('agentic_full', result.read_text())

    def test_aggregation_math(self):
        from fable.evaluation.reporting import aggregate
        from fable.infrastructure.evaluation_judge import SCORE_KEYS
        runs = [dict(scenario='s', config='c', model='m', turns=[
            dict(ttft_ms=10, total_ms=30, reply_chars=20, error=None, consistency=dict(valid=True, consistent=True)),
            dict(ttft_ms=30, total_ms=70, reply_chars=60, error=None, consistency=dict(valid=True, consistent=False)),
            dict(ttft_ms=None, total_ms=20, reply_chars=0, error='fail', consistency=None),
        ], judge=dict(valid=True, **dict.fromkeys(SCORE_KEYS, 4), probes=[
            dict(eligible=True, valid=True, status='respected'), dict(eligible=True, valid=True, status='ignored')]))]
        row = aggregate(runs)[0]
        self.assertEqual(row['mean_ttft_ms'], 20)
        self.assertEqual(row['median_ttft_ms'], 20)
        self.assertEqual(row['mean_total_ms'], 40)
        self.assertEqual(row['mean_reply_chars'], 40)
        self.assertEqual(row['consistency_failure_rate'], .5)
        self.assertEqual(row['judge_json_valid_rate'], 1)
        self.assertEqual(row['probe_recall_rate'], .5)
        self.assertEqual(row['coherence'], 4)

    def test_missing_and_invalid_denominators(self):
        from fable.evaluation.reporting import aggregate
        run: dict = dict(scenario='s', config='c', model='m', turns=[
            dict(ttft_ms=None, total_ms=10, reply_chars=0, error=None,
                 consistency=dict(valid=False, consistent=None))],
            judge=dict(valid=False, probes=[dict(eligible=True, valid=False),
                                          dict(eligible=False, valid=False)]))
        row = aggregate([run])[0]
        self.assertIsNone(row['mean_ttft_ms'])
        self.assertIsNone(row['consistency_failure_rate'])
        self.assertEqual(row['consistency_json_valid_rate'], 0)
        self.assertEqual(row['judge_json_valid_rate'], 0)
        self.assertEqual(row['probe_recall_rate'], 0)
        self.assertEqual(row['probes'], 1)
        self.assertIsNone(row['coherence'])
        run['turns'][0]['consistency'] = None
        run['judge']['probes'] = []
        row = aggregate([run])[0]
        self.assertIsNone(row['consistency_json_valid_rate'])
        self.assertIsNone(row['probe_recall_rate'])

    def test_skips_and_repetitions_are_explicit(self):
        from fable.config import Settings
        from fable.evaluation.configurations import PRESETS
        from fable.evaluation.scenarios import load_scenarios
        from fable.evaluation.runner import run_experiments
        scenario = next(s for s in load_scenarios(Path('eval/scenarios')) if s.id == 'lirielle')
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='fake')
        with tempfile.TemporaryDirectory() as directory:
            run_experiments([scenario], [PRESETS[n] for n in ['static', 'agentic_memory', 'agentic_full_companions']],
                            ['model/a', 'model_a'], settings, Path(directory), dry_run=True, turns=1,
                            repeat=2, progress=lambda _: None)
            self.assertEqual(len(list(Path(directory, 'transcripts').glob('*.md'))), 4)
            manifest = json.loads(Path(directory, 'manifest.json').read_text())
            self.assertEqual(len(manifest['skipped']), 8)
            self.assertIn('EMBEDDING_MODEL', str(manifest['skipped']))


class CLITests(unittest.TestCase):
    def test_dry_run_end_to_end(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'fable.evaluation.cli', '--dry-run',
                                     '--scenarios', 'eval/scenarios', '--configs', 'static,agentic_full',
                                     '--model', 'X', '--model', 'Y', '--judge-model', 'Z', '--turns', '2',
                                     '--repeat', '2', '--override', 'agentic_full.history_limit=4', '--out', directory],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('summary.md', result.stdout)
            records = Path(directory, 'runs.jsonl').read_text().splitlines()
            self.assertEqual(len(records), 72)
            self.assertEqual(len(list(Path(directory, 'transcripts').glob('*.md'))), 24)
            manifest = json.loads(Path(directory, 'manifest.json').read_text())
            self.assertEqual(manifest['configurations'][1]['history_limit'], 4)
            self.assertTrue(manifest['dry_run'])
            self.assertIn('ОФЛАЙН-ДЕМО', Path(directory, 'summary.md').read_text())

    def test_invalid_options_are_rejected(self):
        from fable.evaluation.cli import main
        from contextlib import redirect_stderr
        import io
        for args in [['--configs', 'missing'], ['--repeat', '0'], ['--turns', '-1'],
                     ['--override', 'static.history_limit=1'], ['--override', 'static.memory=true']]:
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(['--dry-run', *args])
            self.assertEqual(raised.exception.code, 2)


class ScenarioTests(unittest.TestCase):
    def test_scenarios_and_validation(self):
        from fable.evaluation.scenarios import load_scenarios, parse_scenario
        scenarios = load_scenarios(Path('eval/scenarios'))
        self.assertEqual(len(scenarios), 3)
        self.assertGreaterEqual(max(len(s.actions) for s in scenarios), 20)
        long = next(s for s in scenarios if s.id == 'long_recall')
        self.assertNotIn('ключ', long.setup.story.casefold())
        self.assertIn('синей нитью', long.actions[1])
        self.assertNotIn('ключ', long.actions[17])
        source = {'id': 'bad/id', 'title': 'x', 'setup': {}, 'actions': []}
        with self.assertRaisesRegex(ValueError, 'id'):
            parse_scenario(source)
        source = scenarios[0].to_dict()
        for key, value in [('actions', ['']), ('probes', [{'after_turn': True, 'fact': 'x'}]),
                           ('setup', {'world': 4})]:
            bad = {**source, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_scenario(bad)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'bad.json').write_text('{')
            with self.assertRaisesRegex(ValueError, 'bad.json'):
                load_scenarios(Path(directory))
