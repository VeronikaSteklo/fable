import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from pydantic import BaseModel
from openai import APIStatusError, BadRequestError
import httpx

from fable.config import Settings
from fable.infrastructure.llm.client import ChatModel, build_client, thinking_extra_body
from fable.infrastructure.llm.structured import complete_structured


def response(text):
    return NS(choices=[NS(message=NS(content=text))])


class Verdict(BaseModel):
    ok: bool


class OpenAIClientTests(unittest.TestCase):
    def test_client_settings_and_thinking(self):
        settings = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='test',
                            llm_timeout_seconds=17, llm_max_retries=0)
        with patch('fable.infrastructure.llm.client.OpenAI') as constructor:
            build_client(settings)
        constructor.assert_called_once_with(api_key='fake', base_url=settings.base_url, timeout=17, max_retries=0)
        self.assertEqual(thinking_extra_body(settings), {'chat_template_kwargs': {'enable_thinking': False}})
        for level in ('low', 'medium', 'xhigh'):
            configured = Settings(_env_file=None, api_key='fake', base_url=settings.base_url, model='test', enable_thinking=level)
            self.assertEqual(thinking_extra_body(configured), {'chat_template_kwargs': {'enable_thinking': True}, 'reasoning_effort': level})

    def test_schema_success_is_validated(self):
        client = Mock()
        client.chat.completions.create.return_value = response('{"ok":true}')
        result = complete_structured(ChatModel(client, 'test'), [], Verdict)
        self.assertTrue(result.parsed.ok)
        fmt = client.chat.completions.create.call_args.kwargs['response_format']
        self.assertEqual(fmt['type'], 'json_schema')
        self.assertTrue(fmt['json_schema']['strict'])
        self.assertFalse(fmt['json_schema']['schema']['additionalProperties'])

    def test_unsupported_formats_fall_back_to_prompt(self):
        client = Mock()
        error = BadRequestError('response_format is unsupported', response=httpx.Response(400, request=httpx.Request('POST', 'http://offline.invalid')), body=None)
        client.chat.completions.create.side_effect = [error, error, response('```json\n{"ok":true}\n```')]
        result = complete_structured(ChatModel(client, 'test'), [], Verdict)
        self.assertIsNone(result.parsed)
        calls = client.chat.completions.create.call_args_list
        self.assertEqual([c.kwargs.get('response_format', {}).get('type') for c in calls], ['json_schema', 'json_object', None])
        self.assertIn('JSON', calls[-1].kwargs['messages'][0]['content'])

    def test_local_server_format_errors_fall_back(self):
        for status, message in [(400, "response_format type must be 'text' or 'json_object'"),
                                (501, 'json_schema is not implemented')]:
            client = Mock()
            error = APIStatusError(message, response=httpx.Response(
                status, request=httpx.Request('POST', 'http://offline.invalid')), body=None)
            client.chat.completions.create.side_effect = [error, response('{"ok":true}')]
            self.assertTrue(complete_structured(ChatModel(client, 'test'), [], Verdict).parsed.ok)
            self.assertEqual(client.chat.completions.create.call_args.kwargs['response_format']['type'], 'json_object')

    def test_invalid_output_and_unrelated_error_do_not_retry(self):
        client = Mock()
        client.chat.completions.create.return_value = response('{"ok":"invalid"}')
        self.assertIsNone(complete_structured(ChatModel(client, 'test'), [], Verdict).parsed)
        client.chat.completions.create.assert_called_once()
        client.chat.completions.create.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            complete_structured(ChatModel(client, 'test'), [], Verdict)

    def test_modes(self):
        for mode in ('json_object', 'prompt'):
            client = Mock()
            client.chat.completions.create.return_value = response('{"ok":true}')
            result = complete_structured(ChatModel(client, 'test', structured_output=mode), [], Verdict)
            self.assertTrue(result.parsed.ok)
            kwargs = client.chat.completions.create.call_args.kwargs
            self.assertEqual('response_format' in kwargs, mode == 'json_object')
