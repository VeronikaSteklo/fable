import assert from 'node:assert/strict';
import * as api from '../src/api.ts';

assert.equal(typeof api.login, 'function', 'Auth client must expose login');
const originalFetch = globalThis.fetch;
const user = { id: 'user-1', username: 'reader' };
const credentials = { username: 'reader', password: 'password123' };
const calls = [];
let unauthorized = 0;
try {
  api.setUnauthorizedHandler(() => unauthorized++);
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return new Response(url.endsWith('/logout') ? null : JSON.stringify({ user }), { status: url.endsWith('/logout') ? 204 : url.endsWith('/register') ? 201 : 200 });
  };
  const controller = new AbortController();
  assert.deepEqual(await api.register(credentials, controller.signal), user);
  assert.deepEqual(await api.login(credentials, controller.signal), user);
  assert.deepEqual(await api.me(controller.signal), user);
  await api.logout(controller.signal);
  assert.deepEqual(calls.map(([url]) => url), ['/api/auth/register', '/api/auth/login', '/api/auth/me', '/api/auth/logout']);
  for (const [, init] of calls) {
    assert.equal(init.credentials, 'same-origin');
    assert.equal(init.signal, controller.signal);
  }
  for (const [, init] of calls.slice(0, 2)) {
    assert.equal(init.method, 'POST');
    assert.equal(init.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(init.body), credentials);
  }
  assert.equal(calls[3][1].method, 'POST');
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return new Response(JSON.stringify({ detail: 'Нужно войти' }), { status: 401 });
  };
  for (const call of [() => api.me(), () => api.login(credentials), () => api.listGames(), () => api.createGame({}), () => api.getGame('x'), () => api.deleteGame('x'), () => api.logout()]) {
    await assert.rejects(call(), (error) => error instanceof api.ApiError && error.status === 401 && error.detail === 'Нужно войти');
  }
  const errors = [];
  const handlers = { onChunk() {}, onDone() {}, onBlocked() {}, onError(message) { errors.push(message); } };
  await api.startGame('x', handlers);
  await api.sendAction('x', 'Иду', handlers);
  assert.equal(unauthorized, 9, 'Every 401, including both stream starts, must notify the app');
  assert.deepEqual(errors, ['Нужно войти', 'Нужно войти']);
  assert.ok(calls.every(([, init]) => init.credentials === 'same-origin'));
  api.setUnauthorizedHandler(null);
  await assert.rejects(api.me());
  assert.equal(unauthorized, 9, 'Handler must be removable');
  console.log('Auth API checks passed: cookie credentials, payloads, signals, user responses, logout, all 401 paths including SSE');
} finally {
  api.setUnauthorizedHandler(null);
  globalThis.fetch = originalFetch;
}
