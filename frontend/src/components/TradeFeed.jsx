import { useState } from 'react'

const fmt = (n) => n?.toLocaleString() ?? '—'
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', PK: '#888' }

export default function TradeFeed({ trades, loading, error, teams }) {
  const [teamFilter, setTeamFilter] = useState('')

  if (loading) return <div className="trade-feed-status">Loading trade history…</div>
  if (error) return <div className="trade-feed-status">❌ {error}</div>
  if (!trades?.length) return <div className="trade-feed-status">No trades found for this season.</div>

  const displayed = teamFilter
    ? trades.filter((t) => t.sides.some((s) => s.team_name === teamFilter))
    : trades

  return (
    <div className="trade-feed">
      <div className="trade-feed-controls">
        <p className="trade-feed-disclaimer">Values reflect current FC dynasty rankings, not at time of trade.</p>
        <select
          className="partner-filter-select"
          value={teamFilter}
          onChange={(e) => setTeamFilter(e.target.value)}
        >
          <option value="">All teams</option>
          {teams.map((t) => (
            <option key={t.roster_id} value={t.display_name}>{t.display_name}</option>
          ))}
        </select>
      </div>

      {displayed.length === 0 && (
        <div className="trade-feed-status">No trades found for this team.</div>
      )}

      <div className="trade-feed-list">
        {displayed.map((trade, i) => {
          const isEven = trade.winner === 'even'
          const winnerName = isEven ? 'Even' : `${trade.winner} Wins`

          return (
            <div key={i} className="trade-feed-card">
              <div className="trade-feed-card-top">
                <span className="trade-feed-date">{trade.date}</span>
                <span className={`trade-feed-verdict ${isEven ? 'verdict-even' : 'verdict-winner'}`}>
                  {!isEven && <span className="trade-feed-delta">Δ {fmt(trade.value_delta)} · </span>}
                  {winnerName}
                </span>
              </div>

              <div
                className="trade-feed-sides"
                style={{ gridTemplateColumns: `repeat(${trade.sides.length}, 1fr)` }}
              >
                {trade.sides.map((side, j) => (
                  <div key={j} className="trade-feed-side">
                    <div className="trade-feed-side-header">
                      <span className="trade-feed-team">{side.team_name}</span>
                      {side.grade && (
                        <span className={`trade-grade trade-grade-${side.grade.toLowerCase()}`}>
                          {side.grade}
                        </span>
                      )}
                      {side.total_value > 0 && (
                        <span className="trade-feed-side-total">{fmt(side.total_value)}</span>
                      )}
                    </div>
                    {side.reason && (
                      <p className="trade-grade-reason">{side.reason}</p>
                    )}
                    <div className="trade-feed-assets">
                      {side.gave.map((a, k) => (
                        <div key={k} className="trade-feed-asset">
                          <span
                            className="recent-trade-pos"
                            style={{ background: POS_COLOR[a.position] || '#666' }}
                          >
                            {a.position || '?'}
                          </span>
                          <span className="trade-feed-asset-name">{a.name}</span>
                          {a.fc_value > 0 && (
                            <span className="trade-feed-asset-val">{fmt(a.fc_value)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
