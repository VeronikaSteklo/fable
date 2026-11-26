import unittest

from fable.application.game.session import GameSession
from fable.application.usage import TokenUsage, UsageRecord, record_usage
from fable.domain.safety.consistency import ConsistencyVerdict


def count(role):
    record_usage(UsageRecord(role, 'm', TokenUsage(8, 2, 10), 1))


class Agent:
    fail = False
    def stream(self, messages):
        count('master')
        count('companion')
        yield 'scene'
        if self.fail:
            raise RuntimeError('offline failure')


class Checker:
    def check(self, *args):
        count('consistency')
        return ConsistencyVerdict.ok()


class Summary:
    def summarize(self, *args):
        count('summarizer')
        return 'summary'


class Guard:
    def check(self, text):
        from fable.domain.safety.safety import SafetyVerdict
        count('moderator')
        return SafetyVerdict.allow()


class SessionUsageTests(unittest.TestCase):
    def test_all_roles_scoped_and_history_metadata_not_sent(self):
        session = GameSession(Agent(), 2, Guard(), checker=Checker(), summarizer=Summary(),
                              model_prices={'m': {'input': 1, 'output': 2}})
        session.start()
        session.send_action('one')
        session.send_action('two')
        usage = session.to_snapshot()['history'][-1]['usage']
        self.assertEqual(usage['llm_calls'], 5)
        self.assertEqual(set(usage['by_role']), {'master', 'companion', 'consistency', 'moderator', 'summarizer'})
        self.assertEqual(session.usage_total['llm_calls'], 12)
        self.assertIsNotNone(usage['cost_usd'])
        self.assertNotIn('usage', session._messages_for_request()[-1])

    def test_legacy_snapshot_without_usage_stays_loadable(self):
        session = GameSession(Agent(), 16)
        session.start()
        snapshot = session.to_snapshot()
        snapshot['history'][-1].pop('usage')
        restored = GameSession.from_snapshot(snapshot, agent=Agent(), history_limit=16,
                                             model_prices={'m': {'input': 1, 'output': 2}})
        self.assertEqual(restored.usage_total['total_tokens'], 0)
        self.assertIsNone(restored.usage_total['cost_usd'])
        restored.send_action('new')
        self.assertEqual(restored.usage_total['total_tokens'], 20)
        self.assertIsNotNone(restored.last_usage['cost_usd'])
        self.assertIsNone(restored.usage_total['cost_usd'])

    def test_failure_does_not_attach_usage_to_reply(self):
        agent = Agent()
        session = GameSession(agent, 16)
        session.start()
        before = session.to_snapshot()
        agent.fail = True
        with self.assertRaises(RuntimeError):
            session.send_action('bad')
        self.assertEqual(session.to_snapshot(), before)
        self.assertIsNone(session.last_usage)
        self.assertEqual(session.last_attempt_usage['llm_calls'], 2)
        agent.fail = False
        session.send_action('ok')
        self.assertEqual(session.last_usage['llm_calls'], 2)
