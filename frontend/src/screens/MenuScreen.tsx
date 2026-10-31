import { useEffect, useRef, useState } from 'react';
import { deleteGame, listGames } from '../api';
import { lastGameId, rememberGame } from '../savedGame.ts';
import type { GameListItem } from '../types';

type Props = { onStart: (id: string) => void; onNewGame: () => void };
const plural = new Intl.PluralRules('ru-RU');
function turnsLabel(turns: number) {
  const form = plural.select(turns);
  return `${turns} ${form === 'one' ? 'ход' : form === 'few' ? 'хода' : 'ходов'}`;
}
function updatedLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Дата неизвестна' : date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
}

export default function MenuScreen({ onStart, onNewGame }: Props) {
  const [games, setGames] = useState<GameListItem[]>([]);
  const [lastId, setLastId] = useState(lastGameId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const deletion = useRef<AbortController | null>(null);

  const acceptGames = (saved: GameListItem[]) => {
    setGames(saved);
    const remembered = lastGameId();
    if (remembered && !saved.some((game) => game.id === remembered)) {
      rememberGame(null);
      setLastId(null);
    } else setLastId(remembered);
  };
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    listGames(controller.signal).then((saved) => {
      if (!controller.signal.aborted) acceptGames(saved);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Сохранённые истории недоступны. Проверь подключение к серверу.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => () => deletion.current?.abort(), []);

  const remove = async (game: GameListItem) => {
    if (deletion.current || !window.confirm(`Удалить историю «${game.title || 'Без названия'}»? Это действие нельзя отменить.`)) return;
    const controller = new AbortController();
    deletion.current = controller;
    setDeleting(game.id);
    setDeleteError('');
    try {
      await deleteGame(game.id, controller.signal);
      // Read the collection back before reporting successful deletion.
      const saved = await listGames(controller.signal);
      if (saved.some((item) => item.id === game.id)) throw new Error('Сервер не подтвердил удаление истории.');
      if (!controller.signal.aborted) acceptGames(saved);
    } catch (error: unknown) {
      if (!controller.signal.aborted) setDeleteError(error instanceof Error ? error.message : 'Не удалось удалить историю.');
    } finally {
      deletion.current = null;
      if (!controller.signal.aborted) setDeleting(null);
    }
  };
  const lastGame = games.find((game) => game.id === lastId);

  return (
    <main className="setup-page">
      <header className="brand"><span className="brand-mark" aria-hidden="true">✳</span><span>Fable</span></header>
      <section className="setup-content menu-content" aria-labelledby="menu-title">
        <p className="eyebrow">ТВОЯ ИСТОРИЯ ПРОДОЛЖАЕТСЯ</p>
        <h1 id="menu-title">Куда приведёт история?</h1>
        <p className="intro">Создай новый мир или вернись туда, где остановился.</p>
        <button className="primary-button" type="button" onClick={onNewGame}>Новая игра <span aria-hidden="true">→</span></button>
        {!loading && !error && lastGame && <button className="continue-card" type="button" onClick={() => onStart(lastGame.id)} disabled={deleting !== null}>
          <span className="eyebrow">ПРОДОЛЖИТЬ ПОСЛЕДНЮЮ ИСТОРИЮ</span>
          <strong>{lastGame.title || 'Без названия'}</strong>
          <span className="muted">{turnsLabel(lastGame.turns)}</span>
          <span className="continue-label">Продолжить →</span>
        </button>}
        <section className="saved-games" aria-labelledby="saved-title" aria-busy={loading}>
          <h2 id="saved-title">Сохранённые истории</h2>
          {loading ? <p className="muted" role="status">Загружаем истории…</p> : error ? <div className="notice error-notice" role="alert">
            <p>{error}</p>
            <button className="text-button" type="button" onClick={() => setRevision((value) => value + 1)}>Обновить</button>
          </div> : <>
            {deleteError && <p className="notice error-notice" role="alert">{deleteError}</p>}
            {!games.length && <p className="muted">Пока нет сохранённых историй</p>}
            <ul>{games.map((game) => <li key={game.id}>
              <div className="saved-game-info"><strong>{game.title || 'Без названия'}</strong>
                <time className="muted" dateTime={game.updated_at}>{updatedLabel(game.updated_at)}</time>
                <span className="muted">{turnsLabel(game.turns)}</span>
              </div>
              <div className="saved-game-actions">
                <button className="text-button" type="button" onClick={() => onStart(game.id)} disabled={deleting !== null}>Продолжить</button>
                <button className="text-button" type="button" aria-label={`Удалить историю «${game.title || 'Без названия'}»`} onClick={() => void remove(game)} disabled={deleting !== null}>{deleting === game.id ? 'Удаляем…' : 'Удалить'}</button>
              </div>
            </li>)}</ul>
          </>}
        </section>
      </section>
      <footer className="page-footer">История принадлежит тебе.</footer>
    </main>
  );
}
