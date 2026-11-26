from fable.application.prompts import load_prompt, render_prompt
import json
import logging

from fable.infrastructure.llm.client import ChatModel

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = load_prompt('summary')


class LLMSummarizer:
    def __init__(self, model: ChatModel, max_chars: int = 2000) -> None:
        if max_chars < 1:
            raise ValueError("Размер резюме должен быть положительным")
        self._model = model
        if isinstance(model, ChatModel):
            model.role = 'summarizer'
        self._max_chars = max_chars

    def summarize(self, previous_summary: str, messages: list[dict]) -> str:
        try:
            reply = self._model.complete([
                {"role": "system", "content": render_prompt('summary', max_chars=self._max_chars)},
                {"role": "user", "content": json.dumps({
                    "previous_summary": previous_summary,
                    "messages": messages,
                }, ensure_ascii=False)},
            ])
            summary = reply.strip()
            if not summary:
                raise ValueError("Модель вернула пустое резюме")
            return summary[:self._max_chars]
        except Exception:
            logger.warning("Сжатие истории недоступно; старые реплики сохранены", exc_info=True)
            return previous_summary
