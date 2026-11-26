"""Small synchronous OpenAI-compatible transport shared by all LLM adapters."""
from collections.abc import Iterator
from dataclasses import dataclass, field
import json
import math
from time import perf_counter
from typing import Any, Literal

from openai import OpenAI

from fable.application.usage import TokenUsage, UsageRecord, record_usage
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
    role: str = 'plain'
    _stream_usage_supported: bool = field(default=True, init=False, repr=False)

    def _record(self, usage, messages, output, started):
        estimated = usage is None
        if estimated:
            prompt = math.ceil(len(json.dumps(messages, ensure_ascii=False, default=str)) / 4)
            completion = math.ceil(len(output) / 4)
            tokens = TokenUsage(prompt, completion, prompt + completion)
        else:
            tokens = TokenUsage(usage.prompt_tokens or 0, usage.completion_tokens or 0,
                                usage.total_tokens or 0)
        record_usage(UsageRecord(self.role, self.model, tokens,
                                 (perf_counter() - started) * 1000, estimated))

    def create(self, messages: list[dict], **kwargs) -> Any:
        options: dict[str, Any] = dict(model=self.model, temperature=self.temperature, messages=messages, **kwargs)
        if self.extra_body is not None:
            options['extra_body'] = self.extra_body
        streaming = bool(options.get('stream'))
        if streaming and self._stream_usage_supported:
            options['stream_options'] = {'include_usage': True}
        prompt = {'messages': messages}
        for key in ('tools', 'response_format'):
            if key in options:
                prompt[key] = options[key]
        started = perf_counter()
        try:
            response = self.client.chat.completions.create(**options)
        except Exception as error:
            self._record(None, prompt, '', started)
            text = (str(error) + ' ' + str(getattr(error, 'body', ''))).lower()
            if (streaming and 'stream_options' in options and
                    getattr(error, 'status_code', 400) in (400, 404, 422, 501) and
                    any(term in text for term in ('stream_options', 'include_usage')) and
                    any(term in text for term in ('unsupported', 'not support', 'unknown', 'not permitted',
                                                'not allowed', 'unrecognized', 'unexpected', 'extra inputs', 'not implemented', 'invalid'))):
                self._stream_usage_supported = False
                options.pop('stream_options')
                started = perf_counter()
                try:
                    response = self.client.chat.completions.create(**options)
                except Exception:
                    self._record(None, prompt, '', started)
                    raise
            else:
                raise
        if streaming:
            return self._measured_stream(response, prompt, started)
        message = response.choices[0].message
        output = message.content or ''
        tool_calls = getattr(message, 'tool_calls', None)
        if tool_calls:
            output += ''.join((call.function.name or '') + (call.function.arguments or '')
                              for call in tool_calls if getattr(call, 'function', None))
        self._record(getattr(response, 'usage', None), prompt, output, started)
        return response

    def _measured_stream(self, stream, messages, started):
        usage, output = None, []
        try:
            for chunk in stream:
                if getattr(chunk, 'usage', None) is not None:
                    usage = chunk.usage
                for choice in chunk.choices:
                    delta = choice.delta
                    output.append(delta.content or '')
                    for call in getattr(delta, 'tool_calls', None) or []:
                        if call.function:
                            output.append((call.function.name or '') + (call.function.arguments or ''))
                yield chunk
        finally:
            try:
                if hasattr(stream, 'close'):
                    stream.close()
            finally:
                self._record(usage, messages, ''.join(output), started)

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
