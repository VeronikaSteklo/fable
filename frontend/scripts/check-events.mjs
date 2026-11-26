import assert from 'node:assert/strict';
import { createGame, getGame, startGame, sendAction } from '../src/api.ts';
import { api, load, mount, nodes, text, settle } from './auth-harness.mjs';

const setup = { world: '', story: '', companions: [], character: { name: 'Лея', role: '', goal: '', description: '', genre: '' } };
const state = { location: '', inventory: [], facts: [], companions: [] };
const legacy = { id: 'events', setup, started: true, entries: [{ role: 'assistant', content: 'Начало' }, { role: 'user', content: 'Жду' }], state, summary: '' };
const events = [{ type: 'location_changed', text: 'Вы у реки' }];
const originalFetch = globalThis.fetch;
try {
  for (const entryEvents of [undefined, [], events]) {
    const saved = { ...legacy, entries: legacy.entries.map((entry) => ({ ...entry, ...(entryEvents ? { events: entryEvents } : {}) })) };
    globalThis.fetch = async () => Response.json(saved);
    for (const game of [await getGame('events'), await createGame(setup)]) {
      assert.deepEqual(game.entries[0].events, entryEvents || [], 'Assistant entry events default to []');
      assert.deepEqual(game.entries[1].events, entryEvents || [], 'Entry normalization is consistent');
    }
    globalThis.fetch = async () => new Response(`event: done\ndata: ${JSON.stringify({ consistency: null, state, summary: '', ...(entryEvents ? { events: entryEvents } : {}) })}\n\n`);
    for (const run of [startGame, (id, handlers) => sendAction(id, 'Иду', handlers)]) {
      let result;
      await run('events', { onChunk() {}, onDone(value) { result = value; }, onBlocked() { assert.fail('blocked'); }, onError(message) { assert.fail(message); } });
      assert.deepEqual(result.events, entryEvents || [], 'Done events default to []');
    }
  }
} finally { globalThis.fetch = originalFetch; }
console.log('Event API checks passed: missing/empty/preserved events in create/GET entries and start/action done');

const { default: GameScreen } = load('screens/GameScreen.tsx');
const fixtures = [
  ['location_changed', '📍'], ['item_acquired', '+'], ['item_lost', '−'], ['fact_established', '✦'],
  ['companion_attitude_changed', '↑', 7], ['companion_attitude_changed', '↓', -4],
  ['companion_attitude_changed', '↔', 0], ['companion_learned', '💭'],
  ['companion_left', '←'], ['companion_returned', '→'], ['future_event', '•'],
];
const savedEvents = fixtures.map(([type, , delta], index) => ({ type, text: `Готовое описание ${index}`, ...(delta === undefined ? {} : { companion: 'Мира', delta }) }));
const warning = { consistent: false, issues: ['Проверить мост'] };
api.getGame = async () => ({ ...legacy, entries: [
  { role: 'assistant', content: 'Старый ответ', events: savedEvents, consistency: warning },
  { role: 'user', content: 'Мой ход', events: [{ type: 'item_lost', text: 'Не показывать события игрока' }] },
  { role: 'assistant', content: 'Без событий' },
] });
const screen = mount(GameScreen, { gameId: 'events', onExit() {} });
await settle(screen);
const lists = () => nodes(screen.tree, (node) => node.type === 'ul' && node.props['aria-label'] === 'Изменения за ход');
const articles = () => nodes(screen.tree, (node) => node.type === 'article' && node.props.className?.startsWith('story-entry'));
assert.equal(lists().length, 1, 'Only master replies with non-empty events show a list');
assert.doesNotMatch(text(screen.tree), /Не показывать события игрока/);
const items = nodes(lists()[0], (node) => node.type === 'li');
assert.equal(items.length, fixtures.length);
fixtures.forEach(([, marker], index) => {
  const icon = nodes(items[index], (node) => node.props['aria-hidden'] === 'true')[0];
  assert.equal(text(icon), marker, `Marker for ${fixtures[index][0]}`);
  assert.ok(text(items[index]).includes(savedEvents[index].text), 'Display the supplied description verbatim');
});
assert.match(items[4].props.className, /positive/);
assert.match(items[5].props.className, /negative/);
assert.doesNotMatch(items[6].props.className, /positive|negative/);
assert.ok(text(articles()[0]).indexOf('Проверить мост') < text(articles()[0]).indexOf('Изменения за ход'), 'Events follow the consistency warning');
const submit = async (action) => {
  nodes(screen.tree, (node) => node.props.id === 'action')[0].props.onChange({ target: { value: action } });
  screen.render();
  nodes(screen.tree, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} });
  await settle(screen);
};
let finish;
api.sendAction = async (_, __, handlers) => {
  handlers.onChunk('Новый ответ');
  await new Promise((resolve) => { finish = (result) => { handlers.onDone(result); resolve(); }; });
};
await submit('Иду к реке');
assert.equal(lists().length, 1, 'No events before done');
finish({ consistency: null, state, summary: '', events });
await settle(screen);
assert.equal(lists().length, 2);
assert.ok(text(articles().at(-1)).includes('Вы у реки'), 'Done attaches events to just-streamed master');
assert.equal(articles().at(-2).props.className, 'story-entry player');
assert.ok(!text(articles().at(-2)).includes('Вы у реки'), 'Player entry is untouched');
assert.ok(!text(articles()[0]).includes('Вы у реки'), 'Earlier master is untouched');
api.sendAction = async (_, __, handlers) => { handlers.onChunk('Снова жду'); handlers.onDone({ consistency: null, state, summary: '' }); };
await submit('Жду');
assert.equal(lists().length, 2, 'Legacy done without events does not inherit previous turn events');
assert.ok(!text(articles().at(-1)).includes('Вы у реки'));
screen.unmount();
api.getGame = async () => ({ ...legacy, started: false, entries: [] });
api.startGame = async (_, handlers) => { handlers.onChunk('Вступление'); handlers.onDone({ consistency: null, state, summary: '', events }); };
const intro = mount(GameScreen, { gameId: 'new', onExit() {} });
await settle(intro);
assert.equal(nodes(intro.tree, (node) => node.type === 'ul' && node.props['aria-label'] === 'Изменения за ход').length, 1, 'Initial streamed reply also receives events');
intro.unmount();
console.log('Event UI checks passed: loaded entries, all type markers/fallback, signed attitude colors, warning order, hidden empty/player lists, targeted done attachment, legacy done, initial stream');
