import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';

// Exercise real component event handlers without a DOM or added dependencies.
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
};
const jsx = (type, props) => ({ type, props: props || {} });
export const api = {};
const cache = new Map();
export function load(file) {
  file = resolve(import.meta.dirname, '../src', file);
  if (cache.has(file)) return cache.get(file);
  const module = { exports: {} };
  const source = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  const localRequire = (name) => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'fragment' };
    if (/\/api(?:\.ts)?$/.test(name)) return api;
    if (name.startsWith('.')) return load(resolve(dirname(file), /\.(ts|tsx)$/.test(name) ? name : `${name}.tsx`));
    return require(name);
  };
  vm.runInThisContext(`(function(require, module, exports) {${source}\n})`, { filename: file })(localRequire, module, module.exports);
  cache.set(file, module.exports); return module.exports;
}
export function mount(Component, props = {}) {
  const h = { slots: [], cursor: 0, effects: [], tree: null,
    render() { host = h; h.cursor = 0; h.tree = Component(props); h.effects.splice(0).forEach((effect) => effect()); return h.tree; },
    unmount() { h.slots.forEach((slot) => slot?.cleanup?.()); },
  };
  h.render(); return h;
}
export function nodes(tree, predicate) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap((item) => nodes(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
}
export function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  return typeof tree === 'object' ? text(tree.props?.children) : String(tree);
}
export const button = (h, label) => nodes(h.tree, (node) => node.type === 'button' && text(node) === label)[0];
export const settle = async (h) => { h.render(); for (let i = 0; i < 12; i++) await Promise.resolve(); h.render(); };
