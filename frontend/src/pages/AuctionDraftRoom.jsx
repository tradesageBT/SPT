import { useState, useEffect, useMemo, useRef } from 'react'
import { api } from '../api/client'

const STORAGE_KEY = 'auction_draft_state'

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c',
  K: '#8b90b0', DEF: '#666c8a',
}
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF']

const DEFAULT_SETTINGS = {
  teams: 12, budget: 200, ppr: 1,
  qb: 1, rb: 2, wr: 2, te: 1,
  flex: 1, sflex: 0, wr_rb_flex: 0, rec_flex: 0,
  k: 1, dst: 1, bench: 7,
  teamNames: [],
  myTeam: 0,
}

const SLOT_FIELDS = [
  ['qb', 'QB'], ['rb', 'RB'], ['wr', 'WR'], ['te', 'TE'],
  ['flex', 'FLEX'], ['sflex', 'SUPERFLEX'], ['wr_rb_flex', 'WR/RB'], ['rec_flex', 'WR/TE'],
  ['k', 'K'], ['dst', 'DEF'], ['bench', 'Bench'],
]

const PPR_OPTIONS = [[0, 'Standard'], [0.5, 'Half PPR'], [1, 'Full PPR']]

function PosPill({ pos }) {
  const c = POS_COLORS[pos] || '#8b90b0'
  return (
    <span className="rd-pos-pill" style={{ background: c + '22', color: c, borderColor: c + '55' }}>
      {pos || '?'}
    </span>
  )
}

function rosterSize(s) {
  return SLOT_FIELDS.reduce((n, [key]) => n + (s[key] || 0), 0)
}

// ── Setup ─────────────────────────────────────────────────────────────────────

function SetupForm({ onStart }) {
  const [s, setS] = useState(DEFAULT_SETTINGS)
  const [names, setNames] = useState(Array.from({ length: 12 }, (_, i) => `Team ${i + 1}`))

  function setNum(key, val) {
    const n = parseInt(val)
    setS(prev => ({ ...prev, [key]: isNaN(n) ? 0 : n }))
  }

  function setTeamCount(val) {
    const n = Math.max(2, Math.min(32, parseInt(val) || 12))
    setS(prev => ({ ...prev, teams: n }))
    setNames(prev => {
      const next = [...prev]
      while (next.length < n) next.push(`Team ${next.length + 1}`)
      return next.slice(0, n)
    })
  }

  const size = rosterSize(s)

  return (
    <div className="yd-setup-card">
      <div className="yd-setup-title">Auction Draft Setup</div>
      <p className="yd-setup-sub">
        Works on any platform — you enter each player as they're bought.
      </p>

      <div className="au-setup-grid">
        <label className="au-field">
          <span>Teams</span>
          <input className="yd-select" type="number" value={s.teams} onChange={e => setTeamCount(e.target.value)} />
        </label>
        <label className="au-field">
          <span>Budget per team</span>
          <input className="yd-select" type="number" value={s.budget} onChange={e => setNum('budget', e.target.value)} />
        </label>
      </div>

      <div className="au-setup-label">Scoring</div>
      <div className="au-ppr-toggle">
        {PPR_OPTIONS.map(([val, label]) => (
          <button
            key={val}
            className={`au-ppr-btn${s.ppr === val ? ' active' : ''}`}
            onClick={() => setS(prev => ({ ...prev, ppr: val }))}
          >{label}</button>
        ))}
      </div>

      <div className="au-setup-label">Roster slots</div>
      <div className="au-setup-grid au-setup-grid-slots">
        {SLOT_FIELDS.map(([key, label]) => (
          <label key={key} className="au-field">
            <span>{label}</span>
            <input className="yd-select" type="number" value={s[key]} onChange={e => setNum(key, e.target.value)} />
          </label>
        ))}
      </div>
      <p className="yd-setup-hint">
        Roster size: <strong>{size}</strong> · {s.teams * size} total slots · ${s.teams * s.budget} in the room
        {s.sflex > 0 && <> · <strong>Superflex</strong> — QBs valued as 2QB</>}
      </p>

      <div className="au-setup-label">Team names</div>
      <div className="au-name-grid">
        {names.map((n, i) => (
          <input
            key={i}
            className="yd-select au-name-input"
            value={n}
            onChange={e => setNames(prev => prev.map((x, j) => j === i ? e.target.value : x))}
          />
        ))}
      </div>

      <label className="au-field" style={{ marginTop: 14 }}>
        <span>Which team is yours?</span>
        <select className="yd-select" value={s.myTeam} onChange={e => setNum('myTeam', e.target.value)}>
          {names.map((n, i) => <option key={i} value={i}>{n}</option>)}
        </select>
      </label>

      <button
        className="btn btn-primary"
        style={{ marginTop: 18, width: '100%' }}
        onClick={() => onStart({ ...s, teamNames: names })}
      >
        Start Auction
      </button>
    </div>
  )
}

