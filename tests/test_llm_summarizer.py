import unittest
from types import SimpleNamespace

from fable.infrastructure.llm_summarizer import LLMSummarizer
from fable.infrastructure.openai_client import ChatModel


class FakeModel(ChatModel):
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.requests = []
        self.options = []
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))
        super().__init__(self.client, 'fake')

    def _create(self, **kwargs):
        self.requests.append(kwargs['messages'])
        self.options.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])

    def create(self, messages, **kwargs):
        return super().create(messages, **kwargs)

    def complete(self, messages):
        return super().complete(messages)


class LLMSummarizerTests(unittest.TestCase):
    def test_compresses_previous_summary_and_turns_with_character_budget(self):
        model = FakeModel("Событие. " * 20)
        summarizer = LLMSummarizer(model, max_chars=50)
        result = summarizer.summarize("Прошлое", [{"role": "user", "content": "Открыл дверь"}])
        self.assertLessEqual(len(result), 50)
        self.assertIn("50", model.requests[0][0]["content"])
        self.assertIn("Прошлое", model.requests[0][1]["content"])
        self.assertIn("Открыл дверь", model.requests[0][1]["content"])

    def test_failure_or_empty_reply_returns_previous_summary(self):
        for model in [FakeModel(error=RuntimeError("сбой")), FakeModel(" ")]:
            with self.subTest(model=model), self.assertLogs("fable.infrastructure.llm_summarizer", "WARNING"):
                self.assertEqual(LLMSummarizer(model).summarize("Прошлое", []), "Прошлое")
