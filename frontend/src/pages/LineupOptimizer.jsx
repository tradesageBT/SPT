import { useEffect, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { PosPill } from '../components/PlayerDetailModal'

const fmt = (n) => (n == null ? '—' : Number(n).toFixed(1))

function Player({ p, muted }) {
  if (!p) return <span className="wk-empty">Empty</span>
  return (
    <span className={`wk-player${muted ? ' wk-muted' : ''}`}>
      <PosPill pos={p.position} />
      <span className="wk-name">{p.name}</span>
      {p.nfl_team && <span className="wk-team">{p.nfl_team}</span>}
    </span>
  )
}

export default function LineupOptimizer({ basePath = 'league' }) {
  const { leagueId } = useParams()
  const [params, setParams] = useSearchParams()
  const rosterId = params.get('roster_id') || ''
  const week = params.get('week') || ''

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!rosterId) { setLoading(false); return }
    setLoading(true)
    api.getWeeklyLineup(leagueId, rosterId, week || undefined)
      .then((d) => { setData(d); setError('') })
      .catch((e) => { setError(e.message); setData(null) })
      .finally(() => setLoading(false))
  }, [leagueId, rosterId, week])

  if (!rosterId) {
    return (
      <div className="trades-page">
        <div className="profile-nav">
          <Link to={`/${basePath}/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
        </div>
        <p className="eval-placeholder">Pick a team from the league page to optimize its lineup.</p>
      </div>
    )
  }

  if (loading) return <LoadingSpinner message="Projecting this week…" />
  if (error) return <div className="rd-error">{error}</div>
  if (!data) return null

  const changes = data.changes || []
  const optimal = changes.length === 0

  return (
    <div className="trades-page">
      <div className="profile-nav">
        <Link to={`/${basePath}/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
      </div>

      <div className="rl-page-header">
        <h1 className="page-title">Week {data.week} Lineup</h1>
        <p className="rl-page-sub">
          {data.team_name} · {data.league_name}
          {!data.sources_ok.sleeper && ' · projections unavailable'}
        </p>
      </div>

      <div className="wk-weekbar">
        {[...Array(18)].map((_, i) => {
          const w = i + 1
          return (
            <button
              key={w}
              className={`wk-week${w === data.week ? ' active' : ''}`}
              onClick={() => setParams({ roster_id: rosterId, week: String(w) })}
            >{w}</button>
          )
        })}
      </div>

      <div className="card-grid">
        <div className="stat-card">
          <div className="stat-card-title">Projected points</div>
          <div className="wk-totals">
            <div><span className="wk-total-label">Your lineup</span><span className="wk-total">{fmt(data.current.total)}</span></div>
            <div><span className="wk-total-label">Optimal</span><span className="wk-total wk-total-best">{fmt(data.optimal.total)}</span></div>
            <div>
              <span className="wk-total-label">Leaving on bench</span>
              <span className={`wk-total${data.delta > 0 ? ' wk-total-gain' : ''}`}>
                {data.delta > 0 ? `+${fmt(data.delta)}` : fmt(0)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {optimal ? (
        <div className="wk-callout wk-callout-good">
          Your lineup is optimal — nothing worth changing by more than{' '}
          {fmt(data.min_delta)} points.
        </div>
      ) : (
        <div className="wk-changes">
          <h2 className="section-title">Suggested changes</h2>
          {changes.map((c, i) => (
            <div key={i} className="wk-change">
              <span className="wk-change-slot">{c.slot_label}</span>
              <span className="wk-change-in">▲ <Player p={c.start} /></span>
              <span className="wk-change-out">▼ <Player p={c.sit} muted /></span>
              <span className="wk-change-gain">+{fmt(c.gain)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="spt-section">
        <div>
          <h2 className="section-title">Optimal lineup</h2>
          <div className="player-table">
            {data.optimal.slots.map((s, i) => (
              <div key={i} className={`player-row${s.optimizable ? '' : ' wk-locked'}`}>
                <span className="rl-slot">{s.slot_label}</span>
                <Player p={s.player} />
                <span className="player-value">{s.optimizable ? fmt(s.points) : '—'}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h2 className="section-title">Your lineup</h2>
          <div className="player-table">
            {data.current.slots.map((s, i) => (
              <div key={i} className="player-row">
                <span className="rl-slot">{s.slot_label}</span>
                <Player p={s.player} muted={!!s.unavailable_reason} />
                <span className="player-value">
                  {s.unavailable_reason ? <span className="wk-out">{s.unavailable_reason}</span> : fmt(s.points)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {data.bench?.length > 0 && (
        <div>
          <h2 className="section-title">Bench ({data.bench.length})</h2>
          <div className="player-table">
            {data.bench.map((p) => (
              <div key={p.player_id} className="player-row">
                <Player p={p} />
                <span className="player-value">{fmt(p.points)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.unavailable?.length > 0 && (
        <div>
          <h2 className="section-title">Not playing</h2>
          <div className="player-table">
            {data.unavailable.map((p) => (
              <div key={p.player_id} className="player-row">
                <Player p={p} muted />
                <span className="wk-out">{p.reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.notes?.map((n, i) => <p key={i} className="rl-note">{n}</p>)}
    </div>
  )
}
