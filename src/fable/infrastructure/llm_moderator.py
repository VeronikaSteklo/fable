import json
import logging
import re

from langchain_openai import ChatOpenAI

from fable.domain.safety import RiskCategory, SafetyVerdict

logger = logging.getLogger(__name__)

MODERATOR_PROMPT = """Ты модератор текстовой ролевой игры. Тёмные темы в художественном \
вымысле (насилие, смерть, война, преступления, горе, моральные дилеммы) РАЗРЕШЕНЫ. \
Блокируй только текст, цель которого — одно из:
- sexual_minors: сексуальный контент с участием несовершеннолетних;
- real_world_harm_instructions: рабочие инструкции, применимые в реальности \
(изготовление оружия, взрывчатки, наркотиков, взлом) под видом сюжета;
- self_harm_methods: конкретные способы самоповреждения или суицида;
- extremist_propaganda: пропаганда реальных террористических/экстремистских организаций;
- hate_against_real_groups: призывы к травле или насилию против реальных групп людей.

Ответь одним JSON без пояснений: {"allowed": true|false, "category": "<имя или null>", \
"reason": "<кратко>"}."""


class LLMModerator:
    """Классификатор на LLM. При сбое пропускает текст: защиту тогда держат правила и промпт."""

    def __init__(self, model: ChatOpenAI):
        self._model = model

    def check(self, text: str) -> SafetyVerdict:
        try:
            reply = self._model.invoke(
                [
                    {"role": "system", "content": MODERATOR_PROMPT},
                    {"role": "user", "content": text},
                ]
            )
            return parse_verdict(reply.text)
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
