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

export interface Companion {
  name: string;
  role: string;
  personality: string;
}

export interface CompanionState {
  name: string;
  role: string;
  attitude: number;
  attitude_label: string;
  present: boolean;
  notes: string[];
}

export interface GameSetup {
  world: string;
  story: string;
  character: Character;
  companions: Companion[];
}

export interface Consistency {
  consistent: boolean;
  issues: string[];
}

export interface GameState {
  location: string;
  inventory: string[];
  facts: string[];
  companions: CompanionState[];
}

export interface DomainEvent {
  type: string;
  text: string;
  companion?: string;
  delta?: number;
}

export interface GameEntry {
  role: 'user' | 'assistant';
  content: string;
  consistency?: Consistency | null;
  events?: DomainEvent[];
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
  events: DomainEvent[];
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
  events?: DomainEvent[];
  rejected?: boolean;
  incomplete?: boolean;
}
