from typing import Protocol

from fable.domain.safety.consistency import ConsistencyVerdict


class ConsistencyChecker(Protocol):
    def check(self, context: str, recent: list[dict], reply: str) -> ConsistencyVerdict: ...
