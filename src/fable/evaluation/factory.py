"""Composition root isolated from CLI/network: injectable master, fake all LLM roles."""
from dataclasses import dataclass
from fable.application.usage import TokenUsage, UsageRecord, record_usage

from fable.application.game.session import GameSession
from fable.domain.game.state import GameState
from fable.evaluation.configurations import Configuration, configure_settings, plain_prompt
from fable.infrastructure.checks.judge import ObservedConsistencyChecker, SCORE_KEYS


def fake_usage(role, model, prompt=80, completion=20):
    record_usage(UsageRecord(role, model, TokenUsage(prompt, completion, prompt + completion), 10))


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += .01
        return self.value


class FakeAgent:
    def __init__(self, model="offline-model", role="master", companions=False):
        self.model, self.role, self.companions = model, role, companions

    def stream(self, messages):
        fake_usage(self.role, self.model)
        if self.companions:
            fake_usage("companion", self.model, 24, 6)
        yield 'Офлайн-сцена. '
        yield 'Игрок может выбрать дальнейшее действие.'


class FakeSummary:
    def __init__(self, model="offline-model"):
        self.model = model

    def summarize(self, previous_summary, messages):
        fake_usage("summarizer", self.model, 32, 8)
        return (previous_summary + '\n' + '\n'.join(item['content'] for item in messages))[-2000:]


class FakeConsistency:
    def __init__(self, model="offline-model"):
        self.model = model
        self.last = None

    def check(self, context, recent, reply):
        fake_usage("consistency", self.model, 16, 4)
        from fable.domain.safety.consistency import ConsistencyVerdict
        self.last = dict(valid=True, consistent=True, issues=[], raw='{"consistent":true,"issues":[]}', error=None)
        return ConsistencyVerdict.ok()


class FakeJudge:
    def evaluate(self, scenario, turns):
        fake_usage("judge", "fake-judge", 40, 10)
        for probe in scenario.probes:
            if any(t["turn"] > probe.after_turn and not t["error"] for t in turns):
                fake_usage("judge", "fake-judge", 40, 10)
        return dict(valid=True, **dict.fromkeys(SCORE_KEYS, 3), raw='', error=None,
                    justification='Демонстрационная оценка заглушки, не оценка качества модели.',
                    probes=[dict(after_turn=p.after_turn, fact=p.fact,
                                 eligible=any(t['turn'] > p.after_turn and not t['error'] for t in turns),
                                 valid=True, status='ignored', justification='Заглушка не проверяет факты.')
                            for p in scenario.probes])


@dataclass
class Runtime:
    session: GameSession
    state: GameState
    options: dict
    checker: ObservedConsistencyChecker | FakeConsistency | None = None

    def rollback(self, session_snapshot, state_snapshot):
        self.state.restore(state_snapshot)
        self.session = GameSession.from_snapshot(session_snapshot, **self.options)


def create_runtime(settings, setup, config: Configuration, model: str, *, dry_run=False, agent_factory=None) -> Runtime:
    configured = configure_settings(settings, config, model)
    state = GameState.for_setup(setup)
    summarizer = None
    checker = None
    context_provider = None
    if dry_run:
        agent = agent_factory(configured, setup, state, config) if agent_factory else FakeAgent(model, "master" if config.tools else "plain", config.companions)
        summarizer = FakeSummary(model) if config.summary else None
        checker = FakeConsistency(model) if config.consistency else None
    else:
        from fable.bootstrap import _model, create_context_provider
        from fable.infrastructure.checks.summarizer import LLMSummarizer
        from fable.infrastructure.agents.plain import PlainStreamingAgent
        if agent_factory:
            agent = agent_factory(configured, setup, state, config)
        elif config.tools:
            from fable.application.prompts import build_system_prompt
            from fable.infrastructure.agents.master import GameMasterAgent
            from fable.infrastructure.agents.companion import LLMCompanionVoice
            memory = None
            if config.memory:
                from fable.infrastructure.llm.embeddings import create_embeddings
                from fable.infrastructure.memory.chroma import ChromaMemory
                memory = ChromaMemory(
                    setup=setup, embeddings=create_embeddings(configured),
                    persist_directory=configured.memory_store_path, search_limit=configured.memory_search_limit,
                )
            voice = LLMCompanionVoice(_model(configured, model, temperature=configured.companion_temperature), setup) if config.companions and setup.companions else None
            agent = GameMasterAgent(configured, build_system_prompt(setup, vector_memory_enabled=memory is not None,
                                    companions_enabled=config.companions), state, memory, setup=setup, companion_voice=voice)
        else:
            agent = PlainStreamingAgent.from_settings(configured, plain_prompt(setup))
        summarizer = LLMSummarizer(_model(configured, model), configured.summary_max_chars) if config.summary else None
        checker = ObservedConsistencyChecker(_model(configured, model)) if config.consistency else None
        context_provider = create_context_provider(setup, state) if config.tools else None
    if dry_run and config.tools:
        from fable.bootstrap import create_context_provider
        context_provider = create_context_provider(setup, state)
    options: dict = dict(agent=agent, history_limit=config.history_limit, summarizer=summarizer,
                   checker=checker, context_provider=context_provider, model_prices=settings.model_prices)
    if dry_run:
        options["usage_clock"] = FakeClock()
    return Runtime(GameSession(**options), state, options, checker)
