import { Link } from 'react-router-dom'

const fmt = (n) => n?.toLocaleString() ?? '—'
const fmtDelta = (n) => (n >= 0 ? '+' : '') + n?.toLocaleString()
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', PK: '#888' }

function PlayerChip({ player, highlighted }) {
  const isStarter = player.is_starter
  const isPick = player.position === 'PK'
  return (
    <div className={`player-chip${highlighted ? ' chip-highlighted' : ''}`}>
      <span className="chip-pos" style={{ background: POS_COLOR[player.position] || '#666' }}>
        {player.position || '?'}
      </span>
      <span className="chip-name">{player.name}</span>
      {!isPick && (
        <span className={`chip-role ${isStarter ? 'chip-role-s' : 'chip-role-b'}`}>
          {isStarter ? 'S' : 'B'}
        </span>
      )}
      <span className="chip-val">{fmt(player.fc_value)}</span>
    </div>
  )
}

function LineupTag({ delta }) {
  if (delta == null) return null
  const pos = delta > 0
  const neu = Math.abs(delta) < 200
  return (
    <span className={`lineup-tag ${neu ? 'lineup-neu' : pos ? 'lineup-pos' : 'lineup-neg'}`}>
      {neu ? '~' : pos ? '▲' : '▼'} lineup {fmtDelta(delta)}
    </span>
  )
}

function LineupSummary({ breakdown }) {
  if (!breakdown) return null
  const { starters_lost, bench_lost, starters_gained, bench_gained } = breakdown

  const starterNet = starters_gained - starters_lost
  const benchNet   = bench_gained - bench_lost

  const parts = []

  if (Math.abs(starterNet) >= 50) {
    parts.push(
      <span key="s" className="ls-part">
        <span className="ls-label">Starter quality</span>
        <span className={starterNet > 0 ? 'ls-pos' : 'ls-neg'}>
          {starterNet > 0 ? '+' : ''}{starterNet.toLocaleString()}
        </span>
      </span>
    )
  }
  if (Math.abs(benchNet) >= 50) {
    parts.push(
      <span key="b" className="ls-part">
        <span className="ls-label">Bench</span>
        <span className={benchNet > 0 ? 'ls-pos' : 'ls-neg'}>
          {benchNet > 0 ? '+' : ''}{benchNet.toLocaleString()}
        </span>
      </span>
    )
  }

  if (!parts.length) return null
  return <div className="lineup-summary">{parts}</div>
}

export default function TradeCard({ trade, leagueId, highlightId }) {
  const delta = trade.value_delta
  const fairness = delta < 200 ? '✓ Fair' : delta < 500 ? '~ Close' : '⚠ Lopsided'
  const fairnessClass = delta < 200 ? 'fair' : delta < 500 ? 'close' : 'lopsided'

  const bothUp = trade.lineup_delta_a > 0 && trade.lineup_delta_b > 0

  return (
    <div className={`trade-card${bothUp ? ' trade-card-both-up' : ''}`}>
      <div className="trade-header">
        <span className="trade-reason">{trade.reason}</span>
        <div className="trade-header-badges">
          {bothUp && <span className="badge-both-up">Win-Win</span>}
          <span className={`trade-fairness fairness-${fairnessClass}`}>{fairness}</span>
        </div>
      </div>

      <div className="trade-sides">
        <div className="trade-side">
          <div className="trade-side-header">
            <Link to={`/league/${leagueId}/team/${trade.team_a.roster_id}`} className="trade-team-name">
              {trade.team_a.display_name}
            </Link>
            <LineupTag delta={trade.lineup_delta_a} />
          </div>
          <div className="trade-gives-label">gives</div>
          <div className="trade-players">
            {trade.a_gives.map((p, i) => (
              <PlayerChip key={i} player={p} highlighted={highlightId && p.sleeper_id === highlightId} />
            ))}
          </div>
          <div className="trade-total">Assets: {fmt(trade.value_a_gives)}</div>
          <LineupSummary breakdown={trade.breakdown_a} />
        </div>

        <div className="trade-arrow">⇄</div>

        <div className="trade-side">
          <div className="trade-side-header">
            <Link to={`/league/${leagueId}/team/${trade.team_b.roster_id}`} className="trade-team-name">
              {trade.team_b.display_name}
            </Link>
            <LineupTag delta={trade.lineup_delta_b} />
          </div>
          <div className="trade-gives-label">gives</div>
          <div className="trade-players">
            {trade.b_gives.map((p, i) => (
              <PlayerChip key={i} player={p} highlighted={highlightId && p.sleeper_id === highlightId} />
            ))}
          </div>
          <div className="trade-total">Assets: {fmt(trade.value_b_gives)}</div>
          <LineupSummary breakdown={trade.breakdown_b} />
        </div>
      </div>

      <div className="trade-footer">
        Asset delta: <strong>{fmt(delta)}</strong>
      </div>
    </div>
  )
}
