import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fable.infrastructure.llm_client import LLMClient


class LLMClientTests(unittest.TestCase):
    @patch("fable.infrastructure.llm_client.OpenAI")
    def test_ask_streams_and_combines_text_chunks(self, openai_class) -> None:
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])
            for text in ["Первые слова", " и продолжение"]
        ]
        openai_class.return_value.chat.completions.create.return_value = chunks
        client = LLMClient("http://localhost:8080/v1", "test-model", "test-key")

        result = client.ask([{"role": "user", "content": "Начни"}])

        self.assertEqual(result, "Первые слова и продолжение")
        self.assertTrue(
            openai_class.return_value.chat.completions.create.call_args.kwargs["stream"]
        )


if __name__ == "__main__":
    unittest.main()
