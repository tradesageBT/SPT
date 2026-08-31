import { useState, useEffect, useMemo, useRef } from 'react'
import { api } from '../api/client'

const STORAGE_KEY = 'auction_draft_state'
const POLL_MS = 3000

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c',
  K: '#8b90b0', DEF: '#666c8a',
}
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF']

const DEFAULT_TEAM_NAMES = [
  'Willie Cam', '2 Knuckles deepER', 'CollinStoner69ers', 'Dabolls Hurts',
  'DannyFootball', 'Dayman', 'ElectricDreamMachine', 'Football Pharm',
  'Southcards', 'SteelCurtain', 'The Pack is Back!', 'Thicc Boiz',
]
const DEFAULT_SETTINGS = {
  teams: 12, budget: 200, ppr: 1,
  qb: 1, rb: 2, wr: 3, te: 1,
  // Q/W/R/T is a superflex slot — this is what prices QBs as a 2QB league.
  // IR slots are excluded: they aren't filled during the auction.
  flex: 0, sflex: 1, wr_rb_flex: 0, rec_flex: 0,
  k: 1, dst: 1, bench: 7,
  teamNames: DEFAULT_TEAM_NAMES,
  // No default — everyone in the league uses this, so picking a team is explicit.
  myTeam: null,
}

const SLOT_FIELDS = [
  ['qb', 'QB'], ['rb', 'RB'], ['wr', 'WR'], ['te', 'TE'],
  ['flex', 'FLEX'], ['sflex', 'SUPERFLEX'], ['wr_rb_flex', 'WR/RB'], ['rec_flex', 'WR/TE'],
  ['k', 'K'], ['dst', 'DEF'], ['bench', 'Bench'],
]

const PPR_OPTIONS = [[0, 'Standard'], [0.5, 'Half PPR'], [1, 'Full PPR']]

