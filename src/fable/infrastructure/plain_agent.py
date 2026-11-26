"""Plain continuation baseline: no bound tools and no mutable state access."""
from collections.abc import Iterator


class PlainStreamingAgent:
    def __init__(self, model, system_prompt: str) -> None:
        self._model = model
        self._prompt = system_prompt

    @classmethod
    def from_settings(cls, settings, system_prompt: str):
        from langchain_openai import ChatOpenAI
        from fable.config import ThinkingLevel
        extra_body: dict[str, object] = {'chat_template_kwargs': {
            'enable_thinking': settings.enable_thinking is not ThinkingLevel.NONE}}
        if settings.enable_thinking is not ThinkingLevel.NONE:
            extra_body['reasoning_effort'] = settings.enable_thinking.value
        return cls(ChatOpenAI(model=settings.model, api_key=settings.api_key,
                              base_url=settings.base_url, temperature=settings.temperature,
                              extra_body=extra_body), system_prompt)

    def stream(self, messages: list[dict]) -> Iterator[str]:
        for chunk in self._model.stream([{'role': 'system', 'content': self._prompt}, *messages]):
            if chunk.text:
                yield chunk.text
