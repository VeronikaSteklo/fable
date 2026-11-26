from fable.application.prompts import load_prompt
import json
import logging
import re

from fable.infrastructure.llm.client import ChatModel
from fable.infrastructure.llm.structured import complete_structured
from fable.infrastructure.llm.structured import ModerationOutput

from fable.domain.safety.safety import RiskCategory, SafetyVerdict

logger = logging.getLogger(__name__)

MODERATOR_PROMPT = load_prompt('moderator')


class LLMModerator:
    """Классификатор на LLM. При сбое пропускает текст: защиту тогда держат правила и промпт."""

    def __init__(self, model: ChatModel):
        self._model = model
        if isinstance(model, ChatModel):
            model.role = 'moderator'

    def check(self, text: str) -> SafetyVerdict:
        try:
            reply = complete_structured(self._model,
                [
                    {"role": "system", "content": MODERATOR_PROMPT},
                    {"role": "user", "content": text},
                ], ModerationOutput
            )
            return parse_verdict(reply.parsed.model_dump_json() if reply.parsed else reply.raw)
        except Exception:
            logger.warning("Модератор недоступен, проверка пропущена", exc_info=True)
            return SafetyVerdict.allow()


def parse_verdict(raw: str) -> SafetyVerdict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return SafetyVerdict.allow()
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return SafetyVerdict.allow()
    if data.get("allowed", True):
        return SafetyVerdict.allow()
    try:
        category = RiskCategory(data.get("category"))
    except ValueError:
        return SafetyVerdict.allow()
    return SafetyVerdict.block(category, str(data.get("reason") or ""))
