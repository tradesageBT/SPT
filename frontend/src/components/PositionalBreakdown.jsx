const POSITIONS = ['QB', 'RB', 'WR', 'TE']
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }

function SurplusBar({ pct }) {
  const clamped = Math.max(-100, Math.min(100, pct))
  const isPos = clamped >= 0
  return (
    <div className="pos-bar-wrap">
      <div className="pos-bar-track">
        <div className="pos-bar-center" />
        {isPos ? (
          <div
            className="pos-bar-fill pos-bar-pos"
            style={{ left: '50%', width: `${clamped / 2}%` }}
          />
        ) : (
          <div
            className="pos-bar-fill pos-bar-neg"
            style={{ right: '50%', width: `${Math.abs(clamped) / 2}%` }}
          />
        )}
      </div>
      <span className={`pos-bar-label ${isPos ? 'label-pos' : 'label-neg'}`}>
        {isPos ? '+' : ''}{pct}%
      </span>
    </div>
  )
}

export default function PositionalBreakdown({ breakdown, surplus }) {
  const maxVal = Math.max(...POSITIONS.map((p) => breakdown[p] || 0), 1)

  return (
    <div className="positional-section">
      <h2 className="section-title">Positional Breakdown vs League Avg</h2>
      <div className="positional-grid">
        {POSITIONS.map((pos) => {
          const val = breakdown[pos] || 0
          const sp = surplus[pos] ?? 0
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
              <SurplusBar pct={sp} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
