"""Play the same scripted actions through GameSession; no network in dry-run."""
from dataclasses import asdict
import json
from pathlib import Path
import time
from urllib.parse import quote

from fable.application.usage import UsageMeter
from fable.evaluation.factory import FakeClock, FakeJudge, create_runtime
from fable.evaluation.reporting import write_json, write_summary, write_transcript


def run_experiments(scenarios, configs, models, settings, out: Path, *, judge=None,
                    judge_model=None, dry_run=False, turns=None, repeat=1,
                    clock=None, agent_factory=None, progress=print) -> Path:
    if repeat < 1 or (turns is not None and turns < 0):
        raise ValueError('repeat должен быть >= 1; turns должен быть >= 0')
    if not scenarios or not configs or not models:
        raise ValueError('Нужны сценарии, конфигурации и модели')
    if len({c.name for c in configs}) != len(configs) or len(set(models)) != len(models):
        raise ValueError('Конфигурации и модели не должны повторяться')
    if out.exists() and any(out.iterdir()):
        raise ValueError(f'Каталог результатов должен быть пустым: {out}')
    out.mkdir(parents=True, exist_ok=True)
    for folder in ('transcripts', 'snapshots'):
        (out / folder).mkdir()
    clock = clock or (FakeClock() if dry_run else time.perf_counter)
    if judge is None:
        if dry_run:
            judge = FakeJudge()
        else:
            from fable.bootstrap import _model
            from fable.infrastructure.checks.judge import LLMJudge
            judge = LLMJudge(_model(settings, judge_model or settings.model))
    skipped, runs = [], []
    manifest = dict(dry_run=dry_run, repeat=repeat, action_limit=turns, models=models,
                    judge_model=judge_model or ('fake-judge' if dry_run else settings.model),
                    configurations=[asdict(c) for c in configs],
                    scenarios=[s.to_dict() for s in scenarios], skipped=skipped,
                    temperature=settings.temperature, enable_thinking=settings.enable_thinking.value,
                    structured_output=settings.structured_output, max_tool_rounds=settings.max_tool_rounds,
                    llm_timeout_seconds=settings.llm_timeout_seconds, llm_max_retries=settings.llm_max_retries,
                    companion_temperature=settings.companion_temperature,
                    summary_max_chars=settings.summary_max_chars,
                    embedding_model=settings.embedding_model, memory_search_limit=settings.memory_search_limit,
                    moderation_enabled=False, model_prices=settings.model_prices)
    write_json(out / 'manifest.json', manifest)
    with (out / 'runs.jsonl').open('w', encoding='utf-8') as log:
        for scenario in scenarios:
            for config in configs:
                for model in models:
                    for repetition in range(1, repeat + 1):
                        identity = dict(scenario=scenario.id, config=config.name, model=model, repeat=repetition)
                        reason = None
                        if config.memory and not settings.embedding_model:
                            reason = 'Не задан EMBEDDING_MODEL: долгосрочная память отключена'
                        elif config.companions and not scenario.setup.companions:
                            reason = 'В сценарии нет спутников'
                        if reason:
                            skipped.append(dict(**identity, reason=reason))
                            progress(f'Пропуск {scenario.id}/{config.name}/{model}: {reason}')
                            continue
                        stem = f'{scenario.id}__{config.name}__{quote(model, safe="")}'
                        if repeat > 1:
                            stem += f'__r{repetition}'
                        # Never reuse Chroma collections across models/configs/repetitions.
                        run_settings = settings.model_copy(update={'memory_store_path': out / 'memory' / stem})
                        progress(f'Запуск {scenario.id}/{config.name}/{model}, повтор {repetition}/{repeat}')
                        runtime = create_runtime(run_settings, scenario.setup, config, model,
                                                 dry_run=dry_run, agent_factory=agent_factory)
                        records = []
                        actions = (None, *scenario.actions[:turns]) if turns is not None else (None, *scenario.actions)
                        for turn, action in enumerate(actions):
                            session_before = runtime.session.to_snapshot()
                            state_before = runtime.state.to_dict()
                            if runtime.checker is not None:
                                runtime.checker.last = None
                            chunks, first, error = [], None, None
                            started = clock()
                            try:
                                stream = (runtime.session.start_stream() if action is None
                                          else runtime.session.send_action_stream(action))
                                for chunk in stream:
                                    if chunk:
                                        if first is None:
                                            first = clock()
                                        chunks.append(chunk)
                            except Exception as failure:
                                error = f'{type(failure).__name__}: {failure}'
                            ended = clock()
                            consistency = runtime.checker.last if runtime.checker is not None and error is None else None
                            usage = runtime.session.last_attempt_usage
                            if error:
                                runtime.rollback(session_before, state_before)
                            reply = ''.join(chunks)
                            record = dict(**identity, turn=turn, action=action, reply=reply, reply_chars=len(reply),
                                          ttft_ms=(first-started)*1000 if first is not None else None,
                                          total_ms=(ended-started)*1000, consistency=consistency, error=error, usage=usage)
                            records.append(record)
                            log.write(json.dumps(record, ensure_ascii=False) + '\n')
                            log.flush()
                            progress(f'  Ход {turn}/{len(actions)-1}: ' + ('ошибка' if error else f'{len(reply)} символов'))
                        judge_meter = UsageMeter(settings.model_prices, clock=FakeClock() if dry_run else time.perf_counter)
                        def evaluate():
                            yield judge.evaluate(scenario, records)
                        judgment = list(judge_meter.iterate(evaluate()))[0]
                        judgment["usage"] = judge_meter.summary()
                        run = dict(**identity, turns=records, judge=judgment)
                        write_json(out / 'snapshots' / f'{stem}.json', dict(
                            **identity, state=runtime.state.to_dict(), session=runtime.session.to_snapshot(),
                            judge=judgment, configuration=asdict(config)))
                        write_transcript(out / 'transcripts' / f'{stem}.md', scenario, run)
                        runs.append(run)
    write_json(out / 'manifest.json', manifest)
    target = write_summary(out, runs, skipped, dry_run=dry_run)
    progress(f'Итоговая таблица: {target}')
    return target
