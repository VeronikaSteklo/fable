from dataclasses import dataclass


@dataclass(frozen=True)
class ConsistencyVerdict:
    consistent: bool
    issues: tuple[str, ...] = ()

    @classmethod
    def ok(cls) -> "ConsistencyVerdict":
        return cls(consistent=True)
