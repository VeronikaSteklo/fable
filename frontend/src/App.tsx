import { useEffect, useRef, useState } from 'react';
import { ApiError, logout, me, setUnauthorizedHandler } from './api';
import AuthScreen from './screens/AuthScreen';
import GameScreen from './screens/GameScreen';
import MenuScreen from './screens/MenuScreen';
import SetupScreen from './screens/SetupScreen';
import { rememberGame } from './savedGame.ts';
import type { User } from './types';

type Screen = { screen: 'menu' } | { screen: 'setup' } | { screen: 'game'; id: string };

export default function App() {
  const [current, setCurrent] = useState<Screen>({ screen: 'menu' });
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [hint, setHint] = useState('');
  const [revision, setRevision] = useState(0);
  const [loggingOut, setLoggingOut] = useState(false);
  const logoutRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setCurrent({ screen: 'menu' });
      setHint('Сессия истекла, войди снова');
      setError('');
      setLoading(false);
    });
    return () => { setUnauthorizedHandler(null); logoutRequest.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    me(controller.signal).then((user) => {
      if (!controller.signal.aborted) setUser(user);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        setHint(''); // A first visit without a cookie is not an expired session.
      } else setError(error instanceof Error ? error.message : 'Не удалось проверить сессию.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  const authenticated = (user: User) => {
    setUser(user);
    setHint('');
    setCurrent({ screen: 'menu' });
  };
  const signOut = async () => {
    if (logoutRequest.current) return;
    const controller = new AbortController();
    logoutRequest.current = controller;
    setLoggingOut(true);
    try { await logout(controller.signal); }
    catch { /* Local logout must also work when the server is unreachable. */ }
    finally {
      logoutRequest.current = null;
      if (!controller.signal.aborted) {
        setUser(null);
        setHint('');
        setCurrent({ screen: 'menu' });
        setLoggingOut(false);
      }
    }
  };
  const menu = () => setCurrent({ screen: 'menu' });
  const open = (id: string) => {
    if (!user) return;
    rememberGame(user.id, id);
    setCurrent({ screen: 'game', id });
  };
  if (loading || error) return <main className="setup-page">
    <header className="brand"><span className="brand-mark" aria-hidden="true">✳</span><span>Fable</span></header>
    <section className="setup-content auth-content">
      {loading ? <p className="muted" role="status">Проверяем сессию…</p> : <div className="notice error-notice" role="alert">
        <p>{error}</p><button className="text-button" type="button" onClick={() => setRevision((value) => value + 1)}>Повторить</button>
      </div>}
    </section>
  </main>;
  if (!user) return <AuthScreen onAuthenticated={authenticated} hint={hint} />;
  if (current.screen === 'game') return <GameScreen key={current.id} gameId={current.id} onExit={menu} />;
  if (current.screen === 'setup') return <SetupScreen onStart={open} onBack={menu} />;
  return <MenuScreen key={user.id} user={user} onLogout={signOut} loggingOut={loggingOut} onStart={open} onNewGame={() => setCurrent({ screen: 'setup' })} />;
}
