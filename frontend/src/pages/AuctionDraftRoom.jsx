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
  passTdPts: 6, rushAttPts: 0.25,
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

// Short injury tag for the list rows — red for anything that means "not playing"
const INJ_SHORT = {
  Questionable: ['Q', '#e0a45c'], Doubtful: ['D', '#e05c5c'], Out: ['OUT', '#e05c5c'],
  IR: ['IR', '#e05c5c'], PUP: ['PUP', '#e05c5c'], Sus: ['SUS', '#e05c5c'],
  COV: ['COV', '#e0a45c'], NA: ['NA', '#e05c5c'],
}

function InjuryTag({ meta }) {
  const status = meta?.injury_status
  if (!status) return null
  const [label, color] = INJ_SHORT[status] || [String(status).slice(0, 3).toUpperCase(), '#e0a45c']
  return (
    <span className="au-inj-tag" style={{ color, borderColor: color + '66', background: color + '1a' }}>
      {label}
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

      <div className="au-setup-grid" style={{ marginTop: 8 }}>
        <label className="au-field">
          <span>Points per pass TD</span>
          <input
            className="yd-select" type="number" step="0.5" value={s.passTdPts} disabled={locked}
            onChange={e => setS(prev => ({ ...prev, passTdPts: parseFloat(e.target.value) || 0 }))}
          />
        </label>
        <label className="au-field">
          <span>Points per carry</span>
          <input
            className="yd-select" type="number" step="0.05" value={s.rushAttPts} disabled={locked}
            onChange={e => setS(prev => ({ ...prev, rushAttPts: parseFloat(e.target.value) || 0 }))}
          />
        </label>
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

  // Count surplus only in positions that can actually fill a flex `pos` competes
  // for. Pooling every position meant a spare K or DEF — which can never occupy
  // a flex slot — marked a team's superflex full, so the competition panel said
  // nobody could outbid you right before they did.
  // Only flex types this league actually has, or an RB surplus would leak into
  // a WR/TE-only flex the league never configured.
  const activeTypes = FLEX_TYPES.filter(
    ft => (settings[ft] || 0) > 0 && FLEX_ELIGIBLE[ft].includes(pos)
  )
  const eligible = new Set(activeTypes.flatMap(ft => FLEX_ELIGIBLE[ft]))
  const surplus = [...eligible].reduce(
    (n, p) => n + Math.max(0, (byPos[p]?.count || 0) - (settings[STARTER_KEYS[p]] || 0)),
    0,
  )
  return { starterNeed, flexOpen: Math.max(0, Math.min(flexForPos, flexForPos - surplus)) }
}

// ── Player detail ─────────────────────────────────────────────────────────────
//
// Uses the app's existing modal shell (.modal-backdrop / .modal-sheet / …,
// global.css:424) rather than a new pattern. A right-hand pane was considered
// and rejected: .main-content caps at 1100px and .rd-board-body collapses to a
// single column at 860px, so a third column would be unusable on a phone.

// Columns per position — short headers so a season fits on one line
const STAT_COLS = {
  QB: [['PaYd', 'pass_yd'], ['PaTD', 'pass_td'], ['Int', 'pass_int'], ['RuYd', 'rush_yd'], ['RuTD', 'rush_td']],
  RB: [['Att', 'rush_att'], ['RuYd', 'rush_yd'], ['RuTD', 'rush_td'], ['Rec', 'rec'], ['ReYd', 'rec_yd']],
  WR: [['Tgt', 'rec_tgt'], ['Rec', 'rec'], ['Yds', 'rec_yd'], ['TD', 'rec_td']],
  TE: [['Tgt', 'rec_tgt'], ['Rec', 'rec'], ['Yds', 'rec_yd'], ['TD', 'rec_td']],
}

function StatBlock({ player, seasons, ppr, scoring }) {
  const { proj, last } = player
  if (!proj && !last) {
    return <div className="au-stat-none">No stats or projections available for this player.</div>
  }
  // Match the fantasy-point figure to the league's scoring
  const baseKey = ppr === 1 ? 'pts_ppr' : ppr === 0.5 ? 'pts_half_ppr' : 'pts_std'
  // pts_league is the backend's restatement under this league's scoring
  const ptsKey = (proj?.pts_league != null || last?.pts_league != null) ? 'pts_league' : baseKey
  const cols = [['Pts', ptsKey], ['G', 'gp'], ...(STAT_COLS[player.position] || STAT_COLS.WR)]
  const fmt = (src, key) => {
    const v = src?.[key]
    if (v == null) return '—'
    return key.startsWith('pts') ? Math.round(v) : (Number.isInteger(v) ? v : Math.round(v))
  }
  const scoringNote = ptsKey === 'pts_league'
    ? `Points restated for this league: ${scoring.passTdPts} pt pass TD${
        scoring.rushAttPts ? `, ${scoring.rushAttPts} per carry` : ''}`
    : null
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
      {scoringNote && <div className="au-stat-note">{scoringNote}</div>}
    </div>
  )
}

