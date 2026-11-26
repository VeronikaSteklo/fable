import assert from 'node:assert/strict';
import { createGame, getGame, startGame, sendAction } from '../src/api.ts';
import { api, load, mount, nodes, text, button, settle } from './auth-harness.mjs';

const originalFetch = globalThis.fetch;
const companion = { name: 'Мира', role: 'Следопыт', personality: 'Осторожная' };
const setup = { world: '', story: '', character: { name: 'Лея', role: '', goal: '', description: '', genre: '' } };
const legacy = { id: 'old', setup, started: true, entries: [], state: { location: '', inventory: [], facts: [] }, summary: '' };
try {
  let payload;
  globalThis.fetch = async (_, init) => { payload = JSON.parse(init.body || 'null'); return Response.json(legacy); };
  const created = await createGame({ ...setup, companions: [companion] });
  assert.deepEqual(payload.companions, [companion], 'Creation sends companions');
  assert.deepEqual(created.setup.companions, [], 'Legacy setup defaults to no companions');
  assert.deepEqual(created.state.companions, [], 'Legacy state defaults to no companions');
  const loaded = await getGame('old');
  assert.deepEqual(loaded.setup.companions, []);
  assert.deepEqual(loaded.state.companions, []);
  const stateCompanion = { name: 'Мира', role: 'Следопыт', attitude: -35, attitude_label: 'Недоверие', present: false, notes: ['Герой помог ей'] };
  for (const companions of [undefined, [stateCompanion]]) {
    const result = { consistency: null, state: { ...legacy.state, ...(companions ? { companions } : {}) }, summary: '' };
    globalThis.fetch = async () => new Response(`event: done\ndata: ${JSON.stringify(result)}\n\n`);
    for (const run of [startGame, (id, handlers) => sendAction(id, 'Иду', handlers)]) {
      let done;
      await run('old', { onChunk() {}, onDone(value) { done = value; }, onBlocked() { assert.fail('blocked'); }, onError(message) { assert.fail(message); } });
      assert.deepEqual(done.state.companions, companions || []);
    }
  }
  globalThis.fetch = async () => Response.json({ ...legacy, setup: { ...setup, companions: [companion] }, state: { ...legacy.state, companions: [stateCompanion] } });
  assert.deepEqual((await getGame('old')).state.companions, [stateCompanion]);
  assert.deepEqual((await createGame({ ...setup, companions: [companion] })).setup.companions, [companion]);
} finally { globalThis.fetch = originalFetch; }
console.log('Companion API checks passed: create payload, legacy create/GET defaults, preserved companions, start/action done normalization');

const field = (h, id) => nodes(h.tree, (node) => node.props.id === id)[0];
const change = (h, id, value) => { field(h, id).props.onChange({ target: { value } }); h.render(); };
const submit = async (h) => { await nodes(h.tree, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} }); await settle(h); };
const { default: Setup } = load('screens/SetupScreen.tsx');
let payload; let calls = 0;
api.createGame = async (value) => { payload = value; calls++; return { id: 'new' }; };
const screen = mount(Setup, { onStart() {}, onBack() {} });
assert.match(text(screen.tree), /Спутники \(необязательно\)/);
const add = () => { button(screen, '+ Добавить спутника').props.onClick(); screen.render(); };
const companionFields = () => nodes(screen.tree, (node) => node.props.label === 'Характер');
add(); add(); add();
assert.equal(companionFields().length, 3);
assert.ok(!button(screen, '+ Добавить спутника') || button(screen, '+ Добавить спутника').props.disabled, 'No more than three cards');
const ids = companionFields().map((node) => node.props.id.replace(/-personality$/, ''));
change(screen, `${ids[0]}-role`, 'Друг');
await submit(screen);
assert.equal(calls, 0); assert.match(text(screen.tree), /Укажи имя спутника/);
assert.equal(field(screen, `${ids[0]}-name`).props['aria-invalid'], true);
change(screen, `${ids[0]}-name`, 'ЛЕЯ'); change(screen, 'name', 'лея');
await submit(screen); assert.equal(calls, 0); assert.match(text(screen.tree), /именем героя/);
change(screen, `${ids[0]}-name`, 'Мира'); change(screen, `${ids[1]}-name`, ' мИрА ');
await submit(screen); assert.equal(calls, 0); assert.match(text(screen.tree), /повторяться/);
change(screen, `${ids[1]}-name`, '');
for (const [key, limit] of [['name', 40], ['role', 80], ['personality', 1000]]) {
  const previous = field(screen, `${ids[0]}-${key}`).props.value;
  change(screen, `${ids[0]}-${key}`, 'я'.repeat(limit + 1));
  await submit(screen); assert.equal(calls, 0); assert.match(text(screen.tree), new RegExp(String(limit)));
  change(screen, `${ids[0]}-${key}`, previous);
}
change(screen, `${ids[0]}-name`, ' Мира ');
change(screen, `${ids[0]}-personality`, ' Осторожная ');
await submit(screen);
assert.equal(calls, 1);
assert.deepEqual(payload.companions, [{ ...companion, role: 'Друг' }], 'Fully blank cards are dropped and fields trimmed');
nodes(screen.tree, (node) => node.type === 'button' && text(node) === 'Удалить')[1].props.onClick(); screen.render();
assert.equal(companionFields()[1].props.id, `${ids[2]}-personality`, 'Remaining ids are stable after deletion');
add(); assert.notEqual(companionFields()[2].props.id, `${ids[1]}-personality`, 'Deleted ids are not reused');
api.createGame = async () => { throw new Error('Сервер отклонил спутника'); };
await submit(screen); assert.match(text(screen.tree), /Сервер отклонил спутника/);
screen.unmount();
console.log('Companion setup checks passed: three-card limit, required name, case-insensitive duplicates/hero, length limits, inline errors, empty-card dropping, stable ids, server details');

