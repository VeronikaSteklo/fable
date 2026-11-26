import copy
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from fable.config import Settings
from fable.domain.state import GameState
from fable.infrastructure.master_agent import GameMasterAgent


def chunk(content=None, calls=(), finish=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=list(calls)), finish_reason=finish)])


def call(index=0, name=None, args='', id=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return iter(self.responses.pop(0))


def settings(**kwargs):
    return Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='test', **kwargs)


class GameMasterAgentTests(unittest.TestCase):
    def master(self, client, **options):
        with patch('fable.infrastructure.master_agent.build_client', return_value=client):
            return GameMasterAgent(settings(**options), 'Роль', GameState())

    def test_configures_sdk_and_streams_text_only(self):
        client = FakeClient([NS(choices=[]), chunk('Сцена '), chunk('готова', finish='stop')])
        master = self.master(client, enable_thinking='xhigh', temperature=.25)
        messages = [{'role': 'user', 'content': 'Начни'}]
        self.assertEqual(list(master.stream(messages)), ['Сцена ', 'готова'])
        request = client.requests[0]
        self.assertEqual(request['messages'], [{'role': 'system', 'content': 'Роль'}, *messages])
        self.assertTrue(request['stream'])
        self.assertEqual(request['model'], 'test')
        self.assertEqual(request['temperature'], .25)
        self.assertEqual(request['extra_body'], {'chat_template_kwargs': {'enable_thinking': True}, 'reasoning_effort': 'xhigh'})
        self.assertEqual([t['function']['name'] for t in request['tools']], ['read_game_state', 'update_game_state'])
        self.assertEqual(messages, [{'role': 'user', 'content': 'Начни'}])

    def test_tool_round_preserves_content_and_split_arguments(self):
        client = FakeClient([
            chunk('Вступление', [call(name='update_game_state', args='{"loc', id='update')]),
            chunk(calls=[call(args='ation":"Башня"}')], finish='tool_calls'),
        ], [chunk('Финал', finish='stop')])
        master = self.master(client)
        self.assertEqual(list(master.stream([])), ['Вступление', 'Финал'])
        messages = client.requests[1]['messages']
        self.assertEqual(messages[1]['content'], 'Вступление')
        self.assertEqual(messages[1]['tool_calls'][0]['function']['arguments'], '{"location":"Башня"}')
        self.assertEqual(messages[2]['tool_call_id'], 'update')
        self.assertIn('Башня', messages[2]['content'])
        self.assertEqual(master._state.location, 'Башня')

    def test_parallel_calls_execute_in_index_order(self):
        client = FakeClient([chunk(calls=[
            call(1, 'read_game_state', '{}', 'read'),
            call(0, 'update_game_state', '{"location":"Башня"}', 'update'),
        ], finish='tool_calls')], [chunk('Сцена', finish='stop')])
        self.assertEqual(list(self.master(client).stream([])), ['Сцена'])
        results = [m for m in client.requests[1]['messages'] if m['role'] == 'tool']
        self.assertEqual([m['tool_call_id'] for m in results], ['update', 'read'])
        self.assertIn('Башня', results[1]['content'])

    def test_unknown_and_invalid_arguments_are_errors_and_turn_continues(self):
        for name, args in [('missing', '{}'), ('update_game_state', '{broken'),
                           ('update_game_state', '{"location":42}'), ('read_game_state', '[]')]:
            with self.subTest(name=name, args=args):
                client = FakeClient([chunk(calls=[call(name=name, args=args, id='bad')], finish='tool_calls')],
                                    [chunk('Продолжение', finish='stop')])
                self.assertEqual(list(self.master(client).stream([])), ['Продолжение'])
                self.assertIn('Ошибка', client.requests[1]['messages'][-1]['content'])

    def test_handler_error_is_tool_result_not_scene(self):
        from unittest.mock import Mock
        memory = Mock()
        memory.remember.side_effect = RuntimeError('Хранилище недоступно')
        client = FakeClient([chunk(calls=[call(name='remember_story_event', args='{"event":"Факт"}', id='save')], finish='tool_calls')],
                            [chunk('Продолжаем', finish='stop')])
        with patch('fable.infrastructure.master_agent.build_client', return_value=client):
            master = GameMasterAgent(settings(), 'Роль', GameState(), memory)
        self.assertEqual(list(master.stream([])), ['Продолжаем'])
        self.assertIn('Ошибка', client.requests[-1]['messages'][-1]['content'])
        self.assertIn('Хранилище недоступно', client.requests[-1]['messages'][-1]['content'])

    def test_sdk_stream_closes_on_cancellation_and_failure(self):
        from unittest.mock import Mock
        for fails in (False, True):
            closed = []
            def events():
                try:
                    yield chunk('Часть')
                    if fails:
                        raise RuntimeError('Обрыв')
                    yield chunk('Конец')
                finally:
                    closed.append(True)
            client = Mock()
            client.chat.completions.create.return_value = events()
            stream = self.master(client).stream([])
            self.assertEqual(next(stream), 'Часть')
            if fails:
                with self.assertRaises(RuntimeError):
                    next(stream)
            else:
                stream.close()
            self.assertEqual(closed, [True])

    def test_cap_forces_final_call_without_executing_more_tools(self):
        client = FakeClient([chunk(calls=[call(name='read_game_state', args='{}', id='read')], finish='tool_calls')],
                            [chunk('Конец', finish='stop')])
        self.assertEqual(list(self.master(client, max_tool_rounds=1).stream([])), ['Конец'])
        self.assertEqual(client.requests[-1]['tool_choice'], 'none')
        client = FakeClient([chunk('Без инструментов', finish='stop')])
        self.assertEqual(list(self.master(client, max_tool_rounds=0).stream([])), ['Без инструментов'])
        self.assertEqual(client.requests[0]['tool_choice'], 'none')
