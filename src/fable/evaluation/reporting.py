"""Aggregate raw measurements, preserving missing denominators as null/—."""
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import mean, median

from fable.infrastructure.checks.judge import SCORE_KEYS


def _mean(values):
    return mean(values) if values else None


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def aggregate(runs: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for run in runs:
        groups[(run['scenario'], run['config'], run['model'])].append(run)
    result = []
    for (scenario, config, model), group in sorted(groups.items()):
        turns = [turn for run in group for turn in run['turns']]
        completed = [t for t in turns if not t['error']]
        ttft = [t['ttft_ms'] for t in completed if t['ttft_ms'] is not None]
        checked = [t['consistency'] for t in completed if t.get('consistency') is not None]
        valid_checks = [c for c in checked if c['valid']]
        judges = [run['judge'] for run in group]
        valid_judges = [judge for judge in judges if judge['valid']]
        probes = [p for judge in judges for p in judge['probes'] if p['eligible']]
        row = dict(scenario=scenario, config=config, model=model, runs=len(group), turns=len(turns),
                   errors=len(turns)-len(completed),
                   error_rate=_rate(len(turns)-len(completed), len(turns)),
                   mean_ttft_ms=_mean(ttft), median_ttft_ms=median(ttft) if ttft else None,
                   mean_total_ms=_mean([t['total_ms'] for t in turns]),
                   mean_reply_chars=_mean([t['reply_chars'] for t in completed]),
                   consistency_checks=len(checked), consistency_valid=len(valid_checks),
                   consistency_json_valid_rate=_rate(len(valid_checks), len(checked)),
                   consistency_failure_rate=_rate(sum(not c['consistent'] for c in valid_checks), len(valid_checks)),
                   judge_json_valid_rate=_rate(len(valid_judges), len(judges)),
                   probes=len(probes),
                   probe_json_valid_rate=_rate(sum(p['valid'] for p in probes), len(probes)),
                   probe_recall_rate=_rate(sum(p['valid'] and p.get('status') == 'respected' for p in probes), len(probes)),
                   probe_contradiction_rate=_rate(sum(p['valid'] and p.get('status') == 'contradicted' for p in probes), len(probes)))
        row.update({key: _mean([j[key] for j in valid_judges]) for key in SCORE_KEYS})
        result.append(row)
    return result


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _cell(value):
    if value is None:
        return '—'
    if isinstance(value, (int, float)):
        return f'{value:.2f}'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def write_summary(out: Path, runs: list[dict], skipped: list[dict], *, dry_run: bool) -> Path:
    rows = aggregate(runs)
    fields = list(rows[0]) if rows else ['scenario', 'config', 'model', 'runs']
    with (out / 'summary.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    columns = [
        ('scenario', 'Сценарий'), ('config', 'Конфигурация'), ('model', 'Модель'), ('runs', 'R'),
        ('turns', 'Ходы'), ('errors', 'Ошибки'), ('mean_ttft_ms', 'TTFT ср., мс'),
        ('median_ttft_ms', 'TTFT мед., мс'), ('mean_total_ms', 'Полное ср., мс'),
        ('mean_reply_chars', 'Символы ср.'), ('consistency_failure_rate', 'Противоречия'),
        ('consistency_json_valid_rate', 'JSON проверки'), ('coherence', 'Связность'),
        ('character_adherence', 'Герой'), ('no_contradictions', 'Факты'), ('player_agency', 'Агентность'),
        ('judge_json_valid_rate', 'JSON judge'), ('probe_recall_rate', 'Recall'),
        ('probe_json_valid_rate', 'JSON probes'),
    ]
    lines = ['# Результаты эксперимента', '']
    if dry_run:
        lines += ['**ОФЛАЙН-ДЕМО: ответы, оценки и время детерминированы заглушками; это не измерения качества LLM.**', '']
    lines += ['Доли: 0–1; оценки: 1–5; — означает отсутствие наблюдений. Ход 0 — начальная сцена.', '',
              '| ' + ' | '.join(title for _, title in columns) + ' |',
              '| ' + ' | '.join('---' for _ in columns) + ' |']
    lines += ['| ' + ' | '.join(_cell(row[key]) for key, _ in columns) + ' |' for row in rows]
    if skipped:
        lines += ['', '## Пропущенные запуски', '']
        lines += [f"- {item['scenario']} / {item['config']} / {item['model']} / R{item['repeat']}: {item['reason']}" for item in skipped]
    lines += ['', 'Полные знаменатели, доля ошибок и доля противоречий probes — в summary.csv; исходные ответы и проверки — в runs.jsonl и snapshots/.', '']
    target = out / 'summary.md'
    target.write_text('\n'.join(lines), encoding='utf-8')
    return target


def write_transcript(path: Path, scenario, run: dict):
    lines = [f'# {scenario.title}', '', f"Конфигурация: {run['config']}; модель: {run['model']}; повтор: {run['repeat']}", '',
             '## Исходные условия', '', '```json', json.dumps(scenario.setup.to_dict(), ensure_ascii=False, indent=2), '```']
    for turn in run['turns']:
        lines += ['', f"## Ход {turn['turn']}", '', f"Игрок: {turn['action'] or '(начальная сцена)'}", '', 'Мастер:', '', turn['reply']]
        if turn['error']:
            lines += ['', f"Ошибка (ответ не завершён): {turn['error']}"]
    lines += ['', '## Оценка судьи', '', '```json', json.dumps(run['judge'], ensure_ascii=False, indent=2), '```', '']
    path.write_text('\n'.join(lines), encoding='utf-8')
