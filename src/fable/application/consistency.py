from typing import Protocol

from fable.domain.consistency import ConsistencyVerdict


class ConsistencyChecker(Protocol):
    def check(self, context: str, recent: list[dict], reply: str) -> ConsistencyVerdict: ...
