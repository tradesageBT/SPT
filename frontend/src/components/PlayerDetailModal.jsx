import { useEffect } from 'react'

// Shared player detail modal, used by both draft rooms.
//
// Uses the app's existing modal shell (.modal-backdrop / .modal-sheet, global.css)
// rather than a new pattern. The `au-` class prefix on the stat grid is
// historical — these styles are shared now, not auction-specific.

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c',
  K: '#8b90b0', DEF: '#666c8a',
}

export function PosPill({ pos }) {
  const c = POS_COLORS[pos] || '#8b90b0'
  return (
    <span className="rd-pos-pill" style={{ background: c + '22', color: c, borderColor: c + '55' }}>
      {pos || '?'}
    </span>
  )
}

// Short injury tag — red for anything meaning "not playing"
const INJ_SHORT = {
  Questionable: ['Q', '#e0a45c'], Doubtful: ['D', '#e05c5c'], Out: ['OUT', '#e05c5c'],
  IR: ['IR', '#e05c5c'], PUP: ['PUP', '#e05c5c'], Sus: ['SUS', '#e05c5c'],
  COV: ['COV', '#e0a45c'], NA: ['NA', '#e05c5c'],
}

export function InjuryTag({ meta }) {
  const status = meta?.injury_status
  if (!status) return null
  const [label, color] = INJ_SHORT[status] || [String(status).slice(0, 3).toUpperCase(), '#e0a45c']
  return (
    <span className="au-inj-tag" style={{ color, borderColor: color + '66', background: color + '1a' }}>
      {label}
    </span>
  )
}

// Columns per position — short headers so a season fits on one line
const STAT_COLS = {
  QB: [['PaYd', 'pass_yd'], ['PaTD', 'pass_td'], ['Int', 'pass_int'], ['RuYd', 'rush_yd'], ['RuTD', 'rush_td']],
  RB: [['Att', 'rush_att'], ['RuYd', 'rush_yd'], ['RuTD', 'rush_td'], ['Rec', 'rec'], ['ReYd', 'rec_yd']],
  WR: [['Tgt', 'rec_tgt'], ['Rec', 'rec'], ['Yds', 'rec_yd'], ['TD', 'rec_td']],
  TE: [['Tgt', 'rec_tgt'], ['Rec', 'rec'], ['Yds', 'rec_yd'], ['TD', 'rec_td']],
}

function StatBlock({ player, seasons, ppr, note }) {
  const { proj, last } = player
  if (!proj && !last) {
    return <div className="au-stat-none">No stats or projections available for this player.</div>
  }
  const baseKey = ppr === 1 ? 'pts_ppr' : ppr === 0.5 ? 'pts_half_ppr' : 'pts_std'
  // pts_league is the backend's restatement under this league's scoring
  const ptsKey = (proj?.pts_league != null || last?.pts_league != null) ? 'pts_league' : baseKey
  const cols = [['Pts', ptsKey], ['G', 'gp'], ...(STAT_COLS[player.position] || STAT_COLS.WR)]
  // Return yardage only shows for players who actually returned kicks
  const returned = (last?.kr_yd || 0) + (last?.pr_yd || 0) > 0
  if (returned) cols.push(['RetYd', '_ret'])

  const fmt = (src, key) => {
    if (key === '_ret') {
      const v = (src?.kr_yd || 0) + (src?.pr_yd || 0)
      return v ? Math.round(v) : '—'
    }
    const v = src?.[key]
    if (v == null) return '—'
    return key.startsWith('pts') ? Math.round(v) : (Number.isInteger(v) ? v : Math.round(v))
  }
  const rows = [
    [seasons?.actual ?? 'Last', last, false],
    [seasons?.projected ?? 'Proj', proj, true],
  ]
  return (
    // Scrolls rather than squishing — QB and RB carry more columns than a phone fits
    <div className="au-stat-wrap">
      <table className="au-stat-table">
        <thead>
          <tr>
            <th className="au-stat-year">Year</th>
            {cols.map(([label]) => <th key={label}>{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, src, isProj]) => (
            <tr key={label} className={isProj ? 'au-stat-projrow' : ''}>
              <td className="au-stat-year">{label}{isProj ? ' proj' : ''}</td>
              {cols.map(([, key]) => <td key={key}>{fmt(src, key)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {note && <div className="au-stat-note">{note}</div>}
    </div>
  )
}

/**
 * @param stats  [label, value] pairs for the grid at the top — callers decide
 *               what belongs there (dollars, or value/VOR/tier).
 * @param action optional { label, onClick } footer button.
 * @param note   caption under the stat table, e.g. what scoring produced it.
 */
export default function PlayerDetailModal({
  player, stats = [], seasons, ppr, note, action, onClose,
}) {
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const meta = player.meta
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-sheet" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">{player.name}</div>
            <div className="modal-subtitle">
              {player.position}{player.nfl_team ? ` · ${player.nfl_team}` : ''}
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {stats.length > 0 && (
            <div className="au-detail-grid">
              {stats.map(([label, val]) => (
                <div key={label} className="au-detail-stat">
                  <span className="au-detail-label">{label}</span>
                  <span className="au-detail-val">{val}</span>
                </div>
              ))}
            </div>
          )}

          {meta && (
            <div className="au-meta-block">
              {meta.injury_status && (
                <div className="au-meta-row">
                  <InjuryTag meta={meta} />
                  <span className="au-meta-status">
                    {meta.injury_status}
                    {meta.practice_participation ? ` · ${meta.practice_participation}` : ''}
                  </span>
                </div>
              )}
              {meta.injury_notes && <div className="au-meta-notes">{meta.injury_notes}</div>}
              {meta.depth_chart_order != null && (
                <div className="au-meta-depth">
                  Depth chart: <strong>
                    {meta.depth_chart_position || player.position}{meta.depth_chart_order}
                  </strong>
                  {meta.depth_chart_order === 1 ? ' — starter' : ''}
                </div>
              )}
            </div>
          )}

          <StatBlock player={player} seasons={seasons} ppr={ppr} note={note} />

          {action && (
            <button
              className="btn btn-primary"
              style={{ marginTop: 16, width: '100%' }}
              onClick={() => { action.onClick(player); onClose() }}
            >
              {action.label}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
