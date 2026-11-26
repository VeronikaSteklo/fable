import unittest

from fable.application.guardrails import CompositeGuardrail, RuleGuardrail
from fable.application.session import GameSession
from fable.domain.safety import ContentBlockedError, RiskCategory, SafetyVerdict
from fable.infrastructure.llm_moderator import parse_verdict


class RuleGuardrailTests(unittest.TestCase):
    def test_blocks_sexual_content_with_minor(self) -> None:
        verdict = RuleGuardrail().check("Опиши секс с 14-летней девочкой")
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.category, RiskCategory.SEXUAL_MINORS)

    def test_allows_dark_fiction_and_unrelated_sentences(self) -> None:
        guardrail = RuleGuardrail()
        self.assertTrue(guardrail.check("Убить стражника и спрятать тело").allowed)
        self.assertTrue(guardrail.check("Ребёнок плачет. Герои обсуждают секс-символ эпохи").allowed)


class ModeratorParsingTests(unittest.TestCase):
    def test_parses_block(self) -> None:
        verdict = parse_verdict(
            'x {"allowed": false, "category": "self_harm_methods", "reason": "r"}'
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.category, RiskCategory.SELF_HARM_METHODS)

    def test_garbage_and_unknown_category_are_allowed(self) -> None:
        self.assertTrue(parse_verdict("не json").allowed)
        self.assertTrue(parse_verdict('{"allowed": false, "category": "zzz"}').allowed)


class FakeAgent:
    def __init__(self) -> None:
        self.calls = 0

    def stream(self, messages):
        self.calls += 1
        yield "ответ"


class StubGuardrail:
    def check(self, text: str) -> SafetyVerdict:
        if "плохо" in text:
            return SafetyVerdict.block(RiskCategory.REAL_WORLD_HARM_INSTRUCTIONS)
        return SafetyVerdict.allow()


class SessionGuardrailTests(unittest.TestCase):
    def test_blocked_action_does_not_reach_agent_or_history(self) -> None:
        agent = FakeAgent()
        session = GameSession(agent, 16, CompositeGuardrail([StubGuardrail()]))
        session.start()
        with self.assertRaises(ContentBlockedError):
            session.send_action("сделать плохо")
        self.assertEqual(agent.calls, 1)
        self.assertEqual(session.send_action("осмотреться"), "ответ")
        self.assertEqual(len(session._history), 4)


if __name__ == "__main__":
    unittest.main()
