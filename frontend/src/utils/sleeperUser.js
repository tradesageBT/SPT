/**
 * The optional Sleeper "login".
 *
 * There is nothing to authenticate: Sleeper's API is read-only and public, so a
 * username is all that's needed to find someone's leagues. No account, no
 * password, no OAuth, no server-side record — this is one localStorage key, and
 * every other page in the app works without it.
 *
 * The resolved user_id is cached alongside the username so the common path
 * never has to hit the resolution endpoint again.
 */
const KEY = 'spt_sleeper_user'

export function getSleeperUser() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const u = JSON.parse(raw)
    return u?.user_id ? u : null
  } catch {
    // Private windows and blocked site data both throw here.
    return null
  }
}

export function saveSleeperUser({ user_id, username, display_name, avatar }) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ user_id, username, display_name, avatar }))
  } catch {
    // Not being able to remember them is not a reason to fail the lookup.
  }
}

export function clearSleeperUser() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* nothing to do */
  }
}
