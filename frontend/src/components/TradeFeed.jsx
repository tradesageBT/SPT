import { useState } from 'react'

const fmt = (n) => n?.toLocaleString() ?? '—'
// Signed, so a team's row reads as their outcome rather than a bare total.
const fmtNet = (n) => (n > 0 ? `+${fmt(n)}` : fmt(n))
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
                      {/* The signed net, not a one-sided total. The old value
                          here was what the team GAVE, sitting beside a grade
                          computed from what they RECEIVED — two directions in
                          one row, with nothing saying which was which. */}
                      {side.net_value != null && side.net_value !== 0 && (
                        <span className={`trade-feed-side-total${side.net_value > 0 ? ' net-up' : ' net-down'}`}>
                          {fmtNet(side.net_value)}
                        </span>
                      )}
                    </div>
                    <span className="trade-feed-side-label">Received</span>
                    <div className="trade-feed-assets">
                      {(side.received ?? []).map((a, k) => (
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
                      {(side.received ?? []).length === 0 && (
                        <div className="trade-feed-asset trade-feed-asset-none">nothing</div>
                      )}
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
