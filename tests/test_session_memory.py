import unittest

from fable.application.session import GameSession
from test_session import FakeAgent


class FakeSummarizer:
    def __init__(self):
        self.calls = []
        self.fail = False

    def summarize(self, previous_summary, messages):
        self.calls.append((previous_summary, messages))
        if self.fail:
            raise RuntimeError("недоступен")
        return previous_summary + "Важные события."


class SessionMemoryTests(unittest.TestCase):
    def test_summary_folds_complete_turns_and_preserves_full_history(self):
        agent = FakeAgent(["Начало", "Ответ 1", "Ответ 2", "Ответ 3"])
        summarizer = FakeSummarizer()
        session = GameSession(agent, 4, summarizer=summarizer)
        session.start()
        session.send_action("Ход 1")
        session.send_action("Ход 2")
        self.assertEqual(summarizer.calls, [])
        session.send_action("Ход 3")
        self.assertEqual(summarizer.calls[0][1], [
            {"role": "assistant", "content": "Начало"},
            {"role": "user", "content": "Ход 1"},
            {"role": "assistant", "content": "Ответ 1"},
        ])
        self.assertEqual(session.summary, "Важные события.")
        self.assertIn("Краткое содержание прошлых событий", agent.requests[-1][0]["content"])
        self.assertEqual(agent.requests[-1][1:],[
            {"role": "user", "content": "Ход 2"},
            {"role": "assistant", "content": "Ответ 2"},
            {"role": "user", "content": "Ход 3"},
        ])
        self.assertEqual(len(session.to_snapshot()["history"]), 8)
        self.assertEqual(session.to_snapshot()["summarized_count"], 3)

    def test_unchanged_summary_is_retried_without_advancing_pointer(self):
        class UnchangedSummarizer:
            def __init__(self):
                self.calls = []

            def summarize(self, previous_summary, messages):
                self.calls.append(messages)
                return previous_summary

        summarizer = UnchangedSummarizer()
        session = GameSession(FakeAgent(["Начало", "1", "2", "3", "4"]), 4,
                              summarizer=summarizer)
        session.start()
        for action in ["1", "2", "3", "4"]:
            session.send_action(action)
        self.assertEqual(len(summarizer.calls), 2)
        self.assertEqual(session.to_snapshot()["summarized_count"], 0)
        self.assertEqual(len(session.to_snapshot()["history"]), 10)
        self.assertEqual(summarizer.calls[1][:len(summarizer.calls[0])], summarizer.calls[0])

    def test_summary_failure_keeps_pointer_and_retries(self):
        agent = FakeAgent(["Начало", "Один", "Два", "Три", "Четыре"])
        summarizer = FakeSummarizer()
        summarizer.fail = True
        session = GameSession(agent, 4, summarizer=summarizer)
        session.start()
        for action in ["1", "2"]:
            session.send_action(action)
        with self.assertLogs("fable.application.session", "WARNING"):
            session.send_action("3")
        self.assertEqual(session.summary, "")
        self.assertEqual(session.to_snapshot()["summarized_count"], 0)
        self.assertEqual(len(session.to_snapshot()["history"]), 8)
        self.assertLessEqual(len(agent.requests[-1]), 4)
        summarizer.fail = False
        session.send_action("4")
        self.assertEqual(summarizer.calls[1][1][:3], summarizer.calls[0][1])
        self.assertGreater(session.to_snapshot()["summarized_count"], 0)
