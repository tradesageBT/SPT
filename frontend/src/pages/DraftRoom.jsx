import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'

const POS_COLOR = {
  QB: '#e05c5c',
  RB: '#5cb8e0',
  WR: '#01d9ac',
  TE: '#e0a45c',
}
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE']
const POLL_MS = 5000

export default function DraftRoom() {
  const { leagueId } = useParams()
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [posFilter, setPosFilter] = useState('ALL')
  const intervalRef = useRef(null)

  async function fetchDraft() {
    try {
      const data = await api.getDraftState(leagueId)
      setState(data)
      setError(null)
      if (data.status === 'complete') {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    } catch (e) {
      setError(e?.message || 'Failed to load draft')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDraft()
    intervalRef.current = setInterval(fetchDraft, POLL_MS)
    return () => clearInterval(intervalRef.current)
  }, [leagueId])

  if (loading) return <LoadingSpinner message="Loading draft room…" />

  if (error) return (
    <div className="error-state">
      <p>❌ {error}</p>
      <Link to={`/league/${leagueId}`} className="btn btn-secondary" style={{ marginTop: '12px' }}>
        ← Back to League
      </Link>
    </div>
  )

  if (!state) return null

  const filtered = posFilter === 'ALL'
    ? state.available
    : state.available.filter((p) => p.position === posFilter)

  const statusLabel = {
    drafting: 'Live',
    complete: 'Complete',
    pre_draft: 'Pre-Draft',
  }[state.status] ?? state.status

  return (
    <div className="draft-room">
      <div className="draft-room-header">
        <div>
          <h1 className="page-title">Draft Room</h1>
          <p className="page-sub">
            {state.picks_made} / {state.total_picks} picks ·{' '}
            <span className={`draft-status-badge draft-status-${state.status}`}>
              {statusLabel}
            </span>
          </p>
        </div>
        <Link to={`/league/${leagueId}`} className="btn btn-secondary">← League</Link>
      </div>

      {state.status === 'drafting' && state.on_the_clock_team && (
        <div className="draft-otc-banner">
          <span className="draft-otc-label">On the Clock</span>
          <span className="draft-otc-team">{state.on_the_clock_team}</span>
          <span className="draft-otc-pick">Pick #{state.picks_made + 1}</span>
        </div>
      )}

      <div className="draft-room-body">
        <div className="draft-available">
          <div className="draft-section-title">
            Available Players
            <span className="draft-available-count">{filtered.length}</span>
          </div>
          <div className="draft-pos-filters">
            {POSITIONS.map((pos) => (
              <button
                key={pos}
                className={`trade-filter-btn${posFilter === pos ? ' active' : ''}`}
                onClick={() => setPosFilter(pos)}
              >
                {pos}
              </button>
            ))}
          </div>
          <div className="draft-player-list">
            {filtered.slice(0, 100).map((p) => (
              <div key={p.sleeper_id} className="draft-player-row">
                <span className="draft-player-pos" style={{ color: POS_COLOR[p.position] || 'var(--text-muted)' }}>
                  {p.position}
                </span>
                <span className="draft-player-name">{p.name}</span>
                <span className="draft-player-nfl">{p.nfl_team}</span>
                <span className="draft-player-val">{p.fc_value.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="draft-sidebar">
          <div className="draft-section-title">Recent Picks</div>
          <div className="draft-recent-list">
            {state.recent_picks.length === 0
              ? <p className="draft-empty">No picks yet</p>
              : state.recent_picks.map((pick, i) => (
                <div key={i} className="draft-recent-row">
                  <div className="draft-recent-meta">
                    <span className="draft-recent-pick-num">#{pick.overall_pick}</span>
                    <span className="draft-recent-team-name">{pick.team_name}</span>
                  </div>
                  <div className="draft-recent-player">
                    <span className="draft-player-pos" style={{ color: POS_COLOR[pick.position] || 'var(--text-muted)' }}>
                      {pick.position}
                    </span>
                    <span className="draft-player-name">{pick.player_name}</span>
                    <span className="draft-player-nfl">{pick.nfl_team}</span>
                  </div>
                </div>
              ))
            }
          </div>

          <div className="draft-section-title" style={{ marginTop: '24px' }}>Team Builds</div>
          <div className="draft-teams-list">
            {state.teams.length === 0
              ? <p className="draft-empty">No picks yet</p>
              : state.teams.map((team) => (
                <div key={team.roster_id} className="draft-team-build">
                  <div className="draft-team-name">
                    {team.slot != null && <span className="draft-team-slot">#{team.slot}</span>}
                    {team.team_name}
                  </div>
                  <div className="draft-team-players">
                    {team.players.length === 0
                      ? <span className="draft-empty">—</span>
                      : team.players.map((p) => (
                        <span
                          key={p.sleeper_id}
                          className="draft-team-chip"
                          style={{ borderColor: POS_COLOR[p.position] || 'var(--border)' }}
                        >
                          <span style={{ color: POS_COLOR[p.position] || 'var(--text-muted)', fontSize: '0.68rem', fontWeight: 700 }}>
                            {p.position}
                          </span>
                          {' '}{p.name}
                        </span>
                      ))
                    }
                  </div>
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </div>
  )
}
