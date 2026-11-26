import unittest

from fable.application.session import GameSession


class FakeAgent:
    def __init__(self, responses: list[str | list[str] | Exception]):
        self.responses = responses
        self.requests: list[list[dict]] = []

    def stream(self, messages: list[dict]):
        self.requests.append([message.copy() for message in messages])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        yield from response if isinstance(response, list) else [response]


class GameSessionTests(unittest.TestCase):
    def test_context_and_actions_are_sent_to_model(self) -> None:
        agent = FakeAgent(["Начальная сцена", "Дверь открывается"])
        session = GameSession(agent, history_limit=16)

        self.assertEqual(session.start(), "Начальная сцена")
        self.assertEqual(session.send_action("Открыть дверь"), "Дверь открывается")

        self.assertEqual(
            agent.requests[0][0]["content"],
            "Создай начальную сцену, соответствующую контексту игры. "
            "Не решай за героя, что он делает. Заверши сцену ситуацией, "
            "на которую игрок может отреагировать.",
        )
        self.assertEqual(agent.requests[1][-1]["content"], "Открыть дверь")
        self.assertEqual(agent.requests[1][-2]["content"], "Начальная сцена")

    def test_stream_yields_chunks_and_stores_the_complete_reply(self) -> None:
        agent = FakeAgent([["Начальная ", "сцена"]])
        session = GameSession(agent, history_limit=16)
        stream = session.start_stream()

        self.assertEqual(next(stream), "Начальная ")
        self.assertEqual(next(stream), "сцена")
        with self.assertRaises(StopIteration):
            next(stream)

        agent.responses.append("Продолжение")
        session.send_action("Осмотреться")
        self.assertEqual(agent.requests[-1][-2]["content"], "Начальная сцена")

    def test_game_context_is_kept_when_history_is_trimmed(self) -> None:
        agent = FakeAgent(["Сцена", *[f"Ответ {index}" for index in range(10)]])
        session = GameSession(agent, history_limit=16)
        session.start()

        for index in range(10):
            session.send_action(f"Действие {index}")

        latest_request = agent.requests[-1]
        self.assertLessEqual(len(latest_request), 16)
        self.assertIn("Создай начальную сцену", latest_request[0]["content"])
        self.assertEqual(latest_request[-1]["content"], "Действие 9")

    def test_failed_action_is_not_kept_in_history(self) -> None:
        agent = FakeAgent(["Сцена", RuntimeError("ошибка API"), "Повторный ответ"])
        session = GameSession(agent, history_limit=16)
        session.start()

        with self.assertRaisesRegex(RuntimeError, "ошибка API"):
            session.send_action("Неудачное действие")

        session.send_action("Новое действие")
        latest_request = agent.requests[-1]
        sent_user_messages = [
            message["content"] for message in latest_request if message["role"] == "user"
        ]
        self.assertNotIn("Неудачное действие", sent_user_messages)
        self.assertIn("Новое действие", sent_user_messages)


if __name__ == "__main__":
    unittest.main()
