from collections.abc import Iterator

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from fable.config import Settings, ThinkingLevel


class GameMasterAgent:
    def __init__(self, settings: Settings, system_prompt: str):
        extra_body: dict[str, object] = {
            "chat_template_kwargs": {
                "enable_thinking": settings.enable_thinking is not ThinkingLevel.NONE
            }
        }
        if settings.enable_thinking is not ThinkingLevel.NONE:
            extra_body["reasoning_effort"] = settings.enable_thinking.value

        model = ChatOpenAI(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key,
            temperature=settings.temperature,
            extra_body=extra_body,
        )
        self._agent = create_agent(
            model=model,
            tools=[],
            system_prompt=system_prompt,
        )

    def stream(self, messages: list[dict]) -> Iterator[str]:
        events = self._agent.stream(
            {"messages": messages},
            stream_mode="messages",
            version="v2",
        )
        for event in events:
            if event["type"] != "messages":
                continue

            message_chunk = event["data"][0]
            text = message_chunk.text
            if text:
                yield text