// Which positions can fill each flex slot type
const FLEX_ELIGIBLE = {
  flex: ['RB', 'WR', 'TE'],
  sflex: ['QB', 'RB', 'WR', 'TE'],
  wr_rb_flex: ['RB', 'WR'],
  rec_flex: ['WR', 'TE'],
}
const FLEX_TYPES = Object.keys(FLEX_ELIGIBLE)
// Position -> the settings key holding its required starter count
const STARTER_KEYS = { QB: 'qb', RB: 'rb', WR: 'wr', TE: 'te', K: 'k', DEF: 'dst' }

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
  const [names, setNames] = useState(DEFAULT_TEAM_NAMES)
  const [mode, setMode] = useState('solo')   // solo | create | join
  const [joinCode, setJoinCode] = useState('')
  const [joined, setJoined] = useState(null) // room payload once a code loads
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function setNum(key, val) {
    const n = parseInt(val)
    setS(prev => ({ ...prev, [key]: isNaN(n) ? 0 : n }))
  }

  // Pull a room's settings so every manager prices off identical numbers
  async function loadRoom() {
    const code = joinCode.trim().toUpperCase()
    if (!code) return
    setBusy(true); setError(''); setJoined(null)
    try {
      const room = await api.getAuctionRoom(code)
      const rs = room.settings || {}
      setS(prev => ({ ...prev, ...rs, myTeam: null }))
      if (Array.isArray(rs.teamNames) && rs.teamNames.length) setNames(rs.teamNames)
      setJoined(room)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function start() {
    if (s.myTeam == null) return
    const settings = { ...s, teamNames: names }
    if (mode === 'create') {
      setBusy(true); setError('')
      try {
        // myTeam is per-person, so it never goes into the shared room
        const { myTeam, ...shared } = settings
        const room = await api.createAuctionRoom(shared)
        onStart({ ...settings, roomCode: room.code })
      } catch (e) {
        setError(`Could not create room: ${e.message}`)
        setBusy(false)
      }
      return
    }
    onStart({ ...settings, roomCode: mode === 'join' ? joined?.code ?? null : null })
  }

  const locked = mode === 'join' && !!joined   // joiners inherit the room's settings

  function setTeamCount(val) {
    const n = Math.max(2, Math.min(32, parseInt(val) || 12))
    // Keep myTeam in range if the league shrinks below its index
    setS(prev => ({
      ...prev,
      teams: n,
      myTeam: prev.myTeam == null ? null : Math.min(prev.myTeam, n - 1),
    }))
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

      <div className="au-mode-toggle">
        {[['solo', 'Just me'], ['create', 'Create room'], ['join', 'Join room']].map(([m, label]) => (
          <button
            key={m}
            className={`au-mode-btn${mode === m ? ' active' : ''}`}
            onClick={() => { setMode(m); setError(''); setJoined(null) }}
          >{label}</button>
        ))}
      </div>
      <p className="yd-setup-hint" style={{ marginTop: 0 }}>
        {mode === 'solo'
          ? 'Tracked in this browser only. Nobody else sees your entries.'
          : mode === 'create'
            ? "You'll get a code to share. Anyone who joins sees every pick as it's entered."
            : 'Enter the code from whoever created the room.'}
      </p>

      {error && <div className="rd-error" style={{ marginBottom: 10 }}>{error}</div>}

      {mode === 'join' && (
        <>
          <label className="au-field">
            <span>Room code</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="yd-select au-code-input"
                placeholder="e.g. K7M2Q"
                value={joinCode}
                onChange={e => setJoinCode(e.target.value.toUpperCase())}
                onKeyDown={e => e.key === 'Enter' && loadRoom()}
                style={{ flex: 1 }}
              />
              <button className="btn btn-secondary" onClick={loadRoom} disabled={busy || !joinCode.trim()}>
                {busy ? '…' : 'Load'}
              </button>
            </div>
          </label>
          {joined && (
            <p className="au-joined-note">
              Joined <strong>{joined.code}</strong> — {joined.picks?.length ?? 0} picks so far.
              Settings below come from the room and are locked so everyone prices the same.
            </p>
          )}
        </>
      )}

      {(mode !== 'join' || joined) && (
      <>
      <div className="au-setup-grid">
        <label className="au-field">
          <span>Teams</span>
          <input className="yd-select" type="number" value={s.teams} disabled={locked} onChange={e => setTeamCount(e.target.value)} />
        </label>
        <label className="au-field">
          <span>Budget per team</span>
          <input className="yd-select" type="number" value={s.budget} disabled={locked} onChange={e => setNum('budget', e.target.value)} />
        </label>
      </div>

      <div className="au-setup-label">Scoring</div>
      <div className="au-ppr-toggle">
        {PPR_OPTIONS.map(([val, label]) => (
          <button
            key={val}
            className={`au-ppr-btn${s.ppr === val ? ' active' : ''}`}
            disabled={locked}
            onClick={() => setS(prev => ({ ...prev, ppr: val }))}
          >{label}</button>
        ))}
      </div>

      <div className="au-setup-label">Roster slots</div>
      <div className="au-setup-grid au-setup-grid-slots">
        {SLOT_FIELDS.map(([key, label]) => (
          <label key={key} className="au-field">
            <span>{label}</span>
            <input className="yd-select" type="number" value={s[key]} disabled={locked} onChange={e => setNum(key, e.target.value)} />
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
            disabled={locked}
            onChange={e => setNames(prev => prev.map((x, j) => j === i ? e.target.value : x))}
          />
        ))}
      </div>

      <label className="au-field" style={{ marginTop: 14 }}>
        <span>Which team is yours?</span>
        <select
          className="yd-select"
          value={s.myTeam ?? ''}
          onChange={e => setS(prev => ({
            ...prev,
            myTeam: e.target.value === '' ? null : parseInt(e.target.value),
          }))}
        >
          <option value="">— Select your team —</option>
          {names.slice(0, s.teams).map((n, i) => <option key={i} value={i}>{n}</option>)}
        </select>
      </label>

      <button
        className="btn btn-primary"
        style={{ marginTop: 18, width: '100%' }}
        disabled={s.myTeam == null || busy}
        onClick={start}
      >
        {busy ? 'Creating room…'
          : mode === 'create' ? 'Create Room & Start'
          : mode === 'join' ? 'Join & Start'
          : 'Start Auction'}
      </button>
      </>
      )}
    </div>
  )
}

/**
 * What a team still needs at `pos`:
 *   starterNeed — unfilled required starters at that position
 *   flexOpen    — open flex slots this position is eligible to fill
 * Flex slots are treated as consumed by players held beyond their starter
 * requirement, so a team with 4 WR in a 3-WR league has already used one.
 */
function positionNeed(byPos, settings, pos) {
  const owned = byPos[pos]?.count || 0
  const required = settings[STARTER_KEYS[pos]] || 0
  const starterNeed = Math.max(0, required - owned)

  const flexForPos = FLEX_TYPES
    .filter(ft => FLEX_ELIGIBLE[ft].includes(pos))
    .reduce((n, ft) => n + (settings[ft] || 0), 0)
  if (!flexForPos) return { starterNeed, flexOpen: 0 }

  const totalFlex = FLEX_TYPES.reduce((n, ft) => n + (settings[ft] || 0), 0)
  const surplus = Object.entries(STARTER_KEYS).reduce(
    (n, [p, key]) => n + Math.max(0, (byPos[p]?.count || 0) - (settings[key] || 0)),
    0,
  )
  return { starterNeed, flexOpen: Math.max(0, Math.min(flexForPos, totalFlex - surplus)) }
}

// ── Player detail ─────────────────────────────────────────────────────────────
//
// Uses the app's existing modal shell (.modal-backdrop / .modal-sheet / …,
// global.css:424) rather than a new pattern. A right-hand pane was considered
// and rejected: .main-content caps at 1100px and .rd-board-body collapses to a
// single column at 860px, so a third column would be unusable on a phone.

function PlayerDetail({ player, adjPrice, onNominate, onClose }) {
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const stats = [
    ['Est $', `$${player.auction_value}`],
    ['Adjusted $', `$${adjPrice}`],
    ['Pos rank', player.pos_rank ? `${player.position}${player.pos_rank}` : '—'],
    ['Tier', player.tier ? `T${player.tier}` : '—'],
    ['VOR', player.vor > 0 ? `+${player.vor}` : `${player.vor ?? '—'}`],
    ['Age', player.age ? Math.round(player.age) : '—'],
  ]

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
          <div className="au-detail-grid">
            {stats.map(([label, val]) => (
              <div key={label} className="au-detail-stat">
                <span className="au-detail-label">{label}</span>
                <span className="au-detail-val">{val}</span>
              </div>
            ))}
          </div>
          <button
            className="btn btn-primary"
            style={{ marginTop: 16, width: '100%' }}
            onClick={() => { onNominate(player); onClose() }}
          >
            Nominate {player.name}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Competition panel ─────────────────────────────────────────────────────────

function CompetitionPanel({ position, teamState, settings }) {
  const myMax = teamState[settings.myTeam]?.maxBid ?? 0

  const rows = teamState
    .map(t => {
      const { starterNeed, flexOpen } = positionNeed(t.byPos, settings, position)
      return {
        ...t,
        starterNeed,
        flexOpen,
        posSpent: t.byPos[position]?.spent || 0,
        posCount: t.byPos[position]?.count || 0,
        wants: starterNeed > 0 || flexOpen > 0,
      }
    })
    // Teams that need the spot first, then by who can bid the most
    .sort((a, b) => (b.wants - a.wants) || (b.maxBid - a.maxBid))

  const threats = rows.filter(r => r.wants && r.i !== settings.myTeam && r.maxBid >= myMax).length

  return (
    <div className="au-comp">
      <div className="au-comp-head">
        <span className="au-comp-title">Competition for <PosPill pos={position} /></span>
        <span className="au-comp-threats">
          {threats === 0
            ? 'No one who needs it can outbid you'
            : `${threats} team${threats > 1 ? 's' : ''} need it and can match your $${myMax}`}
        </span>
      </div>
      <div className="au-comp-header-row">
        <span>Team</span>
        <span className="rd-col-center">Needs</span>
        <span className="rd-col-center">Has</span>
        <span className="rd-col-center">Spent</span>
        <span className="rd-col-center">Budget</span>
        <span className="rd-col-center">Max</span>
      </div>
      <div className="au-comp-rows">
        {rows.map(r => {
          const canOutbid = r.wants && r.i !== settings.myTeam && r.maxBid >= myMax
          return (
            <div
              key={r.i}
              className={
                'au-comp-row'
                + (r.i === settings.myTeam ? ' au-comp-me' : '')
                + (!r.wants ? ' au-comp-filled' : '')
                + (canOutbid ? ' au-comp-threat' : '')
              }
            >
              <span className="au-comp-name">
                {r.name}{r.i === settings.myTeam ? ' (you)' : ''}
              </span>
              <span className="rd-col-center au-comp-need">
                {r.starterNeed > 0
                  ? `${r.starterNeed}`
                  : r.flexOpen > 0 ? 'flex' : '—'}
              </span>
              <span className="rd-col-center au-comp-dim">{r.posCount}</span>
              <span className="rd-col-center au-comp-dim">${r.posSpent}</span>
              <span className="rd-col-center">${r.remaining}</span>
              <span className="rd-col-center au-comp-max">${r.maxBid}</span>
            </div>
          )
        })}
      </div>
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
  // Who is up for bid — shared across the room. Distinct from `detail`, which is
  // just "I tapped a row to look at someone" and never leaves this browser.
  const [nominated, setNominated] = useState(null)
  const [detail, setDetail] = useState(null)
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')
  const [syncedAt, setSyncedAt] = useState(null)
  const [syncErr, setSyncErr] = useState('')

  const room = settings.roomCode || null

  // Always mirror locally, shared or not: if the network drops mid-draft the
  // board keeps working from this copy.
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY + '_buys', JSON.stringify(purchases))
  }, [purchases])

  // In a shared room the server is the source of truth for picks
  useEffect(() => {
    if (!room) return
    let cancelled = false
    const tick = async () => {
      try {
        const d = await api.getAuctionRoom(room)
        if (cancelled) return
        setPurchases(d.picks || [])
        setNominated(d.nominated || null)
        setSyncedAt(new Date())
        setSyncErr('')
      } catch (e) {
        if (!cancelled) setSyncErr(e.message)
      }
    }
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => { cancelled = true; clearInterval(t) }
  }, [room])

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
    const byPos = {}
    for (const b of bought) {
      const e = byPos[b.position] || { count: 0, spent: 0 }
      e.count += 1
      e.spent += b.price
      byPos[b.position] = e
    }
    return { name, i, bought, spent, remaining, slotsLeft, maxBid, byPos }
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

  // Nomination is shared, so it round-trips through the room. Set optimistically
  // first: the board must not wait on the network to show who's up.
  async function nominate(player) {
    setNominated(player)
    if (!room) return
    try {
      await api.setAuctionNomination(room, player)
      setSyncErr('')
    } catch (e) {
      setSyncErr(`Nomination not shared (${e.message}) — visible only to you`)
    }
  }

  async function addPurchase({ price, team, position }) {
    const pick = {
      sleeper_id: nominated.sleeper_id,
      name: nominated.name,
      position: position || nominated.position,
      nfl_team: nominated.nfl_team || '',
      // Manual entries aren't ranked, so they're never scored over/under value
      auction_value: nominated.auction_value || 0,
      price, team,
    }
    // They're bought — clear the block for everyone
    nominate(null)
    setSearch('')

    if (!room) {
      setPurchases(prev => [...prev, { ...pick, id: `local_${Date.now()}` }])
      return
    }
    try {
      // The server returns the full list, so there's nothing to merge
      const d = await api.addAuctionPick(room, pick)
      setPurchases(d.picks || [])
      setSyncedAt(new Date())
      setSyncErr('')
    } catch (e) {
      // Keep the entry rather than lose it; the next successful poll reconciles
      setPurchases(prev => [...prev, { ...pick, id: `local_${Date.now()}` }])
      setSyncErr(`Not saved to room (${e.message}) — kept locally`)
    }
  }

  // Kickers, defenses and unranked players aren't in the pool, so there's no row
  // to nominate from — go straight up for bid.
  function addManual() {
    const name = search.trim()
    if (!name) return
    nominate({
      sleeper_id: `manual_${Date.now()}`,
      name,
      position: '',
      nfl_team: '',
      auction_value: 0,
      isManual: true,
    })
  }

  async function undo() {
    const last = purchases[purchases.length - 1]
    if (!last) return
    // Delete by id, not "the last row", so undo stays correct when two people
    // are entering at once.
    if (room && typeof last.id === 'number') {
      try {
        const d = await api.deleteAuctionPick(room, last.id)
        setPurchases(d.picks || [])
        setSyncedAt(new Date())
        setSyncErr('')
        return
      } catch (e) {
        setSyncErr(`Undo failed (${e.message})`)
        return
      }
    }
    setPurchases(prev => prev.slice(0, -1))
  }

  async function clearAll() {
    const msg = room
      ? `Clear all ${purchases.length} picks for EVERYONE in room ${room}? This cannot be undone.`
      : 'Clear every purchase and start this auction over?'
    if (!window.confirm(msg)) return
    if (!room) { setPurchases([]); return }
    try {
      let remaining = purchases
      for (const p of purchases) {
        if (typeof p.id === 'number') {
          const d = await api.deleteAuctionPick(room, p.id)
          remaining = d.picks || []
        }
      }
      setPurchases(remaining)
    } catch (e) {
      setSyncErr(`Clear failed (${e.message})`)
    }
  }

  if (loading) return <div className="rd-loading">Loading player values…</div>
  if (error) return <div className="rd-error">{error}</div>

  const adj = (v) => Math.max(1, Math.round(v * inflation))

  return (
    <div className="rd-board">
      {detail && (
        <PlayerDetail
          player={detail}
          adjPrice={adj(detail.auction_value)}
          onNominate={nominate}
          onClose={() => setDetail(null)}
        />
      )}
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

      {room && (
        <div className={`au-room-bar${syncErr ? ' au-room-bar-err' : ''}`}>
          <span className="au-room-code">Room {room}</span>
          <span className="au-room-sync">
            {syncErr
              ? syncErr
              : syncedAt
                ? `Shared · synced ${syncedAt.toLocaleTimeString()}`
                : 'Connecting…'}
          </span>
        </div>
      )}

      {inflation !== 1 && (
        <div className="au-inflation-note">
          {inflation > 1.05
            ? `Money is loose — remaining players are going for about ${((inflation - 1) * 100).toFixed(0)}% over base value. Expect to pay up.`
            : inflation < 0.95
              ? `Money is tight — remaining players should go about ${((1 - inflation) * 100).toFixed(0)}% under base value. Bargains ahead.`
              : 'Prices are tracking close to base value.'}
        </div>
      )}

      {nominated && (
        <>
          <EntryBar
            player={nominated}
            settings={settings}
            teamState={teamState}
            onSubmit={addPurchase}
            onCancel={() => nominate(null)}
          />
          {!nominated.isManual && nominated.position && (
            <CompetitionPanel
              position={nominated.position}
              teamState={teamState}
              settings={settings}
            />
          )}
        </>
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
            <span />
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
              <div
                key={p.sleeper_id}
                className={`au-player-row${nominated?.sleeper_id === p.sleeper_id ? ' active' : ''}`}
                onClick={() => setDetail(p)}
              >
                <div className="rd-player-info">
                  <PosPill pos={p.position} />
                  <span className="rd-player-name">{p.name}</span>
                  <span className="rd-player-team">{p.nfl_team}{p.pos_rank ? ` · ${p.position}${p.pos_rank}` : ''}</span>
                </div>
                <span className="rd-col-center au-val">${p.auction_value}</span>
                <span className="rd-col-center au-val-adj">${adj(p.auction_value)}</span>
                <span className="rd-col-center rd-col-muted">{p.vor > 0 ? `+${p.vor}` : p.vor}</span>
                <button
                  className="au-nom-btn"
                  onClick={e => { e.stopPropagation(); nominate(p) }}
                >
                  Nom
                </button>
              </div>
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
    // Clear the saved config too, otherwise it shadows DEFAULT_SETTINGS on the
    // next refresh. Purchases live under a separate key and are untouched.
    localStorage.removeItem(STORAGE_KEY)
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
