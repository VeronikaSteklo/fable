"""Auditable evaluation adapters: invalid structured output is never a success."""
from fable.application.prompts import load_prompt
import json

from fable.infrastructure.llm.client import ChatModel
from fable.infrastructure.llm.structured import complete_structured
from fable.infrastructure.llm.structured import ConsistencyOutput, JudgmentOutput, ProbeOutput

from fable.domain.safety.consistency import ConsistencyVerdict
from fable.infrastructure.checks.consistency import CONSISTENCY_PROMPT

SCORE_KEYS = ('coherence', 'character_adherence', 'no_contradictions', 'player_agency')
JUDGE_RUBRIC = load_prompt('judge')
PROBE_RUBRIC = load_prompt('judge_probe')


def _objects(raw: str):
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char == '{':
            try:
                value, _ = decoder.raw_decode(raw[index:])
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                yield value


def parse_judgment(raw: str) -> dict | None:
    for data in _objects(raw):
        if (all(type(data.get(key)) is int and 1 <= data[key] <= 5 for key in SCORE_KEYS)
                and isinstance(data.get('justification'), str) and data['justification'].strip()):
            return {key: data[key] for key in (*SCORE_KEYS, 'justification')}
    return None


def parse_probe(raw: str) -> dict | None:
    for data in _objects(raw):
        if (data.get('status') in ('respected', 'contradicted', 'ignored')
                and isinstance(data.get('justification'), str) and data['justification'].strip()):
            return {key: data[key] for key in ('status', 'justification')}
    return None


class LLMJudge:
    """The composition root supplies a temperature-zero model."""
    def __init__(self, model: ChatModel):
        self._model = model

    def _ask(self, prompt, payload, parser) -> dict:
        try:
            response = complete_structured(self._model, [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
            ], JudgmentOutput if parser is parse_judgment else ProbeOutput)
            raw = response.raw
            parsed = parser(response.parsed.model_dump_json() if response.parsed else raw)
            return dict(valid=parsed is not None, raw=raw, error=None if parsed else 'Некорректный JSON',
                        **(parsed or {}))
        except Exception as error:
            return dict(valid=False, raw='', error=f'{type(error).__name__}: {error}')

    def evaluate(self, scenario, turns: list[dict]) -> dict:
        # Blind the judge to model/config names, timings and the consistency checker's opinion.
        narrative = [{key: turn.get(key) for key in ('turn', 'action', 'reply', 'error')} for turn in turns]
        result = self._ask(JUDGE_RUBRIC, {'setup': scenario.setup.to_dict(), 'turns': narrative}, parse_judgment)
        probes = []
        for probe in scenario.probes:
            later = [{'turn': turn['turn'], 'reply': turn['reply']} for turn in turns
                     if turn['turn'] > probe.after_turn and turn.get('reply') and not turn.get('error')]
            if not later:
                probes.append(dict(after_turn=probe.after_turn, fact=probe.fact, eligible=False,
                                   valid=False, status=None, error='Нет последующих завершённых ответов'))
                continue
            verdict = self._ask(PROBE_RUBRIC, {'fact': probe.fact, 'after_turn': probe.after_turn,
                                             'replies': later}, parse_probe)
            probes.append(dict(after_turn=probe.after_turn, fact=probe.fact, eligible=True, **verdict))
        result['probes'] = probes
        return result


class ObservedConsistencyChecker:
    """Preserve normal fail-open gameplay, but expose parse/API failures to metrics."""
    def __init__(self, model: ChatModel):
        self._model = model
        self.last = None

    def check(self, context: str, recent: list[dict], reply: str) -> ConsistencyVerdict:
        raw = ''
        try:
            response = complete_structured(self._model, [
                {'role': 'system', 'content': CONSISTENCY_PROMPT},
                {'role': 'user', 'content': json.dumps(dict(context=context, recent=recent, reply=reply), ensure_ascii=False)},
            ], ConsistencyOutput)
            raw = response.raw
            for data in _objects(response.parsed.model_dump_json() if response.parsed else raw):
                if (type(data.get('consistent')) is bool and isinstance(data.get('issues'), list)
                        and all(isinstance(issue, str) for issue in data['issues'])):
                    self.last = dict(valid=True, consistent=data['consistent'], issues=data['issues'], raw=raw, error=None)
                    return ConsistencyVerdict(data['consistent'], tuple(data['issues']))
            raise ValueError('Некорректный JSON проверки согласованности')
        except Exception as error:
            self.last = dict(valid=False, consistent=None, issues=[], raw=raw, error=f'{type(error).__name__}: {error}')
            return ConsistencyVerdict.ok()
