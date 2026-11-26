import assert from 'node:assert/strict';
import { getGame, startGame } from '../src/api.ts';
import { api, load, mount, nodes, text, settle } from './auth-harness.mjs';

const setup = { world: '', story: '', companions: [], character: { name: 'Лея', role: '', goal: '', description: '', genre: '' } };
const state = { location: '', inventory: [], facts: [], companions: [] };
const usage = { prompt_tokens: 80, completion_tokens: 20, total_tokens: 100, llm_calls: 2, estimated: true, cost_usd: .0012, duration_ms: 1200, by_role: { master: { prompt_tokens: 80, completion_tokens: 20, total_tokens: 100, calls: 2 } } };
const legacy = { id: 'u', setup, state, summary: '', started: true, entries: [{ role: 'assistant', content: 'Старый ответ' }] };
const originalFetch = globalThis.fetch;
try {
  globalThis.fetch = async () => Response.json(legacy);
  const old = await getGame('u');
  assert.equal(old.entries[0].usage, null);
  assert.equal(old.usage_total.total_tokens, 0);
  assert.equal(old.usage_total.cost_usd, null);
  globalThis.fetch = async () => Response.json({ ...legacy, entries: [{ role: 'assistant', content: 'Ответ', usage }], usage_total: usage });
  assert.deepEqual((await getGame('u')).usage_total, usage);
  for (const value of [undefined, usage, { total_tokens: 10 }]) {
    globalThis.fetch = async () => new Response(`event: done\ndata: ${JSON.stringify({ state, summary: '', usage: value })}\n\n`);
    let result;
    await startGame('u', { onChunk() {}, onDone(v) { result = v; }, onError(e) { assert.fail(e); }, onBlocked() { assert.fail(); } });
    assert.equal(result.usage?.total_tokens ?? null, value?.total_tokens ?? null);
    if (value) assert.equal(typeof result.usage.estimated, 'boolean');
  }
} finally { globalThis.fetch = originalFetch; }

const { default: GameScreen } = load('screens/GameScreen.tsx');
api.getGame = async () => ({ ...legacy, entries: [{ role: 'assistant', content: 'Ответ', usage }], usage_total: usage });
const screen = mount(GameScreen, { gameId: 'u', onExit() {} });
await settle(screen);
assert.match(text(screen.tree), /≈ 100 токенов/);
assert.match(text(screen.tree), /2 вызовов LLM/);
assert.match(text(screen.tree), /1,2 с/);
assert.match(text(screen.tree), /\$0\.0012/);
assert.match(text(screen.tree), /Расход/);
assert.equal(nodes(screen.tree, n => n.type === 'details' && n.props.className === 'turn-usage').length, 1);
api.sendAction = async (_, __, handlers) => { handlers.onChunk('Дальше'); handlers.onDone({ state, summary: '', usage: { ...usage, estimated: false }, events: [] }); };
nodes(screen.tree, n => n.props.id === 'action')[0].props.onChange({ target: { value: 'Иду' } });
screen.render();
nodes(screen.tree, n => n.type === 'form')[0].props.onSubmit({ preventDefault() {} });
await settle(screen);
assert.match(text(screen.tree), /200 токенов/);
assert.match(text(screen.tree), /\$0\.0024/);
assert.equal(nodes(screen.tree, n => n.type === 'details' && n.props.className === 'turn-usage').length, 2);
screen.unmount();
api.getGame = async () => legacy;
const oldScreen = mount(GameScreen, { gameId: 'old', onExit() {} });
await settle(oldScreen);
assert.equal(nodes(oldScreen.tree, n => n.type === 'details' && n.props.className === 'turn-usage').length, 0);
assert.doesNotMatch(text(oldScreen.tree), /NaN|undefined/);
oldScreen.unmount();
console.log('Usage checks passed: API legacy/partial/done, loaded and streamed entries, estimated/exact labels, cost, game totals');
