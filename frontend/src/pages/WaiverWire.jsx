import { useEffect, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import { PosPill, InjuryTag } from '../components/PlayerDetailModal'

const fmt = (n) => (n == null ? '—' : Number(n).toFixed(1))
const adds = (n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n ?? 0))

export default function WaiverWire({ basePath = 'league' }) {
  const { leagueId } = useParams()
  const [params] = useSearchParams()
  const rosterId = params.get('roster_id') || ''

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [needOnly, setNeedOnly] = useState(false)
  const [startersOnly, setStartersOnly] = useState(false)

  useEffect(() => {
    if (!rosterId) { setLoading(false); return }
    setLoading(true)
    api.getWeeklyWaivers(leagueId, rosterId)
      .then((d) => { setData(d); setError('') })
      .catch((e) => { setError(e.message); setData(null) })
      .finally(() => setLoading(false))
  }, [leagueId, rosterId])

  if (!rosterId) {
    return (
      <div className="trades-page">
        <div className="profile-nav">
          <Link to={`/${basePath}/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
        </div>
        <p className="eval-placeholder">Pick a team from the league page to see waiver targets.</p>
      </div>
    )
  }

  if (loading) return <LoadingSpinner message="Checking the wire…" />
  if (error) return <div className="rd-error">{error}</div>
  if (!data) return null

  const isDynasty = data.mode === 'dynasty'
  const targets = (data.targets || []).filter((t) =>
    (!needOnly || t.fills_need) && (!startersOnly || t.would_start)
  )

  return (
    <div className="trades-page">
      <div className="profile-nav">
        <Link to={`/${basePath}/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
        <Link to={`/${basePath}/${leagueId}/lineup?roster_id=${rosterId}`} className="btn btn-secondary btn-sm">
          Lineup Optimizer
        </Link>
      </div>

      <div className="rl-page-header">
        <h1 className="page-title">Waiver Wire</h1>
        <p className="rl-page-sub">
          Week {data.week} · {data.league_name}
          {data.needs?.top_need && ` · biggest need: ${data.needs.top_need}`}
        </p>
      </div>

      <div className="rl-controls">
        <div className="rl-control-group">
          <label className="pool-option">
            <input type="checkbox" checked={needOnly} onChange={(e) => setNeedOnly(e.target.checked)} />
            Fills a need
          </label>
          <label className="pool-option">
            <input type="checkbox" checked={startersOnly} onChange={(e) => setStartersOnly(e.target.checked)} />
            Would crack my lineup
          </label>
        </div>
      </div>

      <p className="rl-note">
        {/* The filtering is the point — Sleeper's trending list is league-wide
            and mostly players you can't have. */}
        Most-added players across Sleeper in the last 24 hours, narrowed to those
        actually unrostered in this league. Points are projected for week{' '}
        {data.week} under your league's scoring.
        {!data.sources_ok?.trending && ' Trending data is unavailable right now.'}
      </p>

      {targets.length === 0 ? (
        <p className="eval-placeholder">
          {data.targets?.length
            ? 'No trending free agents match those filters.'
            : 'No trending players are free in this league right now.'}
        </p>
      ) : (
        <div className="player-table">
          {targets.map((t) => (
            <div key={t.player_id} className="player-row">
              <PosPill pos={t.position} />
              <span className="wk-name">{t.name}</span>
              {t.nfl_team && <span className="wk-team">{t.nfl_team}</span>}
              <InjuryTag meta={{ injury_status: t.injury_status }} />
              {t.fills_need && <span className="wk-tag wk-tag-need">need</span>}
              {t.would_start && (
                <span className="wk-tag wk-tag-start">+{fmt(t.lineup_gain)} to lineup</span>
              )}
              {isDynasty && t.dynasty_value != null && (
                <span className="wk-tag wk-tag-dyn">
                  dynasty {t.dynasty_value.toLocaleString()}
                </span>
              )}
              <span className="wk-adds" title="Added across Sleeper in 24h">
                {adds(t.adds_24h)} adds
              </span>
              <span className="player-value">{fmt(t.proj_points)}</span>
            </div>
          ))}
        </div>
      )}

      {isDynasty && (
        <p className="rl-note">
          Dynasty value is shown alongside this week's projection, not blended
          into it — a streamer and a stash are different decisions.
          {data.sources_ok?.dynasty_values === false &&
            ' Values are unavailable until this league syncs.'}
        </p>
      )}
    </div>
  )
}
