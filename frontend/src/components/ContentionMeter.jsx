import { contentionClass, CONTENTION_COLOR } from '../utils/contention'

export default function ContentionMeter({ score = 0.5, category = 'Treading Water' }) {
  const pct = Math.round(score * 100)
  const color = CONTENTION_COLOR[contentionClass(category)]

  return (
    <div className="contention-meter">
      <div className="contention-track">
        <div className="contention-fill" style={{ width: `${pct}%`, background: color }} />
        <div className="contention-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="contention-labels">
        <span>Rebuild</span>
        <span style={{ color }} className="contention-label-center">{category}</span>
        <span>Win-Now</span>
      </div>
    </div>
  )
}