// ── Purchase entry bar ────────────────────────────────────────────────────────

function EntryBar({ player, settings, teamState, onSubmit, onCancel }) {
  const [price, setPrice] = useState('')
  const [team, setTeam] = useState(settings.myTeam)
  const [manualPos, setManualPos] = useState('K')
  const priceRef = useRef(null)

  useEffect(() => {
    setPrice('')
    setTeam(settings.myTeam)
    setManualPos('K')
    priceRef.current?.focus()
  }, [player, settings.myTeam])

  function submit() {
    const p = parseInt(price)
    if (isNaN(p) || p < 0) return
    onSubmit({ price: p, team, position: player.isManual ? manualPos : player.position })
  }

  const t = teamState[team]
  const over = t && parseInt(price) > t.maxBid

  return (
    <div className="au-entry-bar">
      <div className="au-entry-player">
        {player.isManual
          ? (
            <select
              className="au-entry-pos-select"
              value={manualPos}
              onChange={e => setManualPos(e.target.value)}
            >
              {POSITIONS.filter(p => p !== 'ALL').map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          )
          : <PosPill pos={player.position} />
        }
        <span className="au-entry-name">{player.name}</span>
        <span className="au-entry-est">
          {player.isManual ? 'not ranked' : `est $${player.auction_value}`}
        </span>
      </div>
      <input
        ref={priceRef}
        className="au-entry-price"
        type="number"
        inputMode="numeric"
        placeholder="$"
        value={price}
        onChange={e => setPrice(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') submit()
          if (e.key === 'Escape') onCancel()
        }}
      />
      <select className="au-entry-team" value={team} onChange={e => setTeam(parseInt(e.target.value))}>
        {settings.teamNames.map((n, i) => (
          <option key={i} value={i}>{n}{i === settings.myTeam ? ' (you)' : ''}</option>
        ))}
      </select>
      <button className="btn btn-primary btn-sm" onClick={submit} disabled={price === ''}>Add</button>
      <button className="btn btn-secondary btn-sm" onClick={onCancel}>✕</button>
      {over && <span className="au-entry-warn">Over {settings.teamNames[team]}'s max bid (${t.maxBid})</span>}
    </div>
  )
}

// ── Board ─────────────────────────────────────────────────────────────────────

function AuctionBoard({ settings, onReset }) {
  const [pool, setPool] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [purchases, setPurchases] = useState(() => {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY + '_buys') || '[]') } catch { return [] }
  })
  const [selected, setSelected] = useState(null)
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY + '_buys', JSON.stringify(purchases))
  }, [purchases])

  useEffect(() => {
    setLoading(true)
    api.getAuctionPool(settings)
      .then(d => { setPool(d.players || []); setError('') })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [settings])

  const size = rosterSize(settings)

  // ── Derived team state ──────────────────────────────────────────────────────
  const teamState = useMemo(() => settings.teamNames.map((name, i) => {
    const bought = purchases.filter(p => p.team === i)
    const spent = bought.reduce((s, p) => s + p.price, 0)
    const remaining = settings.budget - spent
    const slotsLeft = size - bought.length
    // Must keep $1 in reserve for every slot after the one you're bidding on
    const maxBid = Math.max(0, remaining - Math.max(0, slotsLeft - 1))
    return { name, i, bought, spent, remaining, slotsLeft, maxBid }
  }), [purchases, settings, size])

  const me = teamState[settings.myTeam]

  // ── Inflation ───────────────────────────────────────────────────────────────
  const draftedIds = useMemo(() => new Set(purchases.map(p => p.sleeper_id)), [purchases])
  const available = useMemo(
    () => pool.filter(p => !draftedIds.has(p.sleeper_id)),
    [pool, draftedIds],
  )

  const { inflation, moneyLeft } = useMemo(() => {
    const money = teamState.reduce((s, t) => s + t.remaining, 0)
    const slots = teamState.reduce((s, t) => s + t.slotsLeft, 0)
    // Only the players who will actually be rostered matter for inflation
    const relevant = available.slice(0, Math.max(slots, 1))
    const value = relevant.reduce((s, p) => s + p.auction_value, 0)
    return { inflation: value > 0 ? money / value : 1, moneyLeft: money }
  }, [teamState, available])

  const filtered = useMemo(() => available.filter(p => {
    if (pos !== 'ALL' && p.position !== pos) return false
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  }), [available, pos, search])

  // ── My positional needs ─────────────────────────────────────────────────────
  const myCounts = useMemo(() => {
    const c = {}
    for (const b of (me?.bought || [])) c[b.position] = (c[b.position] || 0) + 1
    return c
  }, [me])

  function addPurchase({ price, team, position }) {
    setPurchases(prev => [...prev, {
      sleeper_id: selected.sleeper_id,
      name: selected.name,
      position: position || selected.position,
      nfl_team: selected.nfl_team || '',
      // Manual entries aren't ranked, so they're never scored over/under value
      auction_value: selected.auction_value || 0,
      price, team,
    }])
    setSelected(null)
    setSearch('')
  }

  function addManual() {
    const name = search.trim()
    if (!name) return
    setSelected({
      sleeper_id: `manual_${Date.now()}`,
      name,
      position: '',
      nfl_team: '',
      auction_value: 0,
      isManual: true,
    })
  }

  function undo() {
    setPurchases(prev => prev.slice(0, -1))
  }

  function clearAll() {
    if (!window.confirm('Clear every purchase and start this auction over?')) return
    setPurchases([])
  }

  if (loading) return <div className="rd-loading">Loading player values…</div>
  if (error) return <div className="rd-error">{error}</div>

  const adj = (v) => Math.max(1, Math.round(v * inflation))

  return (
    <div className="rd-board">
      {/* Top stats */}
      <div className="au-stats">
        <div className="au-stat au-stat-hero">
          <span className="au-stat-label">Your budget</span>
          <span className="au-stat-val">${me?.remaining ?? 0}</span>
        </div>
        <div className="au-stat au-stat-hero">
          <span className="au-stat-label">Max bid</span>
          <span className="au-stat-val au-stat-accent">${me?.maxBid ?? 0}</span>
        </div>
        <div className="au-stat">
          <span className="au-stat-label">Slots left</span>
          <span className="au-stat-val">{me?.slotsLeft ?? 0}</span>
        </div>
        <div className="au-stat">
          <span className="au-stat-label">Inflation</span>
          <span className="au-stat-val" style={{ color: inflation > 1.05 ? '#e05c5c' : inflation < 0.95 ? '#01d9ac' : 'var(--text)' }}>
            {(inflation * 100).toFixed(0)}%
          </span>
        </div>
        <div className="au-stat">
          <span className="au-stat-label">$ in room</span>
          <span className="au-stat-val">${moneyLeft}</span>
        </div>
        <div className="au-stat-actions">
          {purchases.length > 0 && <button className="btn btn-secondary btn-sm" onClick={undo}>Undo</button>}
          <button className="btn btn-secondary btn-sm" onClick={onReset}>Settings</button>
        </div>
      </div>

      {inflation !== 1 && (
        <div className="au-inflation-note">
          {inflation > 1.05
            ? `Money is loose — remaining players are going for about ${((inflation - 1) * 100).toFixed(0)}% over base value. Expect to pay up.`
            : inflation < 0.95
              ? `Money is tight — remaining players should go about ${((1 - inflation) * 100).toFixed(0)}% under base value. Bargains ahead.`
              : 'Prices are tracking close to base value.'}
        </div>
      )}

      {selected && (
        <EntryBar
          player={selected}
          settings={settings}
          teamState={teamState}
          onSubmit={addPurchase}
          onCancel={() => setSelected(null)}
        />
      )}

      <div className="rd-board-body">
        {/* Available players */}
        <div className="rd-player-list-wrap">
          <div className="rd-pos-tabs" style={{ marginBottom: 8 }}>
            {POSITIONS.map(p => (
              <button
                key={p}
                className={`rd-pos-tab${pos === p ? ' active' : ''}`}
                style={pos === p && p !== 'ALL' ? { background: (POS_COLORS[p] || '#8b90b0') + '22', color: POS_COLORS[p] || '#8b90b0', borderColor: (POS_COLORS[p] || '#8b90b0') + '88' } : {}}
                onClick={() => setPos(p)}
              >{p}</button>
            ))}
          </div>
          <input
            className="rd-search"
            placeholder="Search player…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && filtered.length === 0) addManual() }}
            style={{ marginBottom: 8 }}
          />
          <div className="rd-player-header au-player-header">
            <span>Player</span>
            <span className="rd-col-center">Est</span>
            <span className="rd-col-center">Adj</span>
            <span className="rd-col-center">VOR</span>
          </div>
          <div className="rd-player-list">
            {filtered.length === 0 && (
              search.trim()
                ? (
                  <button className="au-add-manual" onClick={addManual}>
                    <span className="au-add-manual-plus">+</span>
                    Add “{search.trim()}” — kickers, defenses and unranked players
                  </button>
                )
                : <div className="rd-empty">No players match</div>
            )}
            {filtered.slice(0, 200).map(p => (
              <button
                key={p.sleeper_id}
                className={`au-player-row${selected?.sleeper_id === p.sleeper_id ? ' active' : ''}`}
                onClick={() => setSelected(p)}
              >
                <div className="rd-player-info">
                  <PosPill pos={p.position} />
                  <span className="rd-player-name">{p.name}</span>
                  <span className="rd-player-team">{p.nfl_team}{p.pos_rank ? ` · ${p.position}${p.pos_rank}` : ''}</span>
                </div>
                <span className="rd-col-center au-val">${p.auction_value}</span>
                <span className="rd-col-center au-val-adj">${adj(p.auction_value)}</span>
                <span className="rd-col-center rd-col-muted">{p.vor > 0 ? `+${p.vor}` : p.vor}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Sidebar */}
        <div className="rd-sidebar">
          <div className="yd-sidebar-section">
            <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>
              Your Roster — {me?.bought.length ?? 0}/{size}
            </div>
            <div className="au-needs">
              {['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].map(p => (
                <span key={p} className="au-need-chip">
                  <PosPill pos={p} />{myCounts[p] || 0}
                </span>
              ))}
            </div>
            {(me?.bought.length ?? 0) === 0
              ? <div className="rd-empty" style={{ fontSize: '0.75rem' }}>No players yet</div>
              : me.bought.map((b, i) => (
                <div key={i} className="yd-my-pick">
                  <PosPill pos={b.position} />
                  <span className="yd-my-pick-name">{b.name}</span>
                  <span className={`au-price${b.price > b.auction_value ? ' au-over' : b.price < b.auction_value ? ' au-under' : ''}`}>
                    ${b.price}
                  </span>
                </div>
              ))
            }
          </div>

          <div className="yd-sidebar-section">
            <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>Budgets</div>
            {teamState.map(t => (
              <div key={t.i} className={`au-team-row${t.i === settings.myTeam ? ' au-team-me' : ''}`}>
                <span className="au-team-name">{t.name}</span>
                <span className="au-team-slots">{t.slotsLeft} left</span>
                <span className="au-team-budget">${t.remaining}</span>
                <span className="au-team-max">max ${t.maxBid}</span>
              </div>
            ))}
          </div>

          <div className="yd-sidebar-section">
            <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>
              Recent Buys
              {purchases.length > 0 && (
                <button className="au-clear" onClick={clearAll}>clear all</button>
              )}
            </div>
            {purchases.length === 0
              ? <div className="rd-empty" style={{ fontSize: '0.75rem' }}>Nothing bought yet</div>
              : [...purchases].reverse().slice(0, 25).map((b, i) => (
                <div key={i} className="yd-recent-pick">
                  <PosPill pos={b.position} />
                  <span className="yd-recent-pick-name">{b.name}</span>
                  <span className="yd-recent-pick-team">{settings.teamNames[b.team]}</span>
                  <span className={`au-price${b.price > b.auction_value ? ' au-over' : b.price < b.auction_value ? ' au-under' : ''}`}>
                    ${b.price}
                  </span>
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function AuctionDraftRoom() {
  const [settings, setSettings] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
      // Merge over defaults so settings saved before the ppr/flex fields existed
      // don't send undefined to the API
      return saved ? { ...DEFAULT_SETTINGS, ...saved } : null
    } catch { return null }
  })

  function handleStart(s) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    setSettings(s)
  }

  function handleReset() {
    setSettings(null)
  }

  return (
    <div className="yd-page">
      <div className="rd-topbar">
        <div className="rd-topbar-title">Auction Draft Assistant</div>
      </div>
      {settings
        ? <AuctionBoard settings={settings} onReset={handleReset} />
        : <SetupForm onStart={handleStart} />
      }
    </div>
  )
}
