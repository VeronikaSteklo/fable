import assert from 'node:assert/strict';

const api = await import('../src/api.ts').catch(() => ({}));
assert.equal(typeof api.createSSEParser, 'function', 'SSE parser must be exported');
const events = [];
const parser = api.createSSEParser((event, data) => events.push([event, JSON.parse(data)]));
const wire = ': heartbeat\r\nevent: chunk\r\ndata: {"text":"Привет 🌍"}\r\n\r\nevent: done\ndata: {"summary":"ok"}\n\n';
for (const character of wire) parser.push(character);
assert.deepEqual(events, [['chunk', { text: 'Привет 🌍' }], ['done', { summary: 'ok' }]]);
const multiline = [];
const second = api.createSSEParser((event, data) => multiline.push([event, data]));
second.push('event: chunk\ndata: first\ndata: second\n\nevent: blocked\ndata: {}\n\n');
assert.deepEqual(multiline, [['chunk', 'first\nsecond'], ['blocked', '{}']]);
console.log('SSE parser: split CRLF, Unicode, multi-event chunks, multiline data and comments passed');
