import { useEffect, useRef, useState, type FormEvent } from 'react';
import Field from '../components/Field';
import { createGame } from '../api';
import type { Companion, GameSetup } from '../types';

type Props = { onStart: (id: string) => void; onBack: () => void };
type CompanionDraft = Companion & { id: string };
type CompanionErrors = Partial<Record<keyof Companion, string>>;
const emptySetup: GameSetup = {
  world: '', story: '', companions: [],
  character: { name: '', role: '', goal: '', description: '', genre: '' },
};

export default function SetupScreen({ onStart, onBack }: Props) {
  const [setup, setSetup] = useState<GameSetup>(emptySetup);
  const updateCharacter = (key: keyof GameSetup['character'], value: string) =>
    setSetup((current) => ({ ...current, character: { ...current.character, [key]: value } }));
  const [companions, setCompanions] = useState<CompanionDraft[]>([]);
  const companionSeq = useRef(0);
  const [validationShown, setValidationShown] = useState(false);
  const updateCompanion = (id: string, key: keyof Companion, value: string) =>
    setCompanions((current) => current.map((item) => item.id === id ? { ...item, [key]: value } : item));
  // Validate trimmed values; wholly empty cards are intentionally omitted from the request.
  const prepared = companions.map(({ id, name, role, personality }) => ({ id, name: name.trim(), role: role.trim(), personality: personality.trim() }))
    .filter(({ name, role, personality }) => name || role || personality);
  const companionErrors: Record<string, CompanionErrors> = {};
  for (const item of prepared) {
    const errors: CompanionErrors = {};
    if (!item.name) errors.name = 'Укажи имя спутника.';
    else if ([...item.name].length > 40) errors.name = 'Имя спутника — не больше 40 символов.';
    else if (item.name.toLowerCase() === setup.character.name.trim().toLowerCase()) errors.name = 'Имя спутника не должно совпадать с именем героя.';
    else if (prepared.some((other) => other.id !== item.id && other.name.toLowerCase() === item.name.toLowerCase())) errors.name = 'Имена спутников не должны повторяться.';
    if ([...item.role].length > 80) errors.role = 'Роль — не больше 80 символов.';
    if ([...item.personality].length > 1000) errors.personality = 'Характер — не больше 1000 символов.';
    if (Object.keys(errors).length) companionErrors[item.id] = errors;
  }
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const back = () => { request.current?.abort(); onBack(); };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (request.current) return;
    setValidationShown(true);
    setError('');
    if (Object.keys(companionErrors).length) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    try {
      const game = await createGame({ ...setup, companions: prepared.map(({ name, role, personality }) => ({ name, role, personality })) }, controller.signal);
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
        <form onSubmit={submit} aria-busy={pending}>
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
          <fieldset className="companions-setup" disabled={pending} aria-describedby="companions-hint">
            <legend>Спутники (необязательно)</legend>
            <p id="companions-hint" className="muted companion-hint">Спутники — отдельные персонажи со своим характером. Они реагируют на события и помнят, как герой с ними обращался.</p>
            {companions.map((item, index) => <section className="companion-card" key={item.id} aria-labelledby={`${item.id}-title`}>
              <div className="companion-heading"><h2 id={`${item.id}-title`}>Спутник {index + 1}</h2><button className="text-button" type="button" aria-label={`Удалить спутника ${index + 1}`} onClick={() => setCompanions((current) => current.filter((other) => other.id !== item.id))}>Удалить</button></div>
              <div className="field-grid">
                {(['name', 'role'] as const).map((key) => {
                  const message = validationShown ? companionErrors[item.id]?.[key] : undefined;
                  return <div key={key}>
                    <Field id={`${item.id}-${key}`} label={key === 'name' ? 'Имя' : 'Роль'} value={item[key]} onChange={(e) => updateCompanion(item.id, key, e.target.value)} aria-invalid={!!message} aria-describedby={message ? `${item.id}-${key}-error` : undefined} />
                    {message && <p className="companion-error error-notice" id={`${item.id}-${key}-error`} role="alert">{message}</p>}
                  </div>;
                })}
              </div>
              <Field id={`${item.id}-personality`} label="Характер" multiline rows={3} value={item.personality} onChange={(e) => updateCompanion(item.id, 'personality', e.target.value)} aria-invalid={validationShown && !!companionErrors[item.id]?.personality} aria-describedby={validationShown && companionErrors[item.id]?.personality ? `${item.id}-personality-error` : undefined} />
              {validationShown && companionErrors[item.id]?.personality && <p className="companion-error error-notice" id={`${item.id}-personality-error`} role="alert">{companionErrors[item.id].personality}</p>}
            </section>)}
            {companions.length < 3 && <button className="text-button companion-add" type="button" onClick={() => {
              const id = `companion-${companionSeq.current++}`;
              setCompanions((current) => current.length < 3 ? [...current, { id, name: '', role: '', personality: '' }] : current);
            }}>+ Добавить спутника</button>}
          </fieldset>
          {error && <p className="notice error-notice" role="alert">{error}</p>}
          <button className="primary-button" type="submit" disabled={pending}>{pending ? 'Создаём историю…' : 'Начать игру'} <span aria-hidden="true">→</span></button>
        </form>
      </section>
      <footer className="page-footer">История принадлежит тебе.</footer>
    </main>
  );
}
