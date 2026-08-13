import { useState, useMemo, useEffect } from 'react'

const fmt = (n) => n?.toLocaleString() ?? '—'
const fmtNet = (n) => (n > 0 ? `+${n.toLocaleString()}` : n.toLocaleString())
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', PK: '#888' }

const MEDAL = { 0: '🥇', 1: '🥈', 2: '🥉' }

function AssetChip({ a }) {
  return (
    <div className="tlb-asset">
      <span className="recent-trade-pos" style={{ background: POS_COLOR[a.position] || '#666' }}>
        {a.position || '?'}
      </span>
      <span className="tlb-asset-name">{a.name}</span>
      {a.fc_value > 0 && <span className="tlb-asset-val">{fmt(a.fc_value)}</span>}
    </div>
  )
}

function TeamTradeModal({ team, onClose }) {
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const sorted = [...team.trades].sort((a, b) => b.ts - a.ts)
  const avgPerTrade = team.total_trades ? Math.round(team.net_value / team.total_trades) : 0

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-sheet tlb-modal-sheet" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">{team.team_name}</div>
            <div className="modal-subtitle">
              <span className={team.net_value >= 0 ? 'tlb-pos' : 'tlb-neg'}>
                {fmtNet(team.net_value)} total
              </span>
              {' · '}{team.total_trades} trade{team.total_trades !== 1 ? 's' : ''}
              {team.total_trades > 0 && (
                <> · avg <span className={avgPerTrade >= 0 ? 'tlb-pos' : 'tlb-neg'}>{fmtNet(avgPerTrade)}</span>/trade</>
              )}
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {sorted.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontStyle: 'italic', textAlign: 'center', padding: '20px 0' }}>
              No trades this season.
            </p>
          ) : sorted.map((trade, i) => {
            const isPositive = trade.net_value > 0
            const counterStr = trade.counterparties.length === 1
              ? trade.counterparties[0]
              : trade.counterparties.slice(0, -1).join(', ') + ' & ' + trade.counterparties.slice(-1)
            return (
              <div key={i} className="tlb-trade-card">
                <div className="tlb-trade-header">
                  <div className="tlb-trade-meta">
                    {trade.date && <span className="tlb-trade-date">{trade.date}</span>}
                    <span className="tlb-trade-vs">vs {counterStr}</span>
                  </div>
                  <div className="tlb-trade-badges">
                    {trade.grade && (
                      <span className={`trade-grade trade-grade-${trade.grade.toLowerCase()}`}>
                        {trade.grade}
                      </span>
                    )}
                    <span className={`tlb-net-chip ${isPositive ? 'tlb-net-pos' : trade.net_value < 0 ? 'tlb-net-neg' : 'tlb-net-even'}`}>
                      {fmtNet(trade.net_value)}
                    </span>
                  </div>
                </div>

                {trade.reason && (
                  <p className="trade-grade-reason" style={{ margin: '4px 0 6px' }}>{trade.reason}</p>
                )}

                <div className="tlb-trade-sides">
                  {trade.gave.length > 0 && (
                    <div className="tlb-trade-section">
                      <span className="tlb-section-label gave-label">Gave</span>
                      {trade.gave.map((a, k) => <AssetChip key={k} a={a} />)}
                    </div>
                  )}
                  {trade.received.length > 0 && (
                    <div className="tlb-trade-section">
                      <span className="tlb-section-label got-label">Received</span>
                      {trade.received.map((a, k) => <AssetChip key={k} a={a} />)}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function AcquiredTable({ title, teams, gotKey, gaveKey, onSelect }) {
  const sorted = [...teams]
    .filter(t => t[gotKey] > 0 || t[gaveKey] > 0)
    .sort((a, b) => (b[gotKey] - b[gaveKey]) - (a[gotKey] - a[gaveKey]))

  if (!sorted.length) return null

  return (
    <div className="tlb-sub-table">
      <div className="tlb-sub-title">{title}</div>
      <div className="tlb-sub-header">
        <span className="tlb-col-rank">#</span>
        <span className="tlb-col-team">Team</span>
        <span className="tlb-col-stat">Got</span>
        <span className="tlb-col-stat">Gave</span>
        <span className="tlb-col-stat">Net</span>
      </div>
      {sorted.map((team, idx) => {
        const net = team[gotKey] - team[gaveKey]
        const netCls = net > 0 ? 'tlb-pos' : net < 0 ? 'tlb-neg' : ''
        return (
          <div
            key={team.roster_id}
            className="tlb-sub-row"
            onClick={() => onSelect(team.roster_id)}
          >
            <span className="tlb-col-rank">
              {MEDAL[idx] ?? <span className="tlb-rank-num">{idx + 1}</span>}
            </span>
            <span className="tlb-col-team">{team.team_name}</span>
            <span className="tlb-col-stat tlb-pos">{team[gotKey]}</span>
            <span className="tlb-col-stat tlb-neg">{team[gaveKey]}</span>
            <span className={`tlb-col-stat tlb-val ${netCls}`}>{fmtNet(net)}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function TradeLeaderboard({ trades, loading, error, teams }) {
  const [selected, setSelected] = useState(null)

  const leaderboard = useMemo(() => {
    const stats = {}
    for (const team of teams) {
      stats[team.display_name] = {
        roster_id: team.roster_id,
        team_name: team.display_name,
        net_value: 0,
        total_trades: 0,
        players_given: 0,
        players_received: 0,
        picks_given: 0,
        picks_received: 0,
        trades: [],
      }
    }

    if (trades) {
      for (const trade of trades) {
        const allTeamNames = new Set(trade.sides.map(s => s.team_name))
        for (const side of trade.sides) {
          const stat = stats[side.team_name]
          if (!stat) continue
          stat.total_trades++
          stat.net_value += side.net_value || 0
          for (const a of side.gave || []) {
            if (a.position === 'PK') stat.picks_given++
            else stat.players_given++
          }
          for (const a of side.received || []) {
            if (a.position === 'PK') stat.picks_received++
            else stat.players_received++
          }
          stat.trades.push({
            date: trade.date,
            ts: trade.ts || 0,
            counterparties: trade.sides
              .filter(s => s.team_name !== side.team_name)
              .map(s => s.team_name),
            gave: side.gave || [],
            received: side.received || [],
            grade: side.grade,
            reason: side.reason,
            net_value: side.net_value || 0,
          })
        }
      }
    }

    return Object.values(stats).sort((a, b) => b.net_value - a.net_value)
  }, [trades, teams])

  if (loading) return <div className="trade-feed-status">Loading trade data…</div>
  if (error) return <div className="trade-feed-status">❌ {error}</div>

  const selectedStat = selected ? leaderboard.find(t => t.roster_id === selected) : null

  return (
    <div className="trade-leaderboard">
      <div className="tlb-disclaimer">
        Click any team to see their full trade history. Values reflect current FC rankings.
      </div>

      <div className="tlb-table">
        <div className="tlb-header-row">
          <span className="tlb-col-rank">#</span>
          <span className="tlb-col-team">Team</span>
          <span className="tlb-col-stat">Net Value</span>
          <span className="tlb-col-stat tlb-hide-sm">Players +/-</span>
          <span className="tlb-col-stat tlb-hide-sm">Picks +/-</span>
          <span className="tlb-col-stat">Per Trade</span>
        </div>

        {leaderboard.map((team, idx) => {
          const avgPerTrade = team.total_trades
            ? Math.round(team.net_value / team.total_trades)
            : 0
          const playerNet = team.players_received - team.players_given
          const pickNet = team.picks_received - team.picks_given
          const netCls = team.net_value > 0 ? 'tlb-pos' : team.net_value < 0 ? 'tlb-neg' : ''
          const avgCls = avgPerTrade > 0 ? 'tlb-pos' : avgPerTrade < 0 ? 'tlb-neg' : ''
          const playerCls = playerNet > 0 ? 'tlb-pos' : playerNet < 0 ? 'tlb-neg' : ''
          const pickCls = pickNet > 0 ? 'tlb-pos' : pickNet < 0 ? 'tlb-neg' : ''

          return (
            <div
              key={team.roster_id}
              className={`tlb-row${team.total_trades === 0 ? ' tlb-row-inactive' : ''}`}
              onClick={() => team.total_trades > 0 && setSelected(team.roster_id)}
              title={team.total_trades > 0 ? 'Click to view trade history' : 'No trades this season'}
            >
              <span className="tlb-col-rank">
                {MEDAL[idx] ?? <span className="tlb-rank-num">{idx + 1}</span>}
              </span>
              <span className="tlb-col-team">
                {team.team_name}
                {team.total_trades > 0 && (
                  <span className="tlb-trade-count"> · {team.total_trades}</span>
                )}
              </span>
              <span className={`tlb-col-stat tlb-val ${netCls}`}>
                {team.total_trades === 0 ? '—' : fmtNet(team.net_value)}
              </span>
              <span className={`tlb-col-stat tlb-hide-sm ${playerCls}`}>
                {team.total_trades === 0 ? '—' : fmtNet(playerNet)}
              </span>
              <span className={`tlb-col-stat tlb-hide-sm ${pickCls}`}>
                {team.total_trades === 0 ? '—' : fmtNet(pickNet)}
              </span>
              <span className={`tlb-col-stat tlb-val ${avgCls}`}>
                {team.total_trades === 0 ? '—' : fmtNet(avgPerTrade)}
              </span>
            </div>
          )
        })}
      </div>

      <div className="tlb-sub-tables">
        <AcquiredTable
          title="Players Acquired"
          teams={leaderboard}
          gotKey="players_received"
          gaveKey="players_given"
          onSelect={(rid) => setSelected(rid)}
        />
        <AcquiredTable
          title="Picks Acquired"
          teams={leaderboard}
          gotKey="picks_received"
          gaveKey="picks_given"
          onSelect={(rid) => setSelected(rid)}
        />
      </div>

      {selectedStat && (
        <TeamTradeModal team={selectedStat} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
