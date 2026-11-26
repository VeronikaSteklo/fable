import unittest

from fable.application.session import GameSession
from fable.domain.models import Character, GameSetup


class FakeLLMClient:
    def __init__(self, responses: list[str | list[str] | Exception]):
        self.responses = responses
        self.requests: list[list[dict]] = []

    def stream(self, messages: list[dict]):
        self.requests.append([message.copy() for message in messages])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        yield from response if isinstance(response, list) else [response]


def make_setup() -> GameSetup:
    return GameSetup(
        world="Мир стеклянных городов",
        story="Пропала королева",
        character=Character(
            name="Мира",
            role="следопыт",
            goal="найти королеву",
            description="Любит старые карты",
            genre="фэнтези",
        ),
    )


class GameSessionTests(unittest.TestCase):
    def test_context_and_actions_are_sent_to_model(self) -> None:
        client = FakeLLMClient(["Начальная сцена", "Дверь открывается"])
        session = GameSession(make_setup(), client)

        self.assertEqual(session.start(), "Начальная сцена")
        self.assertEqual(session.send_action("Открыть дверь"), "Дверь открывается")

        first_request = client.requests[0]
        system_prompt = first_request[0]["content"]
        self.assertIn("Мир стеклянных городов", system_prompt)
        self.assertIn("Пропала королева", system_prompt)
        self.assertIn("Любит старые карты", system_prompt)
        self.assertEqual(client.requests[1][-1]["content"], "Открыть дверь")
        self.assertEqual(client.requests[1][-2]["content"], "Начальная сцена")

    def test_stream_yields_chunks_and_stores_the_complete_reply(self) -> None:
        client = FakeLLMClient([["Начальная ", "сцена"]])
        session = GameSession(make_setup(), client)
        stream = session.start_stream()

        self.assertEqual(next(stream), "Начальная ")
        self.assertEqual(next(stream), "сцена")
        with self.assertRaises(StopIteration):
            next(stream)

        client.responses.append("Продолжение")
        session.send_action("Осмотреться")
        self.assertEqual(client.requests[-1][-2]["content"], "Начальная сцена")

    def test_game_context_is_kept_when_history_is_trimmed(self) -> None:
        client = FakeLLMClient(["Сцена", *[f"Ответ {index}" for index in range(10)]])
        session = GameSession(make_setup(), client)
        session.start()

        for index in range(10):
            session.send_action(f"Действие {index}")

        latest_request = client.requests[-1]
        self.assertLessEqual(len(latest_request), 16)
        self.assertIn("Мир стеклянных городов", latest_request[0]["content"])
        self.assertEqual(latest_request[-1]["content"], "Действие 9")

    def test_failed_action_is_not_kept_in_history(self) -> None:
        client = FakeLLMClient(["Сцена", RuntimeError("ошибка API"), "Повторный ответ"])
        session = GameSession(make_setup(), client)
        session.start()

        with self.assertRaisesRegex(RuntimeError, "ошибка API"):
            session.send_action("Неудачное действие")

        session.send_action("Новое действие")
        latest_request = client.requests[-1]
        sent_user_messages = [
            message["content"] for message in latest_request if message["role"] == "user"
        ]
        self.assertNotIn("Неудачное действие", sent_user_messages)
        self.assertIn("Новое действие", sent_user_messages)


if __name__ == "__main__":
    unittest.main()
