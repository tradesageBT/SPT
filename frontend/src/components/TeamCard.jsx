import { Link } from 'react-router-dom'
import { contentionClass } from '../utils/contention'

const fmt = (n) => n?.toLocaleString() ?? '—'

function SurplusTag({ pos, pct }) {
  const positive = pct >= 0
  return (
    <span className={`surplus-tag ${positive ? 'surplus-pos' : 'surplus-neg'}`}>
      {pos} {positive ? '+' : ''}{pct}%
    </span>
  )
}

const CUSTOM_BADGES = {
  mchakiry: { label: 'Ass until 2027 Rookie Draft', cls: 'winnow' },
}

function ConventionBadge({ category, username }) {
  const custom = CUSTOM_BADGES[username?.toLowerCase()]
  if (custom) return <span className={`contention-badge ${custom.cls}`}>{custom.label}</span>
  return <span className={`contention-badge ${contentionClass(category)}`}>{category}</span>
}

export default function TeamCard({ team, rank, maxValue, leagueId }) {
  const barPct = maxValue ? Math.round((team.total_value / maxValue) * 100) : 0
  const playerPct = team.total_value
    ? Math.round((team.player_value / team.total_value) * 100)
    : 0
  const pickPct = 100 - playerPct

  const surplus = team.positional_surplus || {}

  return (
    <Link to={`/league/${leagueId}/team/${team.roster_id}`} className="team-card">
      <div className="team-card-rank">#{rank}</div>

      <div className="team-card-info">
        {team.avatar && (
          <img
            className="team-avatar-sm"
            src={`https://sleepercdn.com/avatars/thumbs/${team.avatar}`}
            alt={team.display_name}
          />
        )}
        <div>
          <div className="team-name">{team.display_name}</div>
          <ConventionBadge category={team.contention_category} username={team.display_name} />
        </div>
      </div>

      <div className="team-card-value">
        <div className="value-total">{fmt(team.total_value)}</div>
        <div className="value-bar-wrap">
          <div className="value-bar">
            <div className="value-bar-fill" style={{ width: `${barPct}%` }} />
          </div>
        </div>
        <div className="value-split">
          <span className="split-current">{playerPct}% Players</span>
          <span className="split-future">{pickPct}% Picks</span>
        </div>
      </div>

      <div className="team-card-positions">
        {Object.entries(surplus)
          .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
          .map(([pos, pct]) => (
            <SurplusTag key={pos} pos={pos} pct={pct} />
          ))}
      </div>
    </Link>
  )
}
