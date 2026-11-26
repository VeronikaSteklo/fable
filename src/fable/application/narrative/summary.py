from typing import Protocol


class Summarizer(Protocol):
    # Returning the previous summary (or raising) means no progress; retry later.
    def summarize(self, previous_summary: str, messages: list[dict]) -> str: ...