const { default: Game } = load('screens/GameScreen.tsx');
let currentCompanions = [];
api.getGame = async () => ({ ...legacy, state: { ...legacy.state, companions: currentCompanions } });
let game = mount(Game, { gameId: 'old', onExit() {} }); await settle(game);
assert.doesNotMatch(text(game.tree), /Спутники/); game.unmount();
const mira = { name: 'Мира', role: 'Следопыт', attitude: -35, attitude_label: 'Недоверие', present: false, notes: ['Выручка у реки', 'Помнит обещание'] };
currentCompanions = [mira];
game = mount(Game, { gameId: 'old', onExit() {} }); await settle(game);
assert.match(text(game.tree), /Спутники/); assert.match(text(game.tree), /Мира/); assert.match(text(game.tree), /Следопыт/);
assert.match(text(game.tree), /Недоверие/); assert.match(text(game.tree), /не рядом/);
assert.ok(nodes(game.tree, (node) => node.type === 'details' && text(node).startsWith('Что помнит')).length);
assert.match(text(game.tree), /Помнит обещание/);
const meter = () => nodes(game.tree, (node) => node.props.role === 'meter')[0];
assert.equal(meter().props['aria-valuemin'], -100); assert.equal(meter().props['aria-valuemax'], 100);
assert.equal(meter().props['aria-valuenow'], -35); assert.match(meter().props['aria-label'], /Мира/);
const fill = () => nodes(meter(), (node) => node.props.className?.includes('attitude-fill'))[0];
assert.equal(fill().props.style.left, '32.5%'); assert.equal(fill().props.style.width, '17.5%');
assert.match(fill().props.className, /negative/);
api.sendAction = async (_, __, handlers) => handlers.onDone({ consistency: null, state: { ...legacy.state, companions: [{ ...mira, present: true, attitude: 60, attitude_label: 'Доверие', notes: ['Новое воспоминание'] }] }, summary: 'Новый ход' });
change(game, 'action', 'Помогаю Мире'); await submit(game);
assert.equal(meter().props['aria-valuenow'], 60); assert.match(text(game.tree), /Доверие/); assert.doesNotMatch(text(game.tree), /не рядом/);
assert.equal(fill().props.style.left, '50%'); assert.equal(fill().props.style.width, '30%'); assert.match(fill().props.className, /positive/);
assert.match(text(game.tree), /Новое воспоминание/); assert.doesNotMatch(text(game.tree), /Помнит обещание/);
api.sendAction = async (_, __, handlers) => handlers.onDone({ consistency: null, state: { ...legacy.state, companions: [{ ...mira, attitude: 0, attitude_label: 'Нейтрально', notes: [] }] }, summary: '' });
change(game, 'action', 'Жду'); await submit(game);
assert.equal(fill().props.style.width, '0%'); assert.equal(meter().props['aria-valuenow'], 0); assert.match(text(game.tree), /Нейтрально/);
assert.equal(nodes(game.tree, (node) => node.type === 'details' && text(node).startsWith('Что помнит')).length, 0);
game.unmount();
console.log('Companion panel checks passed: hidden empty state, name/role/label, accessible centered signed meter, absent badge, collapsible notes, live done updates');
