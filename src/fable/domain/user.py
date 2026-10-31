from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: str
    username: str
    created_at: str
