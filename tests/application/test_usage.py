import unittest

from fable.application.usage import TokenUsage, UsageRecord, UsageMeter, record_usage, compute_cost


class UsageTests(unittest.TestCase):
    def test_sum_cost_and_scoping(self):
        usage = TokenUsage(100, 50, 150)
        self.assertEqual((usage + usage).total_tokens, 300)
        self.assertAlmostEqual(compute_cost(usage, 'm', {'m': {'input': 2, 'output': 4}}), .0004)
        self.assertIsNone(compute_cost(usage, 'local', {}))
        def calls():
            record_usage(UsageRecord('master', 'm', usage, 1))
            yield 'a'
            record_usage(UsageRecord('companion', 'm', usage, 2, estimated=True))
        first, second = UsageMeter(), UsageMeter()
        stream = first.iterate(calls())
        self.assertEqual(next(stream), 'a')
        record_usage(UsageRecord('plain', 'm', usage, 1))
        list(second.iterate(iter([])))
        list(stream)
        self.assertEqual(first.summary()['llm_calls'], 2)
        self.assertTrue(first.summary()['estimated'])
        self.assertEqual(second.summary()['llm_calls'], 0)

    def test_context_can_change_between_generator_advances(self):
        from contextvars import Context
        meter = UsageMeter()
        def calls():
            record_usage(UsageRecord('master', 'm', TokenUsage(1, 1, 2), 1))
            yield 'a'
            record_usage(UsageRecord('companion', 'm', TokenUsage(1, 1, 2), 1))
        stream = meter.iterate(calls())
        self.assertEqual(Context().run(next, stream), 'a')
        self.assertEqual(Context().run(lambda: list(stream)), [])
        self.assertEqual(meter.summary()['total_tokens'], 4)

    def test_prices_validate_required_rates_and_json_environment(self):
        import os
        from unittest.mock import patch
        from pydantic import ValidationError
        from fable.config import Settings
        options = dict(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='m')
        with patch.dict(os.environ, {'MODEL_PRICES': '{"m":{"input":2,"output":4}}'}):
            self.assertEqual(Settings(**options).model_prices['m']['input'], 2)
        for price in ({}, {'input': 1}, {'input': -1, 'output': 1}):
            with self.assertRaises(ValidationError):
                Settings(**options, model_prices={'m': price})
