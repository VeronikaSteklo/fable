import type { Game, GameListItem, GameSetup, StreamHandlers, StreamResult, User } from './types.ts';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = message;
  }
}

let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

async function request(path: string, init: RequestInit = {}, base = '/api/games'): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, credentials: 'same-origin' });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new Error('Не удалось связаться с сервером. Проверь подключение и попробуй ещё раз.');
  }
  if (!response.ok) {
    if (response.status === 401 && !init.signal?.aborted) unauthorizedHandler?.();
    const body = await response.json().catch(() => null);
    throw new ApiError(typeof body?.detail === 'string' ? body.detail : `Ошибка сервера (${response.status}). Попробуй ещё раз.`, response.status);
  }
  return response;
}

const jsonBody = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
});
type Credentials = { username: string; password: string };
export async function register(credentials: Credentials, signal?: AbortSignal): Promise<User> {
  return (await (await request('/register', jsonBody(credentials, signal), '/api/auth')).json()).user;
}
export async function login(credentials: Credentials, signal?: AbortSignal): Promise<User> {
  return (await (await request('/login', jsonBody(credentials, signal), '/api/auth')).json()).user;
}
export async function logout(signal?: AbortSignal): Promise<void> {
  await request('/logout', { method: 'POST', signal }, '/api/auth');
}
export async function me(signal?: AbortSignal): Promise<User> {
  return (await (await request('/me', { signal }, '/api/auth')).json()).user;
}

export async function createGame(setup: GameSetup, signal?: AbortSignal): Promise<Game> {
  return (await request('', jsonBody(setup, signal))).json();
}
export async function listGames(signal?: AbortSignal): Promise<GameListItem[]> {
  return (await request('', { signal })).json();
}
export async function getGame(id: string, signal?: AbortSignal): Promise<Game> {
  return (await request(`/${encodeURIComponent(id)}`, { signal })).json();
}
export async function deleteGame(id: string, signal?: AbortSignal): Promise<void> {
  await request(`/${encodeURIComponent(id)}`, { method: 'DELETE', signal });
}

/** Incremental SSE framing; preserves partial lines, including split CRLF pairs. */
export function createSSEParser(onEvent: (event: string, data: string) => void) {
  let buffer = '';
  let event = 'message';
  let data: string[] = [];
  return {
    push(text: string) {
      buffer += text;
      let end: number;
      while ((end = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, end).replace(/\r$/, '');
        buffer = buffer.slice(end + 1);
        if (line === '') {
          if (data.length) onEvent(event, data.join('\n'));
          event = 'message';
          data = [];
        } else if (!line.startsWith(':')) {
          const colon = line.indexOf(':');
          const field = colon < 0 ? line : line.slice(0, colon);
          const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
          if (field === 'event') event = value;
          if (field === 'data') data.push(value);
        }
      }
    },
  };
}

async function stream(path: string, init: RequestInit, handlers: StreamHandlers): Promise<void> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let terminal = false;
  try {
    const response = await request(path, { ...init, headers: { ...init.headers, Accept: 'text/event-stream' } });
    if (!response.body) throw new Error('Сервер не вернул поток истории.');
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = createSSEParser((event, raw) => {
      if (terminal || !['chunk', 'done', 'blocked', 'error'].includes(event)) return;
      const data = JSON.parse(raw);
      if (event === 'chunk') {
        if (typeof data.text !== 'string') throw new Error('Некорректный фрагмент истории.');
        handlers.onChunk(data.text);
      } else {
        terminal = true;
        if (event === 'done') handlers.onDone(data as StreamResult);
        else if (event === 'blocked') handlers.onBlocked(data.message || 'Действие отклонено.');
        else handlers.onError(data.message || 'Не удалось продолжить историю.');
      }
    });
    while (!terminal) {
      const { value, done } = await reader.read();
      if (done) {
        parser.push(decoder.decode());
        if (!terminal) throw new Error('Связь прервалась до завершения ответа.');
        break;
      }
      parser.push(decoder.decode(value, { stream: true }));
    }
  } catch (error) {
    if (!init.signal?.aborted && !terminal) handlers.onError(error instanceof Error ? error.message : 'Не удалось связаться с сервером.');
  } finally {
    if (reader) {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  }
}

export function startGame(id: string, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  return stream(`/${encodeURIComponent(id)}/start`, { method: 'POST', signal }, handlers);
}
export function sendAction(id: string, action: string, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  return stream(`/${encodeURIComponent(id)}/actions`, jsonBody({ action }, signal), handlers);
}
