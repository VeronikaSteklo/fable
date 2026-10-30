import { useEffect, useState } from 'react';
import GameScreen from './screens/GameScreen';
import SetupScreen from './screens/SetupScreen';
import { ApiError, getGame } from './api';

const storageKey = 'fable:last-game-id';
function storedId(): string | null {
  try { return localStorage.getItem(storageKey); } catch { return null; }
}
function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(storageKey, id);
    else localStorage.removeItem(storageKey);
  } catch { /* Storage can be unavailable in private or restricted browsers. */ }
}

export default function App() {
  const [gameId, setGameId] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [hint, setHint] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const id = storedId();
    if (!id) { setRestoring(false); return; }
    getGame(id, controller.signal).then(() => {
      if (!controller.signal.aborted) setGameId(id);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 404) remember(null);
      else setHint('Не удалось восстановить последнюю игру. Она останется в сохранённых историях.');
    }).finally(() => { if (!controller.signal.aborted) setRestoring(false); });
    return () => controller.abort();
  }, []);
  const open = (id: string) => { remember(id); setHint(''); setGameId(id); };
  const newGame = () => { remember(null); setGameId(null); };
  if (restoring) return <main className="setup-page"><p role="status">Загружаем историю…</p></main>;
  return gameId ? <GameScreen key={gameId} gameId={gameId} onNewGame={newGame} /> : <>
    {hint && <p className="resume-hint muted" role="status">{hint}</p>}
    <SetupScreen onStart={open} />
  </>;
}
