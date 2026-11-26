from types import SimpleNamespace as NS
import unittest

from fable.application.usage import UsageMeter
from fable.infrastructure.llm.client import ChatModel


def response(usage=True):
    return NS(choices=[NS(message=NS(content='abcd'))], usage=NS(prompt_tokens=8, completion_tokens=2, total_tokens=10) if usage else None)


class Completions:
    def __init__(self, reject=False, missing=False):
        self.calls = []
        self.reject, self.missing = reject, missing

    def create(self, **options):
        self.calls.append(options)
        if self.reject and 'stream_options' in options:
            raise ValueError('stream_options unsupported')
        if options.get('stream'):
            return iter([NS(choices=[NS(delta=NS(content='abcd', tool_calls=None))], usage=None),
                         NS(choices=[], usage=response(not self.missing).usage)])
        return response(not self.missing)


class ClientUsageTests(unittest.TestCase):
    def model(self, **options):
        completions = Completions(**options)
        return ChatModel(NS(chat=NS(completions=completions)), 'm'), completions

    def test_nonstream_and_stream(self):
        model, fake = self.model()
        meter = UsageMeter()
        def calls():
            self.assertEqual(model.complete([{'role': 'user', 'content': 'hi'}]), 'abcd')
            yield from model.stream([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(list(meter.iterate(calls())), ['abcd'])
        self.assertEqual(meter.summary()['total_tokens'], 20)
        self.assertFalse(meter.summary()['estimated'])
        self.assertEqual(fake.calls[-1]['stream_options'], {'include_usage': True})

    def test_unsupported_is_remembered_and_estimated(self):
        model, fake = self.model(reject=True, missing=True)
        meter = UsageMeter()
        def calls():
            yield from model.stream([{'role': 'user', 'content': 'abcdefgh'}])
            yield from model.stream([{'role': 'user', 'content': 'abcdefgh'}])
        list(meter.iterate(calls()))
        self.assertEqual(len(fake.calls), 3)
        self.assertNotIn('stream_options', fake.calls[-1])
        self.assertEqual(meter.summary()['llm_calls'], 3)
        self.assertTrue(meter.summary()['estimated'])
        self.assertGreater(meter.summary()['completion_tokens'], 0)

    def test_missing_nonstream_usage(self):
        model, _ = self.model(missing=True)
        meter = UsageMeter()
        def calls():
            yield model.complete([{'role': 'user', 'content': 'abcdefgh'}])
        list(meter.iterate(calls()))
        self.assertTrue(meter.summary()['estimated'])
        self.assertEqual(meter.summary()['completion_tokens'], 1)

    def test_unrelated_stream_error_does_not_retry(self):
        model, fake = self.model()
        def fail(**options):
            fake.calls.append(options)
            raise RuntimeError('connection unavailable')
        fake.create = fail
        model.client.chat.completions.create = fail
        meter = UsageMeter()
        def calls():
            yield from model.stream([])
        with self.assertRaises(RuntimeError):
            list(meter.iterate(calls()))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(meter.summary()['llm_calls'], 1)

    def test_actual_api_unsupported_error_body_and_memory(self):
        import httpx
        from openai import BadRequestError
        model, fake = self.model()
        original = fake.create
        def create(**options):
            if 'stream_options' in options:
                fake.calls.append(options)
                raise BadRequestError('invalid request', response=httpx.Response(400,
                    request=httpx.Request('POST', 'http://offline.invalid')),
                    body={'error': 'stream_options: extra inputs are not permitted'})
            return original(**options)
        model.client.chat.completions.create = create
        meter = UsageMeter()
        def calls():
            yield from model.stream([])
            yield from model.stream([])
        list(meter.iterate(calls()))
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(meter.summary()['llm_calls'], 3)

    def test_tool_schemas_and_arguments_are_in_estimate(self):
        model, _ = self.model(missing=True)
        meter = UsageMeter()
        def calls():
            yield model.create([], tools=[{'type': 'function', 'function': {'name': 'big', 'description': 'x' * 400}}])
        list(meter.iterate(calls()))
        self.assertGreater(meter.summary()['prompt_tokens'], 100)