function PlayerDetail({ player, adjPrice, seasons, ppr, scoring, onNominate, onClose }) {
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
          {player.meta && (
            <div className="au-meta-block">
              {player.meta.injury_status && (
                <div className="au-meta-row">
                  <InjuryTag meta={player.meta} />
                  <span className="au-meta-status">
                    {player.meta.injury_status}
                    {player.meta.practice_participation ? ` · ${player.meta.practice_participation}` : ''}
                  </span>
                </div>
              )}
              {player.meta.injury_notes && (
                <div className="au-meta-notes">{player.meta.injury_notes}</div>
              )}
              {player.meta.depth_chart_order != null && (
                <div className="au-meta-depth">
                  Depth chart: <strong>
                    {player.meta.depth_chart_position || player.position}
                    {player.meta.depth_chart_order}
                  </strong>
                  {player.meta.depth_chart_order === 1 ? ' — starter' : ''}
                </div>
              )}
            </div>
          )}
          <StatBlock player={player} seasons={seasons} ppr={ppr} scoring={scoring} />
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

// ── Cheat sheet ───────────────────────────────────────────────────────────────
//
// Every player grouped position -> tier, drafted ones kept in place with the
// estimate struck through and what they actually went for. The point is seeing
// how much talent is left in a tier, so removing drafted players would defeat it.

const CHEAT_POS = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']
const CHEAT_DEPTH = 40   // deep enough to cover anything rosterable in a 12-team league

function CheatSheet({ pool, purchases, settings, adj, onNominate }) {
  const [posFilter, setPosFilter] = useState('ALL')

  const boughtById = useMemo(() => {
    const m = new Map()
    for (const b of purchases) m.set(b.sleeper_id, b)
    return m
  }, [purchases])

  const groups = useMemo(() => {
    const out = {}
    for (const pos of CHEAT_POS) {
      // A single position gets the full list; "all" stays shallow so the
      // columns stay comparable side by side.
      const depth = posFilter === 'ALL' ? CHEAT_DEPTH : CHEAT_DEPTH * 3
      const players = pool.filter(p => p.position === pos).slice(0, depth)
      if (!players.length) continue
      const tiers = {}
      for (const p of players) {
        const t = p.tier || 1
        ;(tiers[t] = tiers[t] || []).push(p)
      }
      out[pos] = tiers
    }
    return out
  }, [pool, posFilter])

  const allPositions = Object.keys(groups)
  const positions = posFilter === 'ALL'
    ? allPositions
    : allPositions.filter(p => p === posFilter)

  return (
    <>
      <div className="rd-pos-tabs au-cheat-tabs">
        {['ALL', ...allPositions].map(p => (
          <button
            key={p}
            className={`rd-pos-tab${posFilter === p ? ' active' : ''}`}
            style={posFilter === p && p !== 'ALL'
              ? { background: (POS_COLORS[p] || '#8b90b0') + '22', color: POS_COLORS[p] || '#8b90b0', borderColor: (POS_COLORS[p] || '#8b90b0') + '88' }
              : {}}
            onClick={() => setPosFilter(p)}
          >{p}</button>
        ))}
      </div>
      {!positions.length
        ? <div className="rd-empty">No players loaded</div>
        : (
    <div className={`au-cheat${posFilter !== 'ALL' ? ' au-cheat-single' : ''}`}>
      {positions.map(pos => (
        <div key={pos} className="au-cheat-col">
          <div className="au-cheat-pos">
            <PosPill pos={pos} />
            <span className="au-cheat-pos-name">{pos}</span>
          </div>
          {Object.keys(groups[pos]).sort((a, b) => a - b).map(tier => {
            const players = groups[pos][tier]
            const left = players.filter(p => !boughtById.has(p.sleeper_id)).length
            return (
              <div key={tier} className="au-cheat-tier">
                <div className="au-cheat-tier-head">
                  <span>Tier {tier}</span>
                  <span className={left === 0 ? 'au-cheat-gone' : ''}>
                    {left} of {players.length} left
                  </span>
                </div>
                {players.map(p => {
                  const bought = boughtById.get(p.sleeper_id)
                  return (
                    <div
                      key={p.sleeper_id}
                      className={`au-cheat-row${bought ? ' au-cheat-drafted' : ''}`}
                      onClick={() => !bought && onNominate(p)}
                      title={bought ? '' : `Nominate ${p.name}`}
                    >
                      <span className="au-cheat-name">{p.name}</span>
                      <InjuryTag meta={p.meta} />
                      {bought ? (
                        <span className="au-cheat-prices">
                          <s className="au-cheat-est">${p.auction_value}</s>
                          <strong className={
                            bought.price > p.auction_value ? 'au-over'
                              : bought.price < p.auction_value ? 'au-under' : ''
                          }>${bought.price}</strong>
                          <span className="au-cheat-owner">
                            {settings.teamNames[bought.team] || `T${bought.team + 1}`}
                          </span>
                        </span>
                      ) : (
                        <span className="au-cheat-prices">
                          <span className="au-cheat-est-live">${adj(p.auction_value)}</span>
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      ))}
    </div>
        )}
    </>
  )
}

// ── Purchase entry bar ────────────────────────────────────────────────────────

function EntryBar({ player, settings, teamState, onSubmit, onCancel }) {
  const [price, setPrice] = useState('')
  const [team, setTeam] = useState(settings.myTeam)
  const [manualPos, setManualPos] = useState('K')
  const priceRef = useRef(null)

  // Keyed on the player's id, NOT the object: the 3s poll rebuilds `nominated`
  // from fresh JSON every tick, so an object-identity dep reset the price,
  // team and position every 3 seconds mid-entry.
  useEffect(() => {
    setPrice('')
    setTeam(settings.myTeam)
    setManualPos('K')
    priceRef.current?.focus()
  }, [player?.sleeper_id])

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
        {settings.teamNames.slice(0, settings.teams).map((n, i) => (
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
  const [seasons, setSeasons] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // Storage is keyed per room: a shared room must never open showing solo mode's
  // (or a previous room's) picks, which would otherwise render as this room's
  // and skew every budget until the first poll landed.
  const buysKey = (settings.roomCode ? `${STORAGE_KEY}_buys_${settings.roomCode}` : `${STORAGE_KEY}_buys`)
  const [purchases, setPurchases] = useState(() => {
    // In a room the server is authoritative — start empty and wait for the poll.
    if (settings.roomCode) return []
    try { return JSON.parse(localStorage.getItem(buysKey) || '[]') } catch { return [] }
  })
  // Who is up for bid — shared across the room. Distinct from `detail`, which is
  // just "I tapped a row to look at someone" and never leaves this browser.
  const [nominated, setNominated] = useState(null)
  const [detail, setDetail] = useState(null)
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')
  const [syncedAt, setSyncedAt] = useState(null)
  const [syncErr, setSyncErr] = useState('')
  const [view, setView] = useState('board')   // board | cheat

  const room = settings.roomCode || null

  // Picks that failed to reach the server. Kept OUT of `purchases` so the poll
  // (which wholesale-replaces it) can't drop them, retried on every tick.
  const [pending, setPending] = useState([])
  const pendingRef = useRef([])
  // Ids this client created, so Undo removes your own pick and not whichever
  // manager happened to enter last.
  const myPickIds = useRef([])
  // Ignore incoming nominations briefly after a local write, so an in-flight
  // GET issued before the write can't revert or resurrect it.
  const nominateGuard = useRef(0)
  // Drop out-of-order poll responses.
  const pollSeq = useRef(0)

  // Always mirror locally, shared or not: if the network drops mid-draft the
  // board keeps working from this copy.
  useEffect(() => {
    try { localStorage.setItem(buysKey, JSON.stringify(purchases)) } catch { /* quota */ }
  }, [purchases, buysKey])

  useEffect(() => { pendingRef.current = pending }, [pending])

  // Retry anything that didn't reach the server. Without this a single failed
  // POST lost the pick entirely on the next poll.
  useEffect(() => {
    if (!room || !pending.length) return
    let cancelled = false
    const flush = async () => {
      for (const p of pendingRef.current) {
        try {
          await api.addAuctionPick(room, p)
          if (cancelled) return
          setPending(prev => prev.filter(x => x._localId !== p._localId))
        } catch { return }   // still offline; try again next tick
      }
    }
    const t = setInterval(flush, POLL_MS)
    flush()
    return () => { cancelled = true; clearInterval(t) }
  }, [room, pending.length])

  // In a shared room the server is the source of truth for picks
  useEffect(() => {
    if (!room) return
    let cancelled = false
    const tick = async () => {
      const seq = ++pollSeq.current
      try {
        const d = await api.getAuctionRoom(room)
        if (cancelled || seq !== pollSeq.current) return   // a newer poll already landed
        setPurchases(d.picks || [])
        // Don't clobber a nomination we just made locally, and don't churn the
        // object identity when nothing changed (that resets the entry bar).
        if (Date.now() > nominateGuard.current) {
          const incoming = d.nominated || null
          setNominated(prev =>
            (prev?.sleeper_id ?? null) === (incoming?.sleeper_id ?? null) ? prev : incoming
          )
        }
        setSyncedAt(new Date())
        setSyncErr(prevErr => (pendingRef.current.length ? prevErr : ''))
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
      .then(d => { setPool(d.players || []); setSeasons(d.seasons || null); setError('') })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [settings])

  const size = rosterSize(settings)

  // ── Derived team state ──────────────────────────────────────────────────────
  // Unsent picks count toward budgets immediately — otherwise a dropped
  // connection would make a team look richer than it is.
  const allPurchases = useMemo(
    () => (pending.length ? [...purchases, ...pending] : purchases),
    [purchases, pending],
  )

  const teamState = useMemo(() => settings.teamNames.map((name, i) => {
    const bought = allPurchases.filter(p => p.team === i)
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
  }), [allPurchases, settings, size])

  const me = teamState[settings.myTeam]

  // ── Inflation ───────────────────────────────────────────────────────────────
  const draftedIds = useMemo(() => new Set(allPurchases.map(p => p.sleeper_id)), [allPurchases])
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
    // Ignore server nominations briefly: a GET issued before this write lands
    // would otherwise revert it, or resurrect a player who was just bought.
    nominateGuard.current = Date.now() + POLL_MS * 2
    try {
      await api.setAuctionNomination(room, player)
      setSyncErr('')
    } catch (e) {
      setSyncErr(`Nomination not shared (${e.message}) — visible only to you`)
    } finally {
      nominateGuard.current = Date.now() + 500
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

    // Two managers entering the same sale would otherwise debit the buying team
    // twice. The server rejects duplicates too; this is the fast, local check.
    if (!pick.sleeper_id.startsWith('manual_') && draftedIds.has(pick.sleeper_id)) {
      setSyncErr(`${pick.name} is already recorded as drafted`)
      await nominate(null)
      setSearch('')
      return
    }

    // They're bought — clear the block for everyone. Awaited so an in-flight
    // poll can't re-open the entry bar for the player just purchased.
    await nominate(null)
    setSearch('')

    if (!room) {
      setPurchases(prev => [...prev, { ...pick, id: `local_${Date.now()}` }])
      return
    }
    try {
      // The server returns the full list, so there's nothing to merge
      const d = await api.addAuctionPick(room, pick)
      setPurchases(d.picks || [])
      if (d.duplicate) setSyncErr(`${pick.name} was already entered by someone else`)
      else setSyncErr('')
      // Remember our own ids so Undo targets this client's picks
      const mine = (d.picks || []).find(x => x.sleeper_id === pick.sleeper_id)
      if (mine) myPickIds.current.push(mine.id)
      setSyncedAt(new Date())
    } catch (e) {
      // Held in `pending`, which the poll never clears, and retried until it lands
      setPending(prev => [...prev, { ...pick, _localId: `local_${Date.now()}` }])
      setSyncErr(`Not saved yet (${e.message}) — retrying`)
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
    // Drop an unsent pick first — it isn't on the server to delete.
    if (pending.length) {
      setPending(prev => prev.slice(0, -1))
      return
    }
    if (!room) {
      setPurchases(prev => prev.slice(0, -1))
      return
    }
    // `purchases` is the room's list ordered across ALL managers, so its last
    // row is usually someone else's pick. Undo only what this client entered.
    const live = new Set(purchases.map(p => p.id))
    const mine = myPickIds.current.filter(id => live.has(id))
    if (!mine.length) {
      setSyncErr('Nothing of yours to undo — only the manager who entered a pick can remove it')
      return
    }
    const target = mine[mine.length - 1]
    try {
      const d = await api.deleteAuctionPick(room, target)
      setPurchases(d.picks || [])
      myPickIds.current = myPickIds.current.filter(id => id !== target)
      setSyncedAt(new Date())
      setSyncErr(d.deleted ? '' : 'That pick was already removed')
    } catch (e) {
      setSyncErr(`Undo failed (${e.message})`)
    }
  }

  async function clearAll() {
    const msg = room
      ? `Clear all ${purchases.length} picks for EVERYONE in room ${room}? This cannot be undone.`
      : 'Clear every purchase and start this auction over?'
    if (!window.confirm(msg)) return
    setPending([])
    myPickIds.current = []
    if (!room) { setPurchases([]); return }
    try {
      // One request. Deleting 200+ picks one at a time raced the poll and left
      // the room half-cleared if it failed partway.
      const d = await api.clearAuctionPicks(room)
      setPurchases(d.picks || [])
      setNominated(null)
      setSyncErr('')
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
          seasons={seasons}
          ppr={settings.ppr}
          scoring={{ passTdPts: settings.passTdPts ?? 4, rushAttPts: settings.rushAttPts ?? 0 }}
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

      <div className="au-view-toggle">
        {[['board', 'Board'], ['cheat', 'Cheat Sheet']].map(([v, label]) => (
          <button
            key={v}
            className={`au-view-btn${view === v ? ' active' : ''}`}
            onClick={() => setView(v)}
          >{label}</button>
        ))}
      </div>

      {view === 'cheat' ? (
        <CheatSheet
          pool={pool}
          purchases={purchases}
          settings={settings}
          adj={adj}
          onNominate={nominate}
        />
      ) : (
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
            {filtered.length === 0 && (() => {
              const q = search.trim()
              if (!q) return <div className="rd-empty">No players match</div>
              // `available` excludes drafted players, so a search for someone
              // already bought would otherwise fall through to the manual-add
              // path and create a duplicate at the default position.
              const gone = pool.find(
                p => !available.some(a => a.sleeper_id === p.sleeper_id)
                  && p.name.toLowerCase().includes(q.toLowerCase())
              )
              if (gone) {
                const b = allPurchases.find(x => x.sleeper_id === gone.sleeper_id)
                return (
                  <div className="rd-empty">
                    {gone.name} is already drafted
                    {b ? ` — $${b.price} to ${settings.teamNames[b.team] || `Team ${b.team + 1}`}` : ''}
                  </div>
                )
              }
              return (
                <button className="au-add-manual" onClick={addManual}>
                  <span className="au-add-manual-plus">+</span>
                  Add “{q}” — kickers, defenses and unranked players
                </button>
              )
            })()}
            {filtered.slice(0, 200).map(p => (
              <div
                key={p.sleeper_id}
                className={`au-player-row${nominated?.sleeper_id === p.sleeper_id ? ' active' : ''}`}
                onClick={() => setDetail(p)}
              >
                <div className="rd-player-info">
                  <PosPill pos={p.position} />
                  <span className="rd-player-name">{p.name}</span>
                  <InjuryTag meta={p.meta} />
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
      )}
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
