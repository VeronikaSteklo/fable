import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { getGame, sendAction, startGame } from '../api';
import type { Game, StoryEntry, StreamHandlers } from '../types';

type Props = { gameId: string; onExit: () => void };
type Retry = { action?: string; baseline: number };

// crypto.randomUUID exists only in secure contexts (https/localhost), not on http://<ip>.
let entrySeq = 0;
const newEntryId = () => `entry-${Date.now().toString(36)}-${(entrySeq++).toString(36)}`;

function storyEntries(game: Game): StoryEntry[] {
  return game.entries.map((entry, index) => ({
    id: `saved-${index}`, kind: entry.role === 'user' ? 'player' : 'master',
    text: entry.content, consistency: entry.consistency,
  }));
}

export default function GameScreen({ gameId, onExit }: Props) {
  const [game, setGame] = useState<Game | null>(null);
  const [draft, setDraft] = useState('');
  const [entries, setEntries] = useState<StoryEntry[]>([]);
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState<Retry | null>(null);
  const controller = useRef<AbortController | null>(null);
  const active = useRef(false);
  const streaming = useRef(false);
  const exit = () => {
    if (streaming.current && !window.confirm('Ответ ещё пишется. Выйти в меню?')) return;
    controller.current?.abort();
    onExit();
  };
  const bottom = useRef<HTMLDivElement | null>(null);

  const runStream = useCallback(async (current: Game, signal: AbortSignal, action?: string) => {
    if (signal.aborted) return;
    streaming.current = true;
    active.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    setRetry(null);
    const playerId = newEntryId();
    const masterId = newEntryId();
    let text = '';
    setEntries((saved) => [...saved,
      ...(action ? [{ id: playerId, kind: 'player' as const, text: action }] : []),
      { id: masterId, kind: 'master', text: '' },
    ]);
    if (action) setDraft('');
    const handlers: StreamHandlers = {
      onChunk(chunk) {
        if (signal.aborted) return;
        text += chunk;
        setEntries((saved) => saved.map((entry) => entry.id === masterId ? { ...entry, text: entry.text + chunk } : entry));
      },
      onDone(result) {
        if (signal.aborted) return;
        setEntries((saved) => saved.map((entry) => entry.id === masterId ? { ...entry, consistency: result.consistency } : entry));
        setGame({ ...current, started: true, state: result.state, summary: result.summary,
          entries: [...current.entries, ...(action ? [{ role: 'user' as const, content: action }] : []),
            { role: 'assistant', content: text, consistency: result.consistency }],
        });
      },
      onBlocked(message) {
        if (signal.aborted) return;
        setEntries((saved) => saved.filter((entry) => entry.id !== masterId).map((entry) => entry.id === playerId ? { ...entry, rejected: true } : entry));
        setNotice(message);
        if (action) setDraft(action);
      },
      onError(message) {
        if (signal.aborted) return;
        setEntries((saved) => saved.filter((entry) => entry.id !== masterId || entry.text).map((entry) => entry.id === masterId ? { ...entry, incomplete: true } : entry));
        setError(message);
        setRetry({ action, baseline: current.entries.length });
        if (action) setDraft(action);
      },
    };
    try {
      if (action) await sendAction(gameId, action, handlers, signal);
      else await startGame(gameId, handlers, signal);
    } finally {
      streaming.current = false;
      if (!signal.aborted) { active.current = false; setBusy(false); }
    }
  }, [gameId]);

  const load = useCallback(async (signal: AbortSignal, failed?: Retry) => {
    active.current = true;
    setBusy(true);
    setError('');
    try {
      const saved = await getGame(gameId, signal);
      if (signal.aborted) return;
      setGame(saved);
      setEntries(storyEntries(saved));
      setRetry(null);
      if (!saved.started) await runStream(saved, signal);
      else if (failed?.action && saved.entries.length === failed.baseline) {
        await runStream(saved, signal, failed.action);
      } else if (failed) {
        // POST streams are not idempotent: never blindly replay an already persisted turn.
        setNotice('Сохранённая история загружена. Уже записанный ход не отправлен повторно; можно продолжить игру.');
      }
    } catch (error) {
      if (!signal.aborted) setError(error instanceof Error ? error.message : 'Не удалось загрузить игру.');
    } finally {
      if (!signal.aborted) { active.current = false; setBusy(false); }
    }
  }, [gameId, runStream]);

  useEffect(() => {
    const request = new AbortController();
    controller.current = request;
    void load(request.signal);
    return () => { request.abort(); controller.current?.abort(); };
  }, [load]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end', behavior: 'instant' });
  }, [entries, busy, notice, error]);

  const send = (event?: FormEvent) => {
    event?.preventDefault();
    const action = draft.trim();
    if (!action || active.current || !game?.started || retry) return;
    const request = new AbortController();
    controller.current = request;
    void runStream(game, request.signal, action);
  };
  const retryRequest = () => {
    if (active.current) return;
    const request = new AbortController();
    controller.current = request;
    void load(request.signal, retry ?? undefined);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  };

  return (
    <main className="game-page">
      <header className="game-header">
        <button className="brand brand-button" type="button" onClick={exit} aria-label="Fable — в меню"><span className="brand-mark" aria-hidden="true">✳</span>Fable</button>
        <span className="game-title">{game?.setup.character.name || 'Новая история'}</span>
        <button className="text-button" type="button" onClick={exit}>В меню</button>
      </header>
      <section className="story-log" aria-label="История" aria-live="polite">
        {entries.map((entry) => <article className={`story-entry ${entry.kind}${entry.rejected ? ' rejected' : ''}`} key={entry.id}>
          <span className="entry-label">{entry.kind === 'master' ? 'ИСТОРИЯ' : 'ТВОЙ ХОД'}{entry.rejected ? ' · ОТКЛОНЁН' : ''}</span>
          <p>{entry.text || (busy ? 'История рождается…' : 'Ответ завершён.')}</p>
          {entry.incomplete && <small className="muted">Ответ прерван и может быть неполным.</small>}
          {entry.kind === 'master' && entry.consistency?.consistent === false && <small className="consistency-warning">Проверка согласованности: {entry.consistency.issues.join('; ') || 'возможны противоречия'}</small>}
        </article>)}
        {busy && <p className="muted" role="status">{game ? 'Рассказчик пишет…' : 'Загружаем историю…'}</p>}
        {notice && <p className="notice" role="status">{notice}</p>}
        {error && <div className="notice error-notice" role="alert"><p>{error}</p><button type="button" className="text-button" onClick={retryRequest} disabled={busy}>Повторить</button></div>}
        {game && <details className="game-state">
          <summary>Мир и краткое содержание</summary>
          <h2>Место</h2><p>{game.state.location || 'Пока неизвестно'}</p>
          <h2>Инвентарь</h2>{game.state.inventory.length ? <ul>{game.state.inventory.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>Пока пусто</p>}
          <h2>Известные факты</h2>{game.state.facts.length ? <ul>{game.state.facts.map((fact, index) => <li key={index}>{fact}</li>)}</ul> : <p>Пока нет</p>}
          <h2>Краткое содержание</h2><p>{game.summary || 'История только начинается.'}</p>
        </details>}
        <div ref={bottom} />
      </section>
      <form className="composer" onSubmit={send}>
        <label className="sr-only" htmlFor="action">Что ты делаешь?</label>
        <textarea id="action" rows={1} placeholder="Что ты делаешь?" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} disabled={busy || !game?.started || retry !== null} />
        <button type="submit" aria-label="Отправить ход" disabled={busy || !game?.started || retry !== null || !draft.trim()}>↑</button>
        <span className="composer-hint">{busy ? 'Дождись ответа рассказчика' : 'Enter — отправить · Shift+Enter — новая строка'}</span>
      </form>
    </main>
  );
}
