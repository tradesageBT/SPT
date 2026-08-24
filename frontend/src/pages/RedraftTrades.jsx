import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', K: '#8b90b0', DEF: '#666c8a',
}

function PosPill({ pos }) {
  const c = POS_COLORS[pos] || '#8b90b0'
  return (
    <span className="rd-pos-pill" style={{ background: c + '22', color: c, borderColor: c + '55' }}>
      {pos || '?'}
    </span>
  )
}

function gradeColor(grade) {
  if (grade === 'A+' || grade === 'A') return '#01d9ac'
  if (grade === 'B+' || grade === 'B') return '#5cb8e0'
  if (grade === 'C+' || grade === 'C') return '#e0a45c'
  return '#e05c5c'
}

function tradeFairness(aVal, bVal) {
  const total = aVal + bVal
  if (!total) return { grade: 'N/A', label: 'Add players', color: '#8b90b0', pct: 50 }
  const aPct = (aVal / total) * 100
  const diff = Math.abs(aPct - 50)
  let grade, label
  if (diff < 3)       { grade = 'A+'; label = 'Dead even' }
  else if (diff < 8)  { grade = 'A';  label = 'Very fair' }
  else if (diff < 15) { grade = 'B';  label = 'Slightly uneven' }
  else if (diff < 25) { grade = 'C';  label = 'Lopsided' }
  else                { grade = 'D';  label = 'Very lopsided' }
  const winner = aVal > bVal ? 'You win' : aVal < bVal ? 'They win' : 'Even'
  return { grade, label: `${label} — ${winner}`, color: gradeColor(grade), pct: aPct }
}

function playerValue(p, mode) {
  return mode === 'dynasty' ? (p.fc_value || 0) : (p.redraft_value || 0)
}

