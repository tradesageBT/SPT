const KEY = 'spt_recent_leagues'
const MAX = 5

export function saveRecentLeague(league) {
  // `mode` distinguishes dynasty from redraft — without it the two kinds mix in
  // the recents list and a click sends you to the wrong hub.
  const { id, name, season, mode = 'dynasty' } = league
  const existing = getRecentLeagues().filter((l) => !(l.id === id && (l.mode || 'dynasty') === mode))
  const updated = [{ id, name, season, mode, visitedAt: Date.now() }, ...existing].slice(0, MAX)
  localStorage.setItem(KEY, JSON.stringify(updated))
}

export function getRecentLeagues() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]')
  } catch {
    return []
  }
}
