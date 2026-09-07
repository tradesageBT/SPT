import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import PositionalBreakdown from '../components/PositionalBreakdown'

const fmt = (n) => n?.toLocaleString() ?? '—'
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', K: '#8b90b0', DEF: '#666c8a' }

export default function RedraftTeamPage() {
  const { leagueId, rosterId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.getRedraftTeam(leagueId, rosterId).then(setData).catch(e => setError(e.message))
  }, [leagueId, rosterId])

  if (error) return <div className="rd-error">{error}</div>
  if (!data) return <div className="rd-loading">Loading team…</div>

  // Slot order comes from the server, which rebuilds it from the league's own
  // roster_positions — QB, RB, RB, WR... FLEX, SFLEX, exactly as Sleeper shows it.
  const lineup = data.lineup ?? []
  const bench = data.bench ?? data.players.filter(p => !p.is_starter)
  const starterPct = data.total_value
    ? Math.round((data.starter_value / data.total_value) * 100) : 0

  const Row = ({ p, slot }) => (
    <div className="player-row">
      {slot && <span className="rl-slot">{slot}</span>}
      {p ? (
        <>
          <span className="player-pos-badge" style={{ background: POS_COLOR[p.position] || '#666' }}>
            {p.position}
          </span>
          <span className="player-name">{p.name}</span>
          <span className="player-team">{p.nfl_team}</span>
          <span className="player-pos-rank">
            {p.redraft_pos_rank ? `${p.position}${p.redraft_pos_rank}` : '—'}
          </span>
          <span className="player-value">{fmt(p.redraft_value)}</span>
        </>
      ) : (
        // Keep the slot visible rather than collapsing the row — an unfilled
        // starting spot is the thing you most want to see on this page.
        <span className="rl-slot-empty">Empty</span>
      )}
    </div>
  )

  return (
    <div className="team-profile">
      <div className="profile-nav">
        <Link to={`/redraft/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
        <Link to={`/redraft/${leagueId}/trades?roster_id=${rosterId}`} className="btn btn-secondary btn-sm">
          Trade Ideas for This Team
        </Link>
        <Link to={`/redraft/${leagueId}/lineup?roster_id=${rosterId}`} className="btn btn-secondary btn-sm">
          Optimize Lineup
        </Link>
      </div>

      <div className="profile-header">
        <div>
          <h1 className="page-title">{data.display_name}</h1>
          <p className="league-meta">
            Roster value {fmt(data.total_value)}
            {data.strength_tier && ` · ${data.strength_tier}`}
            {data.strength_rank && ` · #${data.strength_rank} of ${data.num_teams}`}
          </p>
        </div>
      </div>

      {/* No Assets card — that split is players vs draft picks, and redraft has
          no picks. Depth is the one that carries over. */}
      <div className="card-grid">
        <div className="stat-card">
          <div className="stat-card-title">Depth</div>
          <div className="split-bar">
            <div className="split-segment" style={{ width: `${starterPct}%` }} />
            <div className="split-segment future" style={{ width: `${100 - starterPct}%` }} />
          </div>
          <div className="split-legend">
            <span className="split-current">Starters ({fmt(data.starter_value)})</span>
            <span className="split-future">Bench ({fmt(data.bench_value)})</span>
          </div>
        </div>
      </div>

      <PositionalBreakdown
        breakdown={data.positional_breakdown}
        rank={data.positional_rank}
      />

      <div className="spt-section">
        <div>
          <h2 className="section-title">Starting Lineup ({lineup.filter(e => e.player).length}/{lineup.length})</h2>
          <div className="player-table">
            {/* Keyed by index, not player id: an empty slot has no id, and two
                slots of the same name (RB, RB) are distinct rows. */}
            {lineup.map((e, i) => <Row key={i} slot={e.slot} p={e.player} />)}
          </div>
        </div>
        <div>
          <h2 className="section-title">Bench ({bench.length})</h2>
          <div className="player-table">{bench.map(p => <Row key={p.sleeper_id} p={p} />)}</div>
        </div>
      </div>
    </div>
  )
}
