import type { Usage } from './types.ts';

export function normalizeUsage(value?: Partial<Usage> | null): Usage | null {
  if (!value) return null;
  return {
    prompt_tokens: value.prompt_tokens ?? 0, completion_tokens: value.completion_tokens ?? 0,
    total_tokens: value.total_tokens ?? 0, llm_calls: value.llm_calls ?? 0,
    estimated: value.estimated ?? false, cost_usd: value.cost_usd ?? null,
    duration_ms: value.duration_ms ?? 0,
    by_role: Object.fromEntries(Object.entries(value.by_role ?? {}).map(([role, usage]) => [role, {
      prompt_tokens: usage.prompt_tokens ?? 0, completion_tokens: usage.completion_tokens ?? 0,
      total_tokens: usage.total_tokens ?? 0, calls: usage.calls ?? 0,
    }])),
  };
}

export function sumUsage(values: (Usage | null | undefined)[]): Usage {
  const total = normalizeUsage({})!;
  for (const value of values) {
    if (!value) continue;
    for (const key of ['prompt_tokens', 'completion_tokens', 'total_tokens', 'llm_calls', 'duration_ms'] as const) total[key] += value[key];
    total.estimated ||= value.estimated;
    for (const [role, usage] of Object.entries(value.by_role)) {
      const target = total.by_role[role] ??= { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, calls: 0 };
      for (const key of ['prompt_tokens', 'completion_tokens', 'total_tokens', 'calls'] as const) target[key] += usage[key];
    }
  }
  if (values.length && values.every(v => v?.cost_usd != null)) total.cost_usd = values.reduce((sum, v) => sum + v!.cost_usd!, 0);
  return total;
}

export function usageLabel(value: Usage): string {
  const seconds = (value.duration_ms / 1000).toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${value.estimated ? '≈ ' : ''}${value.total_tokens} токенов · ${value.llm_calls} вызовов LLM · ${seconds} с${value.cost_usd == null ? '' : ` · $${value.cost_usd.toFixed(4)}`}`;
}
