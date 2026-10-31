import assert from 'node:assert/strict';
import { createGame, listGames, getGame, deleteGame, startGame, sendAction, ApiError } from '../src/api.ts';
const originalFetch = globalThis.fetch;
const setup = { world: '', story: '', character: { name: '', role: '', goal: '', description: '', genre: '' } };
const game = { id: 'test', setup, started: false, entries: [], state: { location: '', inventory: [], facts: [] }, summary: '' };
let calls = [];
function mock(body, status = 200) {
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return new Response(status === 204 ? null : JSON.stringify(body), { status });
  };
}
try {
  mock(game, 201);
  assert.deepEqual(await createGame(setup), game);
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), setup);
  mock([ { id: 'test', title: 'Story', turns: 0, updated_at: '' } ]);
  assert.equal((await listGames())[0].id, 'test');
  mock(game);
  assert.equal((await getGame('a/b')).id, 'test');
  assert.equal(calls.at(-1)[0], '/api/games/a%2Fb');
  mock(null, 204);
  await deleteGame('test');
  assert.equal(calls.at(-1)[1].method, 'DELETE');
  mock({ detail: 'Нельзя' }, 422);
  await assert.rejects(createGame(setup), (error) => error instanceof ApiError && error.status === 422 && error.message === 'Нельзя');
  const result = { consistency: { consistent: false, issues: ['test'] }, state: game.state, summary: 'summary' };
  async function run(wire, action = false) {
    const events = [];
    const controller = new AbortController();
    globalThis.fetch = async (url, init) => {
      calls.push([url, init]);
      const bytes = new TextEncoder().encode(wire);
      return new Response(new ReadableStream({ start(stream) {
        for (let i = 0; i < bytes.length; i++) stream.enqueue(bytes.slice(i, i + 1));
        stream.close();
      } }));
    };
    const handlers = { onChunk: (text) => events.push(['chunk', text]), onDone: (data) => events.push(['done', data]), onBlocked: (message) => events.push(['blocked', message]), onError: (message) => events.push(['error', message]) };
    if (action) await sendAction('test', 'Иду', handlers, controller.signal);
    else await startGame('test', handlers, controller.signal);
    assert.equal(calls.at(-1)[1].signal, controller.signal);
    return events;
  }
  assert.deepEqual(await run(`event: chunk\r\ndata: {"text":"Привет 🌍"}\r\n\r\nevent: done\ndata: ${JSON.stringify(result)}\n\n`, true), [['chunk', 'Привет 🌍'], ['done', result]]);
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), { action: 'Иду' });
  assert.deepEqual(await run('event: blocked\ndata: {"message":"Нельзя"}\n\n'), [['blocked', 'Нельзя']]);
  assert.deepEqual(await run('event: error\ndata: {"message":"Сбой"}\n\n'), [['error', 'Сбой']]);
  assert.equal((await run('event: chunk\ndata: {"text":"partial"}\n\n')).at(-1)[0], 'error');
  assert.equal((await run('event: chunk\ndata: invalid\n\n')).at(-1)[0], 'error');
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(listGames(), /Не удалось связаться с сервером/);
  const aborted = new AbortController();
  aborted.abort();
  let abortErrorShown = false;
  await startGame('test', { onChunk() {}, onDone() {}, onBlocked() {}, onError() { abortErrorShown = true; } }, aborted.signal);
  assert.equal(abortErrorShown, false, 'Cancellation must not show a user-facing error');
  console.log('API checks passed: CRUD, 422 details, network failure, request payloads, AbortSignal/cancellation, byte-split UTF-8 streaming, done/blocked/error, truncated/malformed streams');
} finally {
  globalThis.fetch = originalFetch;
}
