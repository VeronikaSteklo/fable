import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';

// Run the real TSX components with a tiny hook host: no DOM/test dependencies.
const require = createRequire(import.meta.url);
let host;
const react = {
  useState(initial) {
    const h = host; const i = h.cursor++;
    if (!(i in h.slots)) h.slots[i] = typeof initial === 'function' ? initial() : initial;
    return [h.slots[i], (next) => { h.slots[i] = typeof next === 'function' ? next(h.slots[i]) : next; }];
  },
  useRef(value) { const h = host; const i = h.cursor++; return h.slots[i] ??= { current: value }; },
  useEffect(fn, deps) {
    const h = host; const i = h.cursor++; const previous = h.slots[i];
    if (!previous || deps.some((value, j) => value !== previous.deps[j])) {
      h.effects.push(() => { previous?.cleanup?.(); h.slots[i] = { deps, cleanup: fn() }; });
    }
  },
  useCallback(fn, deps) {
    const h = host; const i = h.cursor++; const previous = h.slots[i];
    if (!previous || deps.some((value, j) => value !== previous.deps[j])) h.slots[i] = { deps, fn };
    return h.slots[i].fn;
  },
};
const jsx = (type, props) => ({ type, props: props || {} });
const store = new Map();
globalThis.localStorage = { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: (key) => store.delete(key) };
globalThis.window = { confirm: () => true };
const api = { listGames: async () => [], deleteGame: async () => {}, getGame: async () => {}, createGame: async () => {} };
const cache = new Map();
function load(file) {
  file = resolve(import.meta.dirname, '../src', file);
  if (cache.has(file)) return cache.get(file);
  const module = { exports: {} }; cache.set(file, module.exports);
  const source = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  const localRequire = (name) => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'fragment' };
    if (name.endsWith('/api')) return api;
    if (name.startsWith('.')) return load(resolve(dirname(file), name.endsWith('.ts') ? name : `${name}.tsx`));
    return require(name);
  };
  vm.runInThisContext(`(function(require, module, exports) {${source}\n})`, { filename: file })(localRequire, module, module.exports);
  cache.set(file, module.exports); return module.exports;
}
function mount(Component, props = {}) {
  const h = { slots: [], cursor: 0, effects: [], tree: null,
    render() { host = h; h.cursor = 0; h.tree = Component(props); h.effects.splice(0).forEach((effect) => effect()); return h.tree; },
    unmount() { h.slots.forEach((slot) => slot?.cleanup?.()); },
  };
  h.render(); return h;
}
function nodes(tree, predicate) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap((item) => nodes(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
}
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  return typeof tree === 'object' ? text(tree.props?.children) : String(tree);
}
const button = (h, label) => nodes(h.tree, (node) => node.type === 'button' && text(node) === label)[0];
const settle = async (h) => { h.render(); for (let i = 0; i < 8; i++) await Promise.resolve(); h.render(); };
const saved = [
  { id: 'last', title: 'Лес', turns: 21, updated_at: '2026-10-31T12:30:00Z' },
  { id: 'other', title: 'Море', turns: 12, updated_at: '2026-10-30T12:30:00Z' },
];
const key = 'fable:last-game-id';
const { default: App } = load('App.tsx');
store.set(key, 'last');
let getCalls = 0;
api.getGame = async () => { getCalls++; };
const app = mount(App);
assert.equal(app.tree.type.name, 'MenuScreen', 'App must open the menu, not restore the last game');
assert.equal(getCalls, 0);
app.tree.props.onNewGame(); app.render();
assert.equal(app.tree.type.name, 'SetupScreen');
app.tree.props.onBack(); app.render();
app.tree.props.onStart('last'); app.render();
assert.equal(app.tree.type.name, 'GameScreen');
assert.equal(store.get(key), 'last');
app.tree.props.onExit(); app.render();
assert.equal(app.tree.type.name, 'MenuScreen');
assert.equal(store.get(key), 'last', 'Exiting must retain the last game');
console.log('Menu navigation checks passed: menu-first load, setup/back, open/exit, last-game retention');

