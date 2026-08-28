import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'

const STORAGE_KEY = 'sleeper_draft_config'
const POLL_MS = 5000

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c',
  K: '#8b90b0', DEF: '#666c8a',
}
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF']

function PosPill({ pos }) {
  const c = POS_COLORS[pos] || '#8b90b0'
  return (
    <span className="rd-pos-pill" style={{ background: c + '22', color: c, borderColor: c + '55' }}>
      {pos || '?'}
    </span>
  )
}

function TierBadge({ tier }) {
  if (!tier) return null
  const colors = ['#e05c5c', '#e0a45c', '#5cb8e0', '#01d9ac', '#8b90b0']
  const c = colors[Math.min(tier - 1, colors.length - 1)]
  return (
    <span className="rd-tier-badge" style={{ background: c + '22', color: c, borderColor: c + '55' }}>
      T{tier}
    </span>
  )
}

// ── Setup ─────────────────────────────────────────────────────────────────────

function SetupForm({ onStart }) {
  const [leagueId, setLeagueId] = useState('')
  const [myRosterId, setMyRosterId] = useState('')
  const [teams, setTeams] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    if (!leagueId.trim()) return
    setLoading(true)
    setError('')
    setTeams([])
    setMyRosterId('')
    try {
      const data = await api.getSleeperDraftState(leagueId.trim())
      setTeams(data.teams || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function start() {
    if (!leagueId || !myRosterId) return
    onStart({ leagueId: leagueId.trim(), myRosterId: parseInt(myRosterId) })
  }

  return (
    <div className="yd-setup-card">
      <div className="yd-setup-title">Sleeper Draft Assistant</div>
      <p className="yd-setup-sub">Enter your Sleeper league ID to connect.</p>
      <p className="yd-setup-hint">
        Find it in your league URL: sleeper.com/leagues/<strong>[LEAGUE ID]</strong>
      </p>

      {error && <div className="rd-error">{error}</div>}

      <label className="yd-label">Sleeper League ID</label>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          className="yd-select"
          placeholder="e.g. 1234567890"
          value={leagueId}
          onChange={e => setLeagueId(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()}
          style={{ flex: 1 }}
        />
        <button className="btn btn-secondary" onClick={load} disabled={loading || !leagueId.trim()}>
          {loading ? '…' : 'Load'}
        </button>
      </div>

      {teams.length > 0 && (
        <>
          <label className="yd-label" style={{ marginTop: 14 }}>Your Team</label>
          <select className="yd-select" value={myRosterId} onChange={e => setMyRosterId(e.target.value)}>
            <option value="">— Select your team —</option>
            {teams.map(t => (
              <option key={t.roster_id} value={t.roster_id}>
                {t.name} (slot {t.draft_slot})
              </option>
            ))}
          </select>
        </>
      )}

      {teams.length > 0 && (
        <button
          className="btn btn-primary"
          style={{ marginTop: 16, width: '100%' }}
          disabled={!myRosterId}
          onClick={start}
        >
          Open Draft Board
        </button>
      )}
    </div>
  )
}

// ── Available players ─────────────────────────────────────────────────────────

function AvailablePlayers({ players }) {
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')

  const filtered = players.filter(p => {
    if (pos !== 'ALL' && p.position !== pos) return false
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  let prevTier = null

  return (
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
        style={{ marginBottom: 8 }}
      />
      <div className="rd-player-header">
        <span></span>
        <span>Player</span>
        <span className="rd-col-center">Rank</span>
        <span className="rd-col-center">Value</span>
        <span className="rd-col-center">VOR</span>
      </div>
      <div className="rd-player-list">
        {filtered.length === 0 && <div className="rd-empty">No players match</div>}
        {filtered.map((p, i) => {
          const showBreak = p.tier && p.tier !== prevTier && i > 0
          prevTier = p.tier
          return (
            <div key={p.player_id || i}>
              {showBreak && <div className="rd-tier-break">— Tier {p.tier} —</div>}
              <div className="yd-player-row">
                <TierBadge tier={p.tier} />
                <div className="rd-player-info">
                  <PosPill pos={p.position} />
                  <span className="rd-player-name">{p.name}</span>
                  <span className="rd-player-team">{p.nfl_team}</span>
                </div>
                <span className="rd-col-center rd-col-muted">
                  {p.redraft_pos_rank ? `${p.position}${p.redraft_pos_rank}` : '—'}
                </span>
                <span className="rd-col-center" style={{ color: '#01d9ac', fontWeight: 700 }}>
                  {p.redraft_value ? p.redraft_value.toLocaleString() : '—'}
                </span>
                <span className="rd-col-center" style={{ color: (p.vor || 0) >= 0 ? '#01d9ac' : '#e05c5c', fontWeight: 600 }}>
                  {p.vor != null ? (p.vor >= 0 ? '+' : '') + Math.round(p.vor) : '—'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar({ data, myRosterId, teams }) {
  const myTeam = teams.find(t => t.roster_id === myRosterId)
  const myPicks = (data.all_picks || []).filter(p => p.roster_id === myRosterId)
  const recentPicks = [...(data.picks || [])].reverse()
  const isMyTurn = data.on_the_clock_roster_id === myRosterId

  return (
    <div className="rd-sidebar">
      <div className={`yd-otc-card${isMyTurn ? ' yd-otc-you' : ''}`}>
        {data.status === 'pre_draft' && <div className="yd-otc-label">Draft hasn't started</div>}
        {data.status === 'complete' && <div className="yd-otc-label">Draft complete</div>}
        {data.status === 'drafting' && (
          <>
            {isMyTurn && <div className="yd-otc-you-banner">🎯 You're on the clock!</div>}
            <div className="yd-otc-label">On the clock</div>
            <div className="yd-otc-team">{data.on_the_clock_name || '—'}</div>
            <div className="yd-otc-pick">Pick {data.picks_made + 1} of {data.total_picks}</div>
          </>
        )}
      </div>

      <div className="yd-sidebar-section">
        <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>
          My Team{myTeam ? ` — ${myTeam.name}` : ''}
        </div>
        {myPicks.length === 0
          ? <div className="rd-empty" style={{ fontSize: '0.75rem' }}>No picks yet</div>
          : myPicks.map((pk, i) => (
            <div key={i} className="yd-my-pick">
              <PosPill pos={pk.position || 'PK'} />
              <span className="yd-my-pick-name">{pk.player_name}</span>
              <span className="yd-my-pick-round">R{pk.round}</span>
            </div>
          ))
        }
      </div>

      <div className="yd-sidebar-section">
        <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>Recent Picks</div>
        {recentPicks.length === 0
          ? <div className="rd-empty" style={{ fontSize: '0.75rem' }}>No picks yet</div>
          : recentPicks.map((pk, i) => (
            <div key={i} className="yd-recent-pick">
              <span className="yd-recent-pick-round">R{pk.round}.{pk.pick_no}</span>
              <PosPill pos={pk.position || 'PK'} />
              <span className="yd-recent-pick-name">{pk.player_name}</span>
              <span className="yd-recent-pick-team">{pk.team_name}</span>
            </div>
          ))
        }
      </div>
    </div>
  )
}

// ── Draft board ───────────────────────────────────────────────────────────────

function DraftBoard({ config, onReset }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [lastPoll, setLastPoll] = useState(null)
  const timerRef = useRef(null)

  const poll = useCallback(async () => {
    try {
      const d = await api.getSleeperDraftState(config.leagueId)
      setData(d)
      setError('')
    } catch (e) {
      setError(e.message)
    }
    setLastPoll(new Date())
  }, [config.leagueId])

  useEffect(() => {
    poll()
    timerRef.current = setInterval(poll, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [poll])

  if (!data && !error) return <div className="rd-loading">Connecting to Sleeper draft…</div>
  if (error && !data) return (
    <div className="rd-error">
      {error}
      <button className="btn btn-secondary btn-sm" style={{ marginTop: 10 }} onClick={poll}>Retry</button>
    </div>
  )

  return (
    <div className="rd-board">
      <div className="rd-board-topbar">
        <div className="rd-board-status">
          {data?.picks_made ?? 0} picks · {data?.available?.length ?? 0} available
          {lastPoll && (
            <span style={{ marginLeft: 8, color: 'var(--text-muted)', fontSize: '0.68rem' }}>
              Updated {lastPoll.toLocaleTimeString()}
            </span>
          )}
          {error && <span style={{ marginLeft: 8, color: 'var(--danger)', fontSize: '0.72rem' }}>{error}</span>}
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onReset}>Change League</button>
      </div>
      <div className="rd-board-body">
        <AvailablePlayers players={data?.available ?? []} />
        <Sidebar data={data ?? {}} myRosterId={config.myRosterId} teams={data?.teams ?? []} />
      </div>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function SleeperDraftRoom() {
  const [config, setConfig] = useState(() => {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') } catch { return null }
  })

  function handleStart(cfg) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
    setConfig(cfg)
  }

  function handleReset() {
    localStorage.removeItem(STORAGE_KEY)
    setConfig(null)
  }

  return (
    <div className="yd-page">
      <div className="rd-topbar">
        <div className="rd-topbar-title">Sleeper Draft Assistant</div>
        {config && <button className="btn btn-secondary btn-sm" onClick={handleReset}>Change League</button>}
      </div>
      {config
        ? <DraftBoard config={config} onReset={handleReset} />
        : <SetupForm onStart={handleStart} />
      }
    </div>
  )
}
