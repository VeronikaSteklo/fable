"""Russian command-line interface for reproducible, offline-capable experiments."""
import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

from fable.config import Settings
from fable.evaluation.configurations import PRESETS
from fable.evaluation.runner import run_experiments
from fable.evaluation.scenarios import load_scenarios


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('нужно целое число >= 1')
    return number


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('нужно целое число >= 0')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description='Сравнение конфигураций мастера Fable')
    parser.add_argument('--scenarios', type=Path, default=Path('eval/scenarios'), help='JSON-файл или каталог сценариев')
    parser.add_argument('--configs', default='static,agentic_full', help='Пресеты через запятую: ' + ', '.join(PRESETS))
    parser.add_argument('--model', action='append', help='Модель мастера; можно повторять')
    parser.add_argument('--judge-model', help='Одна фиксированная модель судьи для всех запусков')
    parser.add_argument('--out', type=Path, help='Новый или пустой каталог результатов')
    parser.add_argument('--turns', type=_nonnegative, help='Число действий (начальная сцена не считается)')
    parser.add_argument('--repeat', type=_positive, default=1, help='Число повторов каждого сочетания')
    parser.add_argument('--history-limit', type=_positive, help='Одинаковое окно истории для всех конфигураций, минимум 2')
    parser.add_argument('--override', action='append', default=[], metavar='CONFIG.FIELD=JSON',
                        help='Изменить фактор пресета: static.history_limit=8, agentic_full.consistency=false')
    parser.add_argument('--dry-run', action='store_true', help='Без сети и .env: детерминированные заглушки и часы')
    args = parser.parse_args(argv)
    try:
        names = args.configs.split(',')
        if any(name not in PRESETS for name in names):
            raise ValueError('Неизвестная конфигурация: ' + args.configs)
        configs = [replace(PRESETS[name], **({'history_limit': args.history_limit} if args.history_limit is not None else {})) for name in names]
        for override in args.override:
            try:
                target, raw = override.split('=', 1)
                name, field = target.split('.', 1)
                if name not in names or field not in ('tools', 'summary', 'consistency', 'companions', 'memory', 'history_limit'):
                    raise ValueError('неизвестный пресет или параметр')
                value = json.loads(raw)
                configs = [replace(c, **{field: value}) if c.name == name else c for c in configs]
            except (ValueError, TypeError) as error:
                raise ValueError(f'Некорректный --override {override}: {error}') from error
        scenarios = load_scenarios(args.scenarios)
        if args.dry_run:
            settings = Settings(_env_file=None, api_key='offline', base_url='http://offline.invalid',
                                model='offline-model', embedding_model=None, temperature=0.7)
        else:
            from fable.bootstrap import load_settings
            settings = load_settings()
        models = args.model or [settings.model]
        if any(not model.strip() for model in models) or (args.judge_model is not None and not args.judge_model.strip()):
            raise ValueError('Идентификатор модели не должен быть пустым')
        out = args.out or Path('eval/results') / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        run_experiments(scenarios, configs, models, settings, out, judge_model=args.judge_model,
                        dry_run=args.dry_run, turns=args.turns, repeat=args.repeat)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