function PlayerSearch({ onAdd, exclude = [], mode }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const debounce = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    clearTimeout(debounce.current)
    if (!q.trim()) { setResults([]); setOpen(false); return }
    debounce.current = setTimeout(async () => {
      setLoading(true)
      try {
        const data = await api.searchPlayers(q, 12, mode)
        setResults(data.filter(p => !exclude.includes(p.sleeper_id)))
        setOpen(true)
      } catch { setResults([]) }
      finally { setLoading(false) }
    }, 250)
  }, [q, mode])

  function pick(p) {
    onAdd(p)
    setQ('')
    setResults([])
    setOpen(false)
    inputRef.current?.focus()
  }

  return (
    <div className="rt-search-wrap">
      <input
        ref={inputRef}
        className="rd-search"
        placeholder="Search player…"
        value={q}
        onChange={e => setQ(e.target.value)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onFocus={() => results.length && setOpen(true)}
      />
      {loading && <div className="rt-search-loading">…</div>}
      {open && results.length > 0 && (
        <div className="rt-dropdown">
          {results.map(p => (
            <div key={p.sleeper_id} className="rt-dropdown-row" onMouseDown={() => pick(p)}>
              <PosPill pos={p.position} />
              <span className="rt-drop-name">{p.name}</span>
              <span className="rt-drop-team">{p.nfl_team}</span>
              <span className="rt-drop-val">{playerValue(p, mode)?.toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TradeSlot({ label, players, onRemove, totalValue }) {
  return (
    <div className="rt-slot">
      <div className="rt-slot-header">
        <span className="rt-slot-label">{label}</span>
        <span className="rt-slot-total">{totalValue.toLocaleString()} pts</span>
      </div>
      {players.length === 0 && <div className="rd-empty-sm">Add players below</div>}
      {players.map(p => (
        <div key={p.sleeper_id} className="rt-player-row">
          <PosPill pos={p.position} />
          <div className="rt-player-info">
            <span className="rt-player-name">{p.name}</span>
            <span className="rt-player-meta">{p.nfl_team} · {p.position}{p.pos_rank ?? ''}</span>
          </div>
          <span className="rt-player-val">{p._val?.toLocaleString()}</span>
          <button className="rt-remove" onClick={() => onRemove(p.sleeper_id)}>✕</button>
        </div>
      ))}
    </div>
  )
}

function TopPlayers({ mode }) {
  const [players, setPlayers] = useState([])
  const [pos, setPos] = useState('ALL')

  useEffect(() => {
    setPlayers([])
    api.searchPlayers('', 100, mode).then(setPlayers).catch(() => {})
  }, [mode])

  const filtered = pos === 'ALL' ? players : players.filter(p => p.position === pos)
  return (
    <div className="rt-top-players">
      <div className="rt-top-header">
        <span className="rd-sidebar-title">Top {mode === 'dynasty' ? 'Dynasty' : 'Redraft'} Values</span>
        <div className="rd-pos-tabs" style={{ flexWrap: 'wrap' }}>
          {['ALL', 'QB', 'RB', 'WR', 'TE'].map(p => (
            <button
              key={p}
              className={`rd-pos-tab${pos === p ? ' active' : ''}`}
              style={pos === p && p !== 'ALL' ? { background: (POS_COLORS[p] || '#8b90b0') + '22', color: POS_COLORS[p] || '#8b90b0', borderColor: (POS_COLORS[p] || '#8b90b0') + '88' } : {}}
              onClick={() => setPos(p)}
            >{p}</button>
          ))}
        </div>
      </div>
      <div className="rt-top-list">
        {filtered.slice(0, 30).map((p, i) => (
          <div key={p.sleeper_id} className="rt-top-row">
            <span className="rt-top-rank">{i + 1}</span>
            <PosPill pos={p.position} />
            <span className="rt-top-name">{p.name}</span>
            <span className="rt-top-team">{p.nfl_team}</span>
            <span className="rt-top-val">{playerValue(p, mode)?.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ModeToggle({ mode, setMode }) {
  return (
    <div className="rt-mode-toggle">
      <button
        className={`rt-mode-btn${mode === 'redraft' ? ' active' : ''}`}
        onClick={() => setMode('redraft')}
      >
        Redraft
      </button>
      <button
        className={`rt-mode-btn${mode === 'dynasty' ? ' active' : ''}`}
        onClick={() => setMode('dynasty')}
      >
        Dynasty
      </button>
    </div>
  )
}

export default function TradeEvaluator() {
  const [mode, setMode] = useState('redraft')
  const [sideA, setSideA] = useState([])
  const [sideB, setSideB] = useState([])

  // Attach current value when mode changes so totals stay in sync
  const enriched = (list) => list.map(p => ({ ...p, _val: playerValue(p, mode) }))
  const enrichedA = enriched(sideA)
  const enrichedB = enriched(sideB)

  const totalA = enrichedA.reduce((s, p) => s + p._val, 0)
  const totalB = enrichedB.reduce((s, p) => s + p._val, 0)
  const fairness = tradeFairness(totalA, totalB)

  const excludeA = sideA.map(p => p.sleeper_id)
  const excludeB = sideB.map(p => p.sleeper_id)
  const allExclude = [...excludeA, ...excludeB]

  function addA(p) { setSideA(prev => prev.find(x => x.sleeper_id === p.sleeper_id) ? prev : [...prev, p]) }
  function addB(p) { setSideB(prev => prev.find(x => x.sleeper_id === p.sleeper_id) ? prev : [...prev, p]) }
  function removeA(id) { setSideA(prev => prev.filter(p => p.sleeper_id !== id)) }
  function removeB(id) { setSideB(prev => prev.filter(p => p.sleeper_id !== id)) }
  function reset() { setSideA([]); setSideB([]) }

  const diff = totalB - totalA
  const diffLabel = diff === 0 ? 'Even' : diff > 0 ? `+${diff.toLocaleString()} for you` : `${diff.toLocaleString()} for you`

  return (
    <div className="rt-page">
      <div className="rt-topbar">
        <div className="rt-topbar-title">Trade Evaluator</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <ModeToggle mode={mode} setMode={setMode} />
          <button className="btn btn-secondary btn-sm" onClick={reset}>Reset</button>
        </div>
      </div>

      <div className="rt-body">
        {/* Trade builder */}
        <div className="rt-builder">
          <div className="rt-sides">
            <div className="rt-side">
              <TradeSlot label="You Give" players={enrichedA} onRemove={removeA} totalValue={totalA} />
              <PlayerSearch onAdd={addA} exclude={allExclude} mode={mode} />
            </div>

            <div className="rt-divider">
              <div className="rt-grade" style={{ color: fairness.color, borderColor: fairness.color + '44' }}>
                {fairness.grade}
              </div>
              <div className="rt-grade-label" style={{ color: fairness.color }}>{fairness.label}</div>
              {(totalA > 0 || totalB > 0) && (
                <div className="rt-diff" style={{ color: diff > 0 ? '#01d9ac' : diff < 0 ? '#e05c5c' : '#8b90b0' }}>
                  {diffLabel}
                </div>
              )}
            </div>

            <div className="rt-side">
              <TradeSlot label="You Get" players={enrichedB} onRemove={removeB} totalValue={totalB} />
              <PlayerSearch onAdd={addB} exclude={allExclude} mode={mode} />
            </div>
          </div>

          {/* Value bar */}
          {(totalA > 0 || totalB > 0) && (
            <div className="rt-bar-wrap">
              <span className="rt-bar-label">You Give</span>
              <div className="rt-value-bar">
                <div className="rt-value-bar-a" style={{ width: `${fairness.pct}%` }} />
              </div>
              <span className="rt-bar-label">You Get</span>
            </div>
          )}
        </div>

        {/* Top players reference */}
        <TopPlayers mode={mode} />
      </div>
    </div>
  )
}
