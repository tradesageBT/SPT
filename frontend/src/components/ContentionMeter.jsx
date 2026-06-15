export default function ContentionMeter({ score = 0.5 }) {
  const pct = Math.round(score * 100)
  let label, color
  if (score < 0.35) { label = 'Rebuilding'; color = '#5cb8e0' }
  else if (score > 0.65) { label = 'Win-Now'; color = '#e05c5c' }
  else { label = 'Contending'; color = '#01d9ac' }

  return (
    <div className="contention-meter">
      <div className="contention-track">
        <div className="contention-fill" style={{ width: `${pct}%`, background: color }} />
        <div className="contention-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="contention-labels">
        <span>Rebuild</span>
        <span style={{ color }} className="contention-label-center">{label}</span>
        <span>Win-Now</span>
      </div>
    </div>
  )
}
