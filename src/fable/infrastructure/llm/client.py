"""Small synchronous OpenAI-compatible transport shared by all LLM adapters."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI

from fable.config import Settings, ThinkingLevel

StructuredMode = Literal['json_schema', 'json_object', 'prompt']


def build_client(settings: Settings, *, base_url: str | None = None) -> OpenAI:
    return OpenAI(base_url=base_url or settings.base_url, api_key=settings.api_key,
                  timeout=settings.llm_timeout_seconds, max_retries=settings.llm_max_retries)


def thinking_extra_body(settings: Settings) -> dict:
    body: dict[str, Any] = {'chat_template_kwargs': {'enable_thinking': settings.enable_thinking is not ThinkingLevel.NONE}}
    if settings.enable_thinking is not ThinkingLevel.NONE:
        body['reasoning_effort'] = settings.enable_thinking.value
    return body


@dataclass
class ChatModel:
    client: OpenAI
    model: str
    temperature: float = 0
    extra_body: dict | None = None
    structured_output: StructuredMode = 'json_schema'

    def create(self, messages: list[dict], **kwargs):
        options: dict[str, Any] = dict(model=self.model, temperature=self.temperature, messages=messages, **kwargs)
        if self.extra_body is not None:
            options['extra_body'] = self.extra_body
        return self.client.chat.completions.create(**options)

    def complete(self, messages: list[dict]) -> str:
        return self.create(messages).choices[0].message.content or ''

    def stream(self, messages: list[dict]) -> Iterator[str]:
        stream = self.create(messages, stream=True)
        try:
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            if hasattr(stream, 'close'):
                stream.close()
