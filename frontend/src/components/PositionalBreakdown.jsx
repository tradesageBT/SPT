const POSITIONS = ['QB', 'RB', 'WR', 'TE']
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }

function rankColor(rank, n) {
  if (!n) return 'var(--text-muted)'
  const third = Math.ceil(n / 3)
  if (rank <= third) return '#4ade80'
  if (rank > n - third) return 'var(--danger)'
  return 'var(--text-muted)'
}

export default function PositionalBreakdown({ breakdown, rank = {} }) {
  const n = rank.n || 0
  const maxVal = Math.max(...POSITIONS.map((p) => breakdown[p] || 0), 1)

  return (
    <div className="positional-section">
      <h2 className="section-title">Positional Strength</h2>
      <div className="positional-grid">
        {POSITIONS.map((pos) => {
          const val = breakdown[pos] || 0
          const r = rank[pos]
          const barW = Math.round((val / maxVal) * 100)
          return (
            <div key={pos} className="pos-card">
              <div className="pos-card-header">
                <span className="pos-badge" style={{ background: POS_COLOR[pos] }}>{pos}</span>
                <span className="pos-value">{val.toLocaleString()}</span>
              </div>
              <div className="pos-internal-bar">
                <div
                  className="pos-internal-fill"
                  style={{ width: `${barW}%`, background: POS_COLOR[pos] }}
                />
              </div>
              {r != null && n > 0 && (
                <div className="pos-rank" style={{ color: rankColor(r, n) }}>
                  #{r} <span className="pos-rank-of">of {n}</span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
