const legacyKey = 'fable:last-game-id';
const storageKey = (userId: string) => `${legacyKey}:${userId}`;

// The old shared pointer must never be attributed to whichever user signs in first.
function dropLegacyKey() {
  try { localStorage.removeItem(legacyKey); } catch { /* Storage may be restricted. */ }
}
dropLegacyKey();

export function lastGameId(userId: string): string | null {
  dropLegacyKey();
  try { return localStorage.getItem(storageKey(userId)); } catch { return null; }
}

export function rememberGame(userId: string, id: string | null) {
  dropLegacyKey();
  try {
    if (id) localStorage.setItem(storageKey(userId), id);
    else localStorage.removeItem(storageKey(userId));
  } catch { /* Storage can be unavailable in private or restricted browsers. */ }
}