const { default: Menu } = load('screens/MenuScreen.tsx');
let opened;
api.listGames = async () => saved;
let menu = mount(Menu, { onStart: (id) => { opened = id; }, onNewGame() {} });
assert.match(text(menu.tree), /Загружаем/);
await settle(menu);
assert.match(text(menu.tree), /Сохранённые истории/);
assert.match(text(menu.tree), /21 ход/);
assert.match(text(menu.tree), /12 ходов/);
assert.match(text(menu.tree), /31\.10\.2026/);
const continues = nodes(menu.tree, (node) => node.type === 'button' && text(node).includes('Продолжить'));
assert.equal(continues.length, 3, 'Prominent last game plus each saved game');
continues[0].props.onClick(); assert.equal(opened, 'last');
let deletions = 0;
api.deleteGame = async () => { deletions++; };
window.confirm = () => false;
button(menu, 'Удалить').props.onClick(); await settle(menu);
assert.equal(deletions, 0);
window.confirm = () => true;
api.listGames = async () => saved.slice(1);
button(menu, 'Удалить').props.onClick(); await settle(menu);
assert.equal(deletions, 1);
assert.equal(store.has(key), false);
assert.doesNotMatch(text(menu.tree), /Лес/);
menu.unmount();
store.set(key, 'missing');
api.listGames = async () => [];
menu = mount(Menu, { onStart() {}, onNewGame() {} }); await settle(menu);
assert.equal(store.has(key), false);
assert.match(text(menu.tree), /Пока нет сохранённых историй/);
menu.unmount();
api.listGames = async () => { throw new Error('Сервер недоступен'); };
menu = mount(Menu, { onStart() {}, onNewGame() {} }); await settle(menu);
assert.match(text(menu.tree), /Сервер недоступен/);
api.listGames = async () => [{ ...saved[0], turns: 2 }];
button(menu, 'Обновить').props.onClick(); await settle(menu);
assert.match(text(menu.tree), /2 хода/);
menu.unmount();
let listSignal;
api.listGames = (signal) => { listSignal = signal; return new Promise(() => {}); };
menu = mount(Menu, { onStart() {}, onNewGame() {} }); menu.unmount();
assert.equal(listSignal.aborted, true, 'Leaving the menu aborts its pending list request');
store.set(key, 'last');
api.listGames = async () => saved;
menu = mount(Menu, { onStart() {}, onNewGame() {} }); await settle(menu);
api.deleteGame = async () => { throw new Error('Не удалось удалить'); };
button(menu, 'Удалить').props.onClick(); await settle(menu);
assert.match(text(menu.tree), /Не удалось удалить/);
assert.equal(store.get(key), 'last');
assert.match(text(menu.tree), /Лес/);
menu.unmount();
console.log('Saved-games checks passed: loading, last-game shortcut, Russian date/plurals, confirmed deletion, stale id, empty state, network retry, failed deletion, unmount cancellation');

const { default: Setup } = load('screens/SetupScreen.tsx');
let creationSignal; let resolveCreation; let started = false; let back = false;
api.createGame = (_, signal) => { creationSignal = signal; return new Promise((resolve) => { resolveCreation = resolve; }); };
let setup = mount(Setup, { onStart() { started = true; }, onBack() { back = true; } });
assert.doesNotMatch(text(setup.tree), /Сохранённые истории|Твои истории/);
nodes(setup.tree, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} }); setup.render();
button(setup, '← В меню').props.onClick(); setup.unmount();
assert.equal(back, true); assert.equal(creationSignal.aborted, true);
resolveCreation({ id: 'new' }); await settle(setup); assert.equal(started, false);
api.createGame = async () => ({ id: 'new' });
setup = mount(Setup, { onStart(id) { opened = id; }, onBack() {} });
nodes(setup.tree, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} }); await settle(setup);
assert.equal(opened, 'new'); setup.unmount();
console.log('Setup checks passed: creation-only form, back aborts creation, no stale navigation, success opens game');

const { default: Game } = load('screens/GameScreen.tsx');
let streamSignal; let resolveStream; let exits = 0;
api.getGame = async () => ({ id: 'last', started: false, setup: { character: { name: 'Лея' } }, entries: [], state: { inventory: [], facts: [] } });
api.startGame = (_, __, signal) => { streamSignal = signal; return new Promise((resolve) => { resolveStream = resolve; }); };
const game = mount(Game, { gameId: 'last', onExit() { exits++; } });
// Resolve the initial GET so the stream is active before testing either exit control.
for (let i = 0; i < 8; i++) await Promise.resolve();
let confirmation;
window.confirm = (message) => { confirmation = message; return false; };
button(game, 'В меню').props.onClick();
assert.equal(confirmation, 'Ответ ещё пишется. Выйти в меню?'); assert.equal(exits, 0); assert.equal(streamSignal.aborted, false);
window.confirm = () => true;
nodes(game.tree, (node) => node.type === 'button' && text(node).includes('Fable'))[0].props.onClick(); game.unmount();
assert.equal(exits, 1); assert.equal(streamSignal.aborted, true);
resolveStream();
console.log('Game exit checks passed: streaming confirmation/cancel, clickable brand, abort on exit');
