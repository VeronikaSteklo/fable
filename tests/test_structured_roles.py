"""Role contracts tested through fake official-SDK client objects, never the network."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from fable import bootstrap
from fable.config import Settings
from fable.domain.consistency import ConsistencyVerdict
from fable.domain.state import GameState
from fable.evaluation.scenarios import load_scenarios
from fable.infrastructure.evaluation_judge import LLMJudge, ObservedConsistencyChecker, SCORE_KEYS
from fable.infrastructure.llm_consistency import LLMConsistencyChecker
from fable.infrastructure.llm_moderator import LLMModerator
from fable.infrastructure.openai_client import ChatModel
from test_chroma_memory import make_setup
from test_llm_summarizer import FakeModel
from test_master_agent import chunk


class StructuredRoleTests(unittest.TestCase):
    def test_moderator_schema_and_legacy_fences(self):
        payload = {'allowed': False, 'category': 'self_harm_methods', 'reason': 'Причина'}
        for raw in [json.dumps(payload), '```json\n' + json.dumps(payload) + '\n```']:
            model = FakeModel(raw)
            verdict = LLMModerator(model).check('Текст')
            self.assertFalse(verdict.allowed)
            self.assertEqual(verdict.reason, 'Причина')
            self.assertEqual(model.options[0]['response_format']['json_schema']['name'], 'ModerationOutput')

    def test_moderator_invalid_and_api_errors_allow(self):
        for raw in ['garbage', '{"allowed":false,"category":"unknown"}', 'null', '[]']:
            self.assertTrue(LLMModerator(FakeModel(raw)).check('Текст').allowed)
        with self.assertLogs('fable.infrastructure.llm_moderator', 'WARNING'):
            self.assertTrue(LLMModerator(FakeModel(error=RuntimeError('offline'))).check('Текст').allowed)

    def test_consistency_invalid_output_fails_open_but_metrics_stay_invalid(self):
        for raw in ['garbage', '{"consistent":"false","issues":[]}', '{"consistent":false,"issues":[2]}']:
            self.assertEqual(LLMConsistencyChecker(FakeModel(raw)).check('', [], ''), ConsistencyVerdict.ok())
            observed = ObservedConsistencyChecker(FakeModel(raw))
            self.assertEqual(observed.check('', [], ''), ConsistencyVerdict.ok())
            self.assertFalse(observed.last['valid'])
            self.assertIsNone(observed.last['consistent'])
            self.assertEqual(observed.last['raw'], raw)

    def test_observed_consistency_preserves_fenced_parser(self):
        model = FakeModel('```json\n{"consistent":false,"issues":["Ошибка"]}\n```')
        checker = ObservedConsistencyChecker(model)
        self.assertEqual(checker.check('Мир', [], 'Сцена'), ConsistencyVerdict(False, ('Ошибка',)))
        self.assertTrue(checker.last['valid'])
        self.assertEqual(model.options[0]['response_format']['json_schema']['name'], 'ConsistencyOutput')

    def test_judge_invalid_output_is_not_a_score(self):
        scenario = load_scenarios(Path('eval/scenarios'))[0]
        for raw in ['garbage', json.dumps({**dict.fromkeys(SCORE_KEYS, 8), 'justification': 'bad'})]:
            result = LLMJudge(FakeModel(raw)).evaluate(scenario, [{'turn': 0, 'reply': 'Сцена'}])
            self.assertFalse(result['valid'])
            self.assertEqual(result['raw'], raw)
            self.assertNotIn('coherence', result)

    def test_judge_fenced_scores_and_probe_schema(self):
        model = FakeModel('```json\n' + json.dumps({**dict.fromkeys(SCORE_KEYS, 4), 'justification': 'Верно'}) + '\n```')
        judge = LLMJudge(model)
        scenario = load_scenarios(Path('eval/scenarios'))[0]
        self.assertTrue(judge.evaluate(scenario, [{'turn': 0, 'reply': 'Сцена'}])['valid'])
        self.assertEqual(model.options[0]['response_format']['json_schema']['name'], 'JudgmentOutput')
        model.text = '{"status":"respected","justification":"Верно"}'
        result = judge.evaluate(scenario, [{'turn': 10, 'reply': 'Сцена'}])
        self.assertTrue(result['probes'][0]['valid'])
        self.assertEqual(model.options[-1]['response_format']['json_schema']['name'], 'ProbeOutput')

    def test_bootstrap_builds_all_adapters_offline(self):
        from test_companions import setup_with
        from fable.domain.companion import Companion
        setup = setup_with(Companion('Лис', 'Разведчик', 'Осторожный'))
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='test',
                            embedding_model='embed', structured_output='prompt')
        client = Mock()
        client.chat.completions.create.side_effect = [
            iter([chunk('Сцена', finish='stop')]),
            NS(choices=[NS(message=NS(content='{"consistent":true,"issues":[]}'))]),
        ]
        with patch('fable.infrastructure.openai_client.OpenAI', return_value=client), \
                patch('fable.infrastructure.chroma_memory.chromadb.PersistentClient') as chroma:
            session = bootstrap.create_session(settings, setup, GameState.for_setup(setup))
            self.assertEqual(session.start(), 'Сцена')
        master = session._agent
        self.assertEqual(len(master._tools), 6)
        self.assertIsInstance(session._summarizer._model, ChatModel)
        self.assertIsInstance(session._checker._model, ChatModel)
        self.assertIsInstance(session._guardrail._guardrails[-1]._model, ChatModel)
        self.assertEqual(session._checker._model.structured_output, 'prompt')
        chroma.assert_called_once_with(path=str(settings.memory_store_path))
        master_request, check_request = [c.kwargs for c in client.chat.completions.create.call_args_list]
        self.assertEqual(master_request['extra_body'], {'chat_template_kwargs': {'enable_thinking': False}})
        self.assertNotIn('extra_body', check_request)
        self.assertNotIn('response_format', check_request)
