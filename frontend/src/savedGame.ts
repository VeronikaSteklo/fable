const storageKey = 'fable:last-game-id';

export function lastGameId(): string | null {
  try { return localStorage.getItem(storageKey); } catch { return null; }
}

export function rememberGame(id: string | null) {
  try {
    if (id) localStorage.setItem(storageKey, id);
    else localStorage.removeItem(storageKey);
  } catch { /* Storage can be unavailable in private or restricted browsers. */ }
}
