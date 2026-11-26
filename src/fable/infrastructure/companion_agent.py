import logging

from langchain_openai import ChatOpenAI

from fable.application.prompts import build_companion_prompt
from fable.domain.companion import Companion, CompanionState
from fable.domain.models import GameSetup

logger = logging.getLogger(__name__)


class LLMCompanionVoice:
    def __init__(self, model: ChatOpenAI, setup: GameSetup) -> None:
        self._model = model
        self._setup = setup

    def speak(self, companion: CompanionState, profile: Companion, situation: str) -> str:
        try:
            response = self._model.invoke([
                {"role": "system", "content": build_companion_prompt(self._setup, profile, companion)},
                {"role": "user", "content": situation},
            ])
            text = response.text.strip()
            if not text:
                raise ValueError("Пустая реплика спутника")
            return text
        except Exception:
            logger.warning("Не удалось получить реплику спутника %s", companion.name, exc_info=True)
            return f"({companion.name} молчит.)"
