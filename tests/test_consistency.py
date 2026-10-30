import unittest

from fable.domain.consistency import ConsistencyVerdict
from fable.infrastructure.llm_consistency import LLMConsistencyChecker, parse_consistency_verdict
from fable.application.session import GameSession
from test_session import FakeAgent
from test_llm_summarizer import FakeModel


class SequenceChecker:
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def check(self, context, recent, reply):
        self.calls.append((context, recent, reply))
        return self.verdicts.pop(0)


class ConsistencyTests(unittest.TestCase):
    def test_parser_handles_json_fences_and_rejects_malformed_values(self):
        bad = ConsistencyVerdict(False, ("Герой решил сам",))
        self.assertEqual(parse_consistency_verdict(
            '```json\n{"consistent": false, "issues": ["Герой решил сам"]}\n```'), bad)
        self.assertEqual(parse_consistency_verdict('{"consistent":true,"issues":[]}'), ConsistencyVerdict.ok())
        for raw in ["", "no", "[]", "null", "{bad}", '{}',
                    '{"consistent":"false","issues":[]}',
                    '{"consistent":false,"issues":"ошибка"}',
                    '{"consistent":false,"issues":[2]}',
                    '{"consistent":false}', '{"consistent":0,"issues":[]}']:
            with self.subTest(raw=raw):
                self.assertEqual(parse_consistency_verdict(raw), ConsistencyVerdict.ok())

    def test_llm_checker_sends_context_and_reply_and_fails_open(self):
        model = FakeModel('{"consistent":false,"issues":["Мир изменился"]}')
        checker = LLMConsistencyChecker(model)
        verdict = checker.check("Герой в башне", [{"role":"user", "content":"Жду"}], "Герой убежал")
        self.assertFalse(verdict.consistent)
        sent = model.requests[0][1]["content"]
        for text in ["Герой в башне", "Жду", "Герой убежал"]:
            self.assertIn(text, sent)
        with self.assertLogs("fable.infrastructure.llm_consistency", "WARNING"):
            result = LLMConsistencyChecker(FakeModel(error=RuntimeError("сбой"))).check("", [], "")
        self.assertEqual(result, ConsistencyVerdict.ok())

    def test_note_is_sent_once_and_verdicts_are_kept_out_of_model_metadata(self):
        bad = ConsistencyVerdict(False, ("Не решай за героя",))
        checker = SequenceChecker([bad, ConsistencyVerdict.ok(), ConsistencyVerdict.ok()])
        agent = FakeAgent(["Начало", "Продолжение", "Финал"])
        session = GameSession(agent, 16, checker=checker, context_provider=lambda: "Мир и состояние")
        self.assertIsNone(session.last_verdict)
        session.start()
        self.assertEqual(session.last_verdict, bad)
        self.assertEqual(checker.calls[0][0], "Мир и состояние")
        session.send_action("Осматриваюсь")
        self.assertIn("Замечание проверки согласованности", agent.requests[1][-1]["content"])
        self.assertIn("Осматриваюсь", agent.requests[1][-2]["content"])
        self.assertEqual(checker.calls[1][1][-1], {"role":"user", "content":"Осматриваюсь"})
        session.send_action("Жду")
        self.assertNotIn("Замечание проверки", str(agent.requests[2]))
        snapshot = session.to_snapshot()
        self.assertNotIn("Замечание проверки", str(snapshot["history"]))
        self.assertEqual(snapshot["history"][1]["consistency"], {"consistent": False, "issues": ["Не решай за героя"]})
        for request in agent.requests:
            self.assertTrue(all(set(message) == {"role", "content"} for message in request))

    def test_failed_reply_keeps_pending_note_for_retry(self):
        class RetryAgent:
            def __init__(self):
                self.requests = []

            def stream(self, messages):
                self.requests.append(messages)
                if len(self.requests) == 2:
                    yield "Незаконченный ответ"
                    raise RuntimeError("сбой")
                yield "Сцена"

        agent = RetryAgent()
        checker = SequenceChecker([
            ConsistencyVerdict(False, ("Не решай за героя",)),
            ConsistencyVerdict.ok(),
        ])
        session = GameSession(agent, 16, checker=checker)
        session.start()
        note = session.to_snapshot()["pending_note"]
        history = session.to_snapshot()["history"]
        with self.assertRaises(RuntimeError):
            session.send_action("Осматриваюсь")
        self.assertEqual(session.to_snapshot()["history"], history)
        self.assertEqual(session.to_snapshot()["pending_note"], note)
        session.send_action("Пробую снова")
        self.assertEqual(agent.requests[-1][-1]["content"], note)
        self.assertEqual(session.to_snapshot()["pending_note"], "")

    def test_checker_receives_current_state_and_event_summary(self):
        from fable.domain.state import GameState
        from test_session_memory import FakeSummarizer

        state = GameState(location="Башня")
        checker = SequenceChecker([ConsistencyVerdict.ok()] * 4)
        session = GameSession(FakeAgent(["Начало", "1", "2", "3"]), 4,
                              summarizer=FakeSummarizer(), checker=checker,
                              context_provider=lambda: "Мир: без магии\n" + state.to_context())
        session.start()
        for action in ["1", "2"]:
            session.send_action(action)
        state.update(location="Площадь")
        session.send_action("3")
        self.assertIn("Мир: без магии", checker.calls[-1][0])
        self.assertIn("Площадь", checker.calls[-1][0])
        self.assertIn(session.summary, checker.calls[-1][0])

    def test_checker_failure_does_not_rollback_a_completed_reply(self):
        class BrokenChecker:
            def check(self, context, recent, reply):
                raise RuntimeError("сбой")
        session = GameSession(FakeAgent(["Сцена"]), 4, checker=BrokenChecker())
        with self.assertLogs("fable.application.session", "WARNING"):
            self.assertEqual(session.start(), "Сцена")
        self.assertEqual(session.last_verdict, ConsistencyVerdict.ok())
        self.assertTrue(session.started)
