"""SSE wire format and cancellation-safe cleanup of synchronous turn streams."""
from collections.abc import Callable, Generator
import json

import anyio
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class GameStreamResponse(StreamingResponse):
    """Close the synchronous generator even when ASGI cancels between chunks.

    StreamingResponse iterates sync bodies in a threadpool; its async wrapper
    alone does not guarantee closing the underlying Python generator.
    """
    def __init__(self, iterator: Generator[str, None, None], release: Callable[[], None]):
        super().__init__(iterator, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })
        self._iterator = iterator
        self._release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await run_in_threadpool(self._iterator.close)
                finally:
                    self._release()
