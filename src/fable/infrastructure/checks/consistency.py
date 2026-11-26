from fable.application.prompts import load_prompt
import json
import logging

from fable.infrastructure.llm.client import ChatModel
from fable.infrastructure.llm.structured import complete_structured
from fable.infrastructure.llm.structured import ConsistencyOutput

from fable.domain.safety.consistency import ConsistencyVerdict

logger = logging.getLogger(__name__)

CONSISTENCY_PROMPT = load_prompt('consistency')


class LLMConsistencyChecker:
    def __init__(self, model: ChatModel) -> None:
        self._model = model

    def check(self, context: str, recent: list[dict], reply: str) -> ConsistencyVerdict:
        try:
            response = complete_structured(self._model, [
                {"role": "system", "content": CONSISTENCY_PROMPT},
                {"role": "user", "content": json.dumps({
                    "context": context, "recent": recent, "reply": reply,
                }, ensure_ascii=False)},
            ], ConsistencyOutput)
            return parse_consistency_verdict(response.parsed.model_dump_json() if response.parsed else response.raw)
        except Exception:
            logger.warning("Проверка согласованности недоступна, пропускаем", exc_info=True)
            return ConsistencyVerdict.ok()


def parse_consistency_verdict(raw: str) -> ConsistencyVerdict:
    # raw_decode handles fenced JSON and prose without a greedy brace regex.
    decoder = json.JSONDecoder()
    for offset, char in enumerate(raw):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(raw[offset:])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or type(data.get("consistent")) is not bool:
            continue
        issues = data.get("issues")
        if not isinstance(issues, list) or not all(isinstance(issue, str) for issue in issues):
            return ConsistencyVerdict.ok()
        return ConsistencyVerdict(data["consistent"], tuple(issues))
    return ConsistencyVerdict.ok()
