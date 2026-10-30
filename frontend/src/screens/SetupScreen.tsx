import { useEffect, useRef, useState, type FormEvent } from 'react';
import Field from '../components/Field';
import { createGame, deleteGame, listGames } from '../api';
import type { GameListItem, GameSetup } from '../types';

type Props = { onStart: (id: string) => void };
const emptySetup: GameSetup = {
  world: '', story: '',
  character: { name: '', role: '', goal: '', description: '', genre: '' },
};

export default function SetupScreen({ onStart }: Props) {
  const [setup, setSetup] = useState<GameSetup>(emptySetup);
  const updateCharacter = (key: keyof GameSetup['character'], value: string) =>
    setSetup((current) => ({ ...current, character: { ...current.character, [key]: value } }));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [games, setGames] = useState<GameListItem[]>([]);
  const [hint, setHint] = useState('');
  const [deleting, setDeleting] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listGames(controller.signal).then(setGames).catch(() => {
      if (!controller.signal.aborted) setHint('Сохранённые игры недоступны. Проверь подключение к серверу.');
    });
    return () => { controller.abort(); request.current?.abort(); };
  }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError('');
    try {
      const game = await createGame(setup, controller.signal);
      if (!controller.signal.aborted) onStart(game.id);
    } catch (error) {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Не удалось создать игру.');
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  };
  const remove = async (id: string) => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setDeleting(id);
    setHint('');
    try {
      await deleteGame(id, controller.signal);
      // Verify the saved-games collection after deletion.
      const saved = await listGames(controller.signal);
      if (saved.some((game) => game.id === id)) throw new Error('Сервер не подтвердил удаление игры.');
      if (!controller.signal.aborted) setGames(saved);
    } catch (error) {
      if (!controller.signal.aborted) setHint(error instanceof Error ? error.message : 'Не удалось удалить игру.');
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setDeleting(null);
    }
  };

  return (
    <main className="setup-page">
      <header className="brand"><span className="brand-mark" aria-hidden="true">✳</span><span>Fable</span></header>
      <section className="setup-content" aria-labelledby="setup-title">
        <p className="eyebrow">ТВОЯ ИСТОРИЯ НАЧИНАЕТСЯ ЗДЕСЬ</p>
        <h1 id="setup-title">Придумай свой мир</h1>
        <p className="intro">Задай направление — и посмотри, куда приведёт история.</p>
        <form onSubmit={submit}>
          <Field id="world" label="Мир" multiline rows={3} placeholder="Где происходит история?" value={setup.world} onChange={(e) => setSetup({ ...setup, world: e.target.value })} />
          <Field id="story" label="Завязка истории" multiline rows={3} placeholder="С чего всё начинается?" value={setup.story} onChange={(e) => setSetup({ ...setup, story: e.target.value })} />
          <fieldset>
            <legend>Твой герой</legend>
            <div className="field-grid">
              <Field id="name" label="Имя" placeholder="Например, Лея" value={setup.character.name} onChange={(e) => updateCharacter('name', e.target.value)} />
              <Field id="role" label="Роль" placeholder="Кто он или она?" value={setup.character.role} onChange={(e) => updateCharacter('role', e.target.value)} />
              <Field id="goal" label="Цель" placeholder="К чему стремится?" value={setup.character.goal} onChange={(e) => updateCharacter('goal', e.target.value)} />
              <Field id="genre" label="Жанр" placeholder="Например, фэнтези" value={setup.character.genre} onChange={(e) => updateCharacter('genre', e.target.value)} />
            </div>
            <Field id="description" label="Описание героя" multiline rows={3} placeholder="Какой он или она?" value={setup.character.description} onChange={(e) => updateCharacter('description', e.target.value)} />
          </fieldset>
          {error && <p className="notice error-notice" role="alert">{error}</p>}
          <button className="primary-button" type="submit" disabled={pending || deleting !== null}>{pending ? 'Создаём историю…' : 'Начать игру'} <span aria-hidden="true">→</span></button>
        </form>
        <section className="saved-games" aria-labelledby="saved-title">
          <h2 id="saved-title">Твои истории</h2>
          {hint && <p className="muted" role="status">{hint}</p>}
          {!hint && !games.length && <p className="muted">Здесь появятся сохранённые игры.</p>}
          <ul>
            {games.map((game) => <li key={game.id}>
              <div><strong>{game.title || 'Без названия'}</strong><span className="muted">Ходов: {game.turns}</span></div>
              <button className="text-button" type="button" onClick={() => onStart(game.id)} disabled={pending || deleting !== null}>Продолжить</button>
              <button className="text-button" type="button" aria-label={`Удалить историю «${game.title || 'Без названия'}»`} onClick={() => void remove(game.id)} disabled={pending || deleting !== null}>{deleting === game.id ? 'Удаляем…' : 'Удалить'}</button>
            </li>)}
          </ul>
        </section>
      </section>
      <footer className="page-footer">История принадлежит тебе.</footer>
    </main>
  );
}
