export interface User {
  id: string;
  username: string;
}

export interface Character {
  name: string;
  role: string;
  goal: string;
  description: string;
  genre: string;
}

export interface GameSetup {
  world: string;
  story: string;
  character: Character;
}

export interface Consistency {
  consistent: boolean;
  issues: string[];
}

export interface GameState {
  location: string;
  inventory: string[];
  facts: string[];
}

export interface GameEntry {
  role: 'user' | 'assistant';
  content: string;
  consistency?: Consistency | null;
}

export interface Game {
  id: string;
  setup: GameSetup;
  started: boolean;
  entries: GameEntry[];
  state: GameState;
  summary: string;
}

export interface GameListItem {
  id: string;
  title: string;
  updated_at: string;
  turns: number;
}

export interface StreamResult {
  consistency: Consistency | null;
  state: GameState;
  summary: string;
}

export interface StreamHandlers {
  onChunk: (text: string) => void;
  onDone: (result: StreamResult) => void;
  onBlocked: (message: string) => void;
  onError: (message: string) => void;
}

export interface StoryEntry {
  id: string;
  kind: 'master' | 'player';
  text: string;
  consistency?: Consistency | null;
  rejected?: boolean;
  incomplete?: boolean;
}
