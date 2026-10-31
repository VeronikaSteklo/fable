import { useState } from 'react';
import GameScreen from './screens/GameScreen';
import MenuScreen from './screens/MenuScreen';
import SetupScreen from './screens/SetupScreen';
import { rememberGame } from './savedGame.ts';

type Screen = { screen: 'menu' } | { screen: 'setup' } | { screen: 'game'; id: string };

export default function App() {
  const [current, setCurrent] = useState<Screen>({ screen: 'menu' });
  const menu = () => setCurrent({ screen: 'menu' });
  const open = (id: string) => {
    rememberGame(id);
    setCurrent({ screen: 'game', id });
  };
  if (current.screen === 'game') return <GameScreen key={current.id} gameId={current.id} onExit={menu} />;
  if (current.screen === 'setup') return <SetupScreen onStart={open} onBack={menu} />;
  return <MenuScreen onStart={open} onNewGame={() => setCurrent({ screen: 'setup' })} />;
}
