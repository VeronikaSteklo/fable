import { useEffect, useRef, useState, type FormEvent } from 'react';
import { login, register } from '../api';
import Field from '../components/Field';
import type { User } from '../types';

type Props = { onAuthenticated: (user: User) => void; hint?: string };

export default function AuthScreen({ onAuthenticated, hint }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const registering = mode === 'register';
  const switchMode = (next: typeof mode) => {
    setMode(next);
    setPassword('');
    setConfirmation('');
    setError('');
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (request.current) return;
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username)) {
      setError('Имя пользователя: от 3 до 32 символов — латинские буквы, цифры, _, . или -.');
      return;
    }
    if ([...password].length < 8 || [...password].length > 128) {
      setError('Пароль должен содержать от 8 до 128 символов.');
      return;
    }
    if (registering && password !== confirmation) {
      setError('Пароли не совпадают. Повтори пароль.');
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError('');
    try {
      const user = await (registering ? register : login)({ username, password }, controller.signal);
      if (!controller.signal.aborted) onAuthenticated(user);
    } catch (error: unknown) {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Не удалось войти. Попробуй ещё раз.');
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  };

  return (
    <main className="setup-page">
      <header className="brand"><span className="brand-mark" aria-hidden="true">✳</span><span>Fable</span></header>
      <section className="setup-content auth-content" aria-labelledby="auth-title">
        <p className="eyebrow">ТВОЯ ИСТОРИЯ НАЧИНАЕТСЯ ЗДЕСЬ</p>
        <h1 id="auth-title">{registering ? 'Создай свой аккаунт' : 'Вернись в свой мир'}</h1>
        <p className="intro">Войди, чтобы создавать и сохранять свои истории.</p>
        <div className="auth-toggle" role="group" aria-label="Вход или регистрация">
          <button className="text-button" type="button" aria-pressed={!registering} disabled={pending} onClick={() => switchMode('login')}>Вход</button>
          <button className="text-button" type="button" aria-pressed={registering} disabled={pending} onClick={() => switchMode('register')}>Регистрация</button>
        </div>
        {hint && <p className="notice" role="status">{hint}</p>}
        <form onSubmit={submit} noValidate aria-busy={pending} aria-describedby={error ? 'auth-error' : undefined}>
          <Field id="username" label="Имя пользователя" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={pending} required aria-describedby="username-hint" />
          <p id="username-hint" className="muted auth-field-hint">3–32 символа: латинские буквы, цифры, _, . и -.</p>
          <Field id="password" label="Пароль" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={registering ? 'new-password' : 'current-password'} disabled={pending} required aria-describedby="password-hint" />
          <p id="password-hint" className="muted auth-field-hint">От 8 до 128 символов.</p>
          {registering && <Field id="password-confirm" label="Повтори пароль" type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="new-password" disabled={pending} required />}
          {error && <p id="auth-error" className="notice error-notice" role="alert">{error}</p>}
          <button className="primary-button" type="submit" disabled={pending}>{pending ? (registering ? 'Создаём аккаунт…' : 'Входим…') : (registering ? 'Зарегистрироваться' : 'Войти')}</button>
        </form>
      </section>
      <footer className="page-footer">История принадлежит тебе.</footer>
    </main>
  );
}
