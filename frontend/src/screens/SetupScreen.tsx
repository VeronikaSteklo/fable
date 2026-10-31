import { useEffect, useRef, useState, type FormEvent } from 'react';
import Field from '../components/Field';
import { createGame } from '../api';
import type { GameSetup } from '../types';

type Props = { onStart: (id: string) => void; onBack: () => void };
const emptySetup: GameSetup = {
  world: '', story: '',
  character: { name: '', role: '', goal: '', description: '', genre: '' },
};

export default function SetupScreen({ onStart, onBack }: Props) {
  const [setup, setSetup] = useState<GameSetup>(emptySetup);
  const updateCharacter = (key: keyof GameSetup['character'], value: string) =>
    setSetup((current) => ({ ...current, character: { ...current.character, [key]: value } }));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const back = () => { request.current?.abort(); onBack(); };
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

  return (
    <main className="setup-page">
      <header className="brand"><span className="brand-mark" aria-hidden="true">✳</span><span>Fable</span></header>
      <section className="setup-content" aria-labelledby="setup-title">
        <button className="text-button back-button" type="button" onClick={back}>← В меню</button>
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
          <button className="primary-button" type="submit" disabled={pending}>{pending ? 'Создаём историю…' : 'Начать игру'} <span aria-hidden="true">→</span></button>
        </form>

      </section>
      <footer className="page-footer">История принадлежит тебе.</footer>
    </main>
  );
}
