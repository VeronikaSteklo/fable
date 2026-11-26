"""Small synchronous OpenAI-compatible transport shared by all LLM adapters."""
from collections.abc import Iterator
from dataclasses import dataclass
import json
from typing import Any, Generic, Literal, TypeVar

from openai import APIStatusError, OpenAI
from pydantic import BaseModel, ValidationError

from fable.config import Settings, ThinkingLevel

StructuredMode = Literal['json_schema', 'json_object', 'prompt']
T = TypeVar('T', bound=BaseModel)


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


@dataclass
class StructuredResult(Generic[T]):
    raw: str
    parsed: T | None


def _strict_schema(schema: dict) -> dict:
    """OpenAI strict schemas require all properties and forbid extra keys recursively."""
    schema = {key: ([_strict_schema(v) if isinstance(v, dict) else v for v in value]
                    if isinstance(value, list) else _strict_schema(value) if isinstance(value, dict) else value)
              for key, value in schema.items() if key != 'default'}
    if schema.get('type') == 'object':
        schema['additionalProperties'] = False
        schema['required'] = list(schema.get('properties', {}))
    return schema


def _unsupported_format(error: APIStatusError) -> bool:
    text = (str(error) + ' ' + str(error.body)).lower()
    return error.status_code in (400, 404, 422, 501) and any(
        term in text for term in ('response_format', 'json_schema', 'json_object')
    ) and any(term in text for term in ('unsupported', 'not support', 'not available', 'unknown',
                                       'not permitted', 'not allowed', 'invalid', 'unrecognized',
                                       'must be', 'input should be', 'not implemented'))


def complete_structured(model: ChatModel, messages: list[dict], schema_model: type[T],
                        mode: StructuredMode | None = None) -> StructuredResult[T]:
    schema = _strict_schema(schema_model.model_json_schema())
    modes = ['json_schema', 'json_object', 'prompt']
    for current in modes[modes.index(mode or model.structured_output):]:
        options = {}
        request = list(messages)
        if current == 'json_schema':
            options['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': schema_model.__name__, 'schema': schema, 'strict': True}}
        else:
            request = [*request, {'role': 'system', 'content':
                       'Верни только JSON по этой схеме: ' + json.dumps(schema, ensure_ascii=False)}]
            if current == 'json_object':
                options['response_format'] = {'type': 'json_object'}
        try:
            raw = model.create(request, **options).choices[0].message.content or ''
        except APIStatusError as error:
            if current != 'prompt' and _unsupported_format(error):
                continue
            raise
        try:
            parsed = schema_model.model_validate_json(raw, strict=True)
        except ValidationError:
            parsed = None
        return StructuredResult(raw, parsed)
    raise AssertionError('Unreachable structured output mode')
