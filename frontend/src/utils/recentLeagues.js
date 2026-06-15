const KEY = 'spt_recent_leagues'
const MAX = 5

export function saveRecentLeague(league) {
  const { id, name, season } = league
  const existing = getRecentLeagues().filter((l) => l.id !== id)
  const updated = [{ id, name, season, visitedAt: Date.now() }, ...existing].slice(0, MAX)
  localStorage.setItem(KEY, JSON.stringify(updated))
}

export function getRecentLeagues() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]')
  } catch {
    return []
  }
}
