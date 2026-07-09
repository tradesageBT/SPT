import { Link } from 'react-router-dom'
import { contentionClass } from '../utils/contention'

const fmt = (n) => n?.toLocaleString() ?? '—'

const POSITIONS = ['QB', 'RB', 'WR', 'TE']

function RankTag({ pos, rank, n }) {
  const third = Math.ceil(n / 3)
  const cls = rank <= third ? 'rank-tag-top' : rank > n - third ? 'rank-tag-bot' : 'rank-tag-mid'
  return (
    <span className={`rank-tag ${cls}`}>
      {pos} <strong>#{rank}</strong>
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

  const posRank = team.positional_rank || {}
  const n = posRank.n || 0

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
        {n > 0 && POSITIONS.filter((pos) => posRank[pos] != null).map((pos) => (
          <RankTag key={pos} pos={pos} rank={posRank[pos]} n={n} />
        ))}
      </div>
    </Link>
  )
}
