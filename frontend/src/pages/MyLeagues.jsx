import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { getSleeperUser, saveSleeperUser, clearSleeperUser } from '../utils/sleeperUser'

const fmt = (n) => (n == null ? '—' : Number(n).toFixed(1))
const basePathFor = (mode) => (mode === 'dynasty' || mode === 'keeper' ? 'league' : 'redraft')

// Summaries are fetched per league rather than in one fan-out call, so rows
// appear immediately and one slow league degrades one row. This caps how many
// are in flight at once so a 14-league account doesn't open 14 sockets.
const CONCURRENCY = 4

async function pooled(items, worker, limit = CONCURRENCY) {
  const queue = [...items]
  const runners = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) await worker(queue.shift())
  })
  await Promise.all(runners)
}

function SignIn({ onUser }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    const u = name.trim()
    if (!u) return
    setBusy(true)
    setError('')
    try {
      const user = await api.getSleeperUser(u)
      saveSleeperUser(user)
      onUser(user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="home-hero">
      <h1 className="home-title">Your leagues.<br /><span className="accent">All in one place.</span></h1>
      <p className="home-sub">
        Enter your Sleeper username to see every league you're in, what you're
        leaving on your bench this week, and who's worth picking up. Sleeper's
        API is read-only, so there's no password and nothing to connect — your
        username is stored in this browser only.
      </p>
      <form className="league-form" onSubmit={submit}>
        <input
          className="league-input"
          type="text"
          placeholder="Sleeper username"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Looking…' : 'Find my leagues →'}
        </button>
      </form>
      {error && <p className="rd-error" style={{ marginTop: 12 }}>{error}</p>}
      <p className="home-hint">
        Your username, not your display name — it's under Account in the Sleeper app.
      </p>
    </div>
  )
}

export default function MyLeagues() {
  const [user, setUser] = useState(getSleeperUser)
  const [leagues, setLeagues] = useState(null)
  const [summaries, setSummaries] = useState({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (u) => {
    setLoading(true)
    setError('')
    setSummaries({})
    try {
      const { leagues: rows } = await api.getSleeperUserLeagues(u.user_id)
      setLeagues(rows)
      // Phase two: fill each row in as its summary lands.
      pooled(rows, async (lg) => {
        try {
          const s = await api.getWeeklyLeagueSummary(lg.league_id, u.user_id)
          setSummaries((prev) => ({ ...prev, [lg.league_id]: s }))
        } catch {
          setSummaries((prev) => ({ ...prev, [lg.league_id]: { failed: true } }))
        }
      })
    } catch (e) {
      setError(e.message)
      setLeagues(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (user) load(user) }, [user, load])

  function forget() {
    clearSleeperUser()
    setUser(null)
    setLeagues(null)
    setSummaries({})
  }

  if (!user) return <div className="home-container"><SignIn onUser={setUser} /></div>
  if (loading && !leagues) return <LoadingSpinner message="Finding your leagues…" />

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1 className="page-title">{user.display_name || user.username}</h1>
          <p className="rl-page-sub">
            {leagues ? `${leagues.length} league${leagues.length === 1 ? '' : 's'}` : ''}
            {' · '}
            <button className="filter-clear-inline" onClick={forget}>not you?</button>
          </p>
        </div>
      </div>

      {error && <div className="rd-error">{error}</div>}

      {leagues?.length === 0 && (
        <p className="eval-placeholder">
          No Sleeper leagues found for this season.
        </p>
      )}

      <div className="team-list">
        {(leagues || []).map((lg) => {
          const s = summaries[lg.league_id]
          const base = basePathFor(lg.mode)
          return (
            <div key={lg.league_id} className="wk-league-row">
              <div className="wk-league-main">
                <Link to={`/${base}/${lg.league_id}`} className="wk-league-name">{lg.name}</Link>
                <span className="wk-league-meta">
                  <span className="badge">{lg.mode}</span>
                  {lg.total_rosters ? ` ${lg.total_rosters} teams` : ''}
                  {s?.record && ` · ${s.record.wins}-${s.record.losses}${s.record.ties ? `-${s.record.ties}` : ''}`}
                </span>
              </div>

              <div className="wk-league-stat">
                {!s ? (
                  <span className="wk-league-pending">loading…</span>
                ) : s.failed ? (
                  <span className="wk-league-pending">unavailable</span>
                ) : s.roster_id == null ? (
                  <span className="wk-league-pending">no roster</span>
                ) : s.bench_points_left > 0 ? (
                  <>
                    <span className="wk-total wk-total-gain">+{fmt(s.bench_points_left)}</span>
                    <span className="wk-total-label">
                      on bench {s.bench_points_basis === 'actual' ? '(actual)' : ''}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="wk-total wk-total-best">✓</span>
                    <span className="wk-total-label">lineup optimal</span>
                  </>
                )}
              </div>

              {s?.roster_id != null && !s.failed && (
                <div className="wk-league-links">
                  <Link className="btn btn-secondary btn-sm"
                        to={`/${base}/${lg.league_id}/lineup?roster_id=${s.roster_id}`}>Lineup</Link>
                  <Link className="btn btn-secondary btn-sm"
                        to={`/${base}/${lg.league_id}/waivers?roster_id=${s.roster_id}`}>Waivers</Link>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
