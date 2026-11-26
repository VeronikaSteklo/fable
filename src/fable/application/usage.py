"""Per-turn accounting boundary, independent of providers and presentation.

Bind only while advancing/closing a generator: ASGI may use a different worker
and Context for each next(), so a ContextVar token must never span a yield.
"""
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from threading import Lock
from time import perf_counter


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: 'TokenUsage') -> 'TokenUsage':
        return TokenUsage(self.prompt_tokens + other.prompt_tokens,
                          self.completion_tokens + other.completion_tokens,
                          self.total_tokens + other.total_tokens)


@dataclass(frozen=True)
class UsageRecord:
    role: str
    model: str
    usage: TokenUsage
    duration_ms: float
    estimated: bool = False


def compute_cost(usage: TokenUsage, model: str, prices: dict) -> float | None:
    price = prices.get(model)
    if price is None:
        return None
    return (usage.prompt_tokens * price['input'] + usage.completion_tokens * price['output']) / 1_000_000


_current: ContextVar['UsageMeter | None'] = ContextVar('usage_meter', default=None)


def record_usage(record: UsageRecord) -> None:
    meter = _current.get()
    if meter is not None:
        meter.record(record)


class UsageMeter:
    """Thread-safe collector; an application port used by LLM adapters/fakes."""
    def __init__(self, prices: dict | None = None, *, clock=perf_counter):
        self.prices = prices or {}
        self.records: list[UsageRecord] = []
        self._lock = Lock()
        self._clock = clock
        self._started = clock()
        self._ended: float | None = None

    def record(self, record: UsageRecord) -> None:
        with self._lock:
            self.records.append(record)

    def iterate(self, iterator):
        try:
            while True:
                token = _current.set(self)
                try:
                    value = next(iterator)
                except StopIteration:
                    return
                finally:
                    _current.reset(token)
                yield value
        finally:
            token = _current.set(self)
            try:
                if hasattr(iterator, 'close'):
                    iterator.close()
            finally:
                _current.reset(token)
                self._ended = self._clock()

    def summary(self) -> dict:
        with self._lock:
            records = list(self.records)
        usage = TokenUsage()
        roles: dict = {}
        costs = []
        for record in records:
            usage += record.usage
            role = roles.setdefault(record.role, dict(asdict(TokenUsage()), calls=0))
            for key, value in asdict(record.usage).items():
                role[key] += value
            role['calls'] += 1
            costs.append(compute_cost(record.usage, record.model, self.prices))
        return dict(asdict(usage), llm_calls=len(records), estimated=any(r.estimated for r in records),
                    cost_usd=sum(costs) if records and all(c is not None for c in costs) else None,
                    duration_ms=((self._ended if self._ended is not None else self._clock()) - self._started) * 1000,
                    by_role=roles)


def aggregate_usage(items) -> dict:
    """Unknown/missing historical prices propagate; never report a partial cost."""
    items = list(items)
    result = dict(asdict(TokenUsage()), llm_calls=0, estimated=False, cost_usd=None, duration_ms=0, by_role={})
    for item in items:
        if not item:
            continue
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'llm_calls', 'duration_ms'):
            result[key] += item.get(key, 0)
        result['estimated'] |= item.get('estimated', False)
        for name, role in item.get('by_role', {}).items():
            target = result['by_role'].setdefault(name, dict(asdict(TokenUsage()), calls=0))
            for key in target:
                target[key] += role.get(key, 0)
    if items and all(i is not None and i.get('cost_usd') is not None for i in items):
        result['cost_usd'] = sum(i['cost_usd'] for i in items)
    return result
