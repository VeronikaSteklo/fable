from collections.abc import Iterator

from openai import OpenAI


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str):
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def ask(self, messages: list[dict]) -> str:
        content = "".join(self.stream(messages))
        if not content:
            raise RuntimeError("Модель вернула пустой ответ.")
        return content

    def stream(self, messages: list[dict]) -> Iterator[str]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            stream=True,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield content
