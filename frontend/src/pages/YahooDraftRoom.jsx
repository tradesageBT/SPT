import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'

const STORAGE_KEY = 'yahoo_draft_config'
const POLL_MS = 5000

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c',
  K: '#8b90b0', DEF: '#666c8a', DST: '#666c8a',
}

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

// ── Setup screens ─────────────────────────────────────────────────────────────

function ConnectScreen() {
  return (
    <div className="yd-setup-card">
      <div className="yd-setup-title">Connect Yahoo Fantasy</div>
      <p className="yd-setup-sub">
        Authorize once — tokens auto-refresh. No cookies needed.
      </p>
      <a href="/api/yahoo-draft/auth" className="btn btn-primary yd-connect-btn">
        Connect Yahoo Account
      </a>
      <p className="yd-setup-hint">
        Need credentials? Register a free app at{' '}
        <strong>developer.yahoo.com</strong> → Fantasy Sports → Read scope, then
        add <code>YAHOO_CLIENT_ID</code> and <code>YAHOO_CLIENT_SECRET</code> in
        Render environment variables.
      </p>
    </div>
  )
}

function LeagueSetup({ onStart }) {
  const [leagues, setLeagues] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [leagueKey, setLeagueKey] = useState('')
  const [myTeamKey, setMyTeamKey] = useState('')
  const [teams, setTeams] = useState([])
  const [loadingTeams, setLoadingTeams] = useState(false)

  useEffect(() => {
    api.getYahooLeagues()
      .then(setLeagues)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  async function handleLeagueChange(key) {
    setLeagueKey(key)
    setMyTeamKey('')
    setTeams([])
    if (!key) return
    setLoadingTeams(true)
    try {
      const state = await api.getYahooDraftState(key)
      setTeams(state.teams || [])
    } catch { /* ignore */ }
    finally { setLoadingTeams(false) }
  }

  function start() {
    if (!leagueKey || !myTeamKey) return
    onStart({ leagueKey, myTeamKey })
  }

  if (loading) return <div className="yd-setup-card"><div className="rd-loading">Loading your leagues…</div></div>

  return (
    <div className="yd-setup-card">
      <div className="yd-setup-title">Select League &amp; Team</div>

      {error && <div className="rd-error">{error}</div>}

      <label className="yd-label">Your Yahoo Fantasy Football League</label>
      <select
        className="yd-select"
        value={leagueKey}
        onChange={e => handleLeagueChange(e.target.value)}
      >
        <option value="">— Select a league —</option>
        {leagues.map(l => (
          <option key={l.league_key} value={l.league_key}>
            {l.name} ({l.season}, {l.num_teams} teams)
          </option>
        ))}
      </select>

      {leagueKey && (
        <>
          <label className="yd-label" style={{ marginTop: 14 }}>Your Team</label>
          {loadingTeams
            ? <div className="rd-loading">Loading teams…</div>
            : (
              <select className="yd-select" value={myTeamKey} onChange={e => setMyTeamKey(e.target.value)}>
                <option value="">— Select your team —</option>
                {teams.map(t => (
                  <option key={t.team_key} value={t.team_key}>
                    {t.name} (slot {t.draft_position || '?'})
                  </option>
                ))}
              </select>
            )
          }
        </>
      )}

      <button
        className="btn btn-primary"
        style={{ marginTop: 20, width: '100%' }}
        disabled={!leagueKey || !myTeamKey}
        onClick={start}
      >
        Open Draft Board
      </button>
    </div>
  )
}

// ── Draft board ───────────────────────────────────────────────────────────────

const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF']

function AvailablePlayers({ players, myTeamKey, onFilter }) {
  const [pos, setPos] = useState('ALL')
  const [search, setSearch] = useState('')

  const filtered = players.filter(p => {
    if (pos !== 'ALL') {
      const ppos = p.position === 'DST' ? 'DEF' : p.position
      if (ppos !== pos) return false
    }
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
          const showTierBreak = p.tier && p.tier !== prevTier && i > 0
          prevTier = p.tier
          return (
            <div key={p.player_key || i}>
              {showTierBreak && (
                <div className="rd-tier-break">— Tier {p.tier} —</div>
              )}
              <div className="yd-player-row">
                <TierBadge tier={p.tier} />
                <div className="rd-player-info">
                  <PosPill pos={p.position === 'DST' ? 'DEF' : p.position} />
                  <span className="rd-player-name">{p.name}</span>
                  <span className="rd-player-team">{p.nfl_team}</span>
                </div>
                <span className="rd-col-center rd-col-muted">{p.redraft_pos_rank ? `${p.position === 'DST' ? 'DEF' : p.position}${p.redraft_pos_rank}` : '—'}</span>
                <span className="rd-col-center" style={{ color: '#01d9ac', fontWeight: 700 }}>{p.redraft_value ? p.redraft_value.toLocaleString() : '—'}</span>
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

function Sidebar({ data, myTeamKey, teams }) {
  const myTeam = teams.find(t => t.team_key === myTeamKey)
  const myPicks = (data.all_picks || []).filter(p => p.team_key === myTeamKey)
  const recentPicks = [...(data.picks || [])].reverse()
  const isMyTurn = data.on_the_clock_key === myTeamKey

  return (
    <div className="rd-sidebar">
      {/* On the clock */}
      <div className={`yd-otc-card${isMyTurn ? ' yd-otc-you' : ''}`}>
        {data.status === 'pre_draft' && <div className="yd-otc-label">Draft hasn't started</div>}
        {data.status === 'complete' && <div className="yd-otc-label">Draft complete</div>}
        {data.status === 'drafting' && (
          <>
            {isMyTurn && <div className="yd-otc-you-banner">🎯 You're on the clock!</div>}
            <div className="yd-otc-label">{data.is_auction ? 'Auction in progress' : 'On the clock'}</div>
            {!data.is_auction && (
              <div className="yd-otc-team">{data.on_the_clock_name || '—'}</div>
            )}
            <div className="yd-otc-pick">
              Pick {data.picks_made + 1} of {data.total_picks}
            </div>
          </>
        )}
      </div>

      {/* My team */}
      <div className="yd-sidebar-section">
        <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>
          My Team {myTeam ? `— ${myTeam.name}` : ''}
        </div>
        {myPicks.length === 0
          ? <div className="rd-empty" style={{ fontSize: '0.75rem' }}>No picks yet</div>
          : myPicks.map((pk, i) => (
            <div key={i} className="yd-my-pick">
              <PosPill pos={pk.position || 'PK'} />
              <span className="yd-my-pick-name">{pk.player_name}</span>
              <span className="yd-my-pick-round">R{pk.round}</span>
              {pk.cost > 0 && <span className="yd-my-pick-cost">${pk.cost}</span>}
            </div>
          ))
        }
      </div>

      {/* Recent picks */}
      <div className="yd-sidebar-section">
        <div className="rd-sidebar-title" style={{ marginBottom: 8 }}>Recent Picks</div>
        {recentPicks.length === 0
          ? <div className="rd-empty" style={{ fontSize: '0.75rem' }}>No picks yet</div>
          : recentPicks.map((pk, i) => (
            <div key={i} className="yd-recent-pick">
              <span className="yd-recent-pick-round">R{pk.round}.{pk.pick}</span>
              <PosPill pos={pk.position || 'PK'} />
              <span className="yd-recent-pick-name">{pk.player_name}</span>
              <span className="yd-recent-pick-team">{pk.team_name}</span>
              {pk.cost > 0 && <span className="yd-recent-pick-cost">${pk.cost}</span>}
            </div>
          ))
        }
      </div>
    </div>
  )
}

function DraftBoard({ config, onReset }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [lastPoll, setLastPoll] = useState(null)
  const timerRef = useRef(null)

  const poll = useCallback(async () => {
    try {
      const d = await api.getYahooDraftState(config.leagueKey)
      setData(d)
      setError('')
    } catch (e) {
      setError(e.message)
    }
    setLastPoll(new Date())
  }, [config.leagueKey])

  useEffect(() => {
    poll()
    timerRef.current = setInterval(poll, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [poll])

  if (!data && !error) return <div className="rd-loading">Connecting to Yahoo draft…</div>
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
          {lastPoll && <span style={{ marginLeft: 8, color: 'var(--text-muted)', fontSize: '0.68rem' }}>
            Updated {lastPoll.toLocaleTimeString()}
          </span>}
          {error && <span style={{ marginLeft: 8, color: 'var(--danger)', fontSize: '0.72rem' }}>{error}</span>}
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onReset}>Change League</button>
      </div>

      <div className="rd-board-body">
        <AvailablePlayers players={data?.available ?? []} myTeamKey={config.myTeamKey} />
        <Sidebar data={data ?? {}} myTeamKey={config.myTeamKey} teams={data?.teams ?? []} />
      </div>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function YahooDraftRoom() {
  const [status, setStatus] = useState(null)  // null = loading
  const [oauthError, setOauthError] = useState('')
  const [config, setConfig] = useState(() => {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') } catch { return null }
  })

  useEffect(() => {
    api.getYahooStatus().then(setStatus).catch(() => setStatus({ connected: false }))
    const params = new URLSearchParams(window.location.search)
    if (params.get('connected') === 'true') {
      window.history.replaceState({}, '', '/yahoo-draft')
    }
    if (params.get('error')) {
      setOauthError(`Yahoo authorization failed: ${params.get('error')}. Please try connecting again.`)
      window.history.replaceState({}, '', '/yahoo-draft')
    }
  }, [])

  function handleStart(cfg) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
    setConfig(cfg)
  }

  function handleReset() {
    localStorage.removeItem(STORAGE_KEY)
    setConfig(null)
  }

  if (status === null) return <div className="rd-loading">Loading…</div>

  if (!status.connected) return (
    <div className="yd-page">
      <div className="rd-topbar">
        <div className="rd-topbar-title">Yahoo Draft Assistant</div>
      </div>
      {oauthError && <div className="rd-error" style={{ margin: '0 0 12px' }}>{oauthError}</div>}
      <ConnectScreen />
    </div>
  )

  if (!config) return (
    <div className="yd-page">
      <div className="rd-topbar">
        <div className="rd-topbar-title">Yahoo Draft Assistant</div>
        <button className="btn btn-secondary btn-sm" onClick={() => {
          api.disconnectYahoo().then(() => setStatus({ connected: false }))
        }}>Disconnect</button>
      </div>
      <LeagueSetup onStart={handleStart} />
    </div>
  )

  return (
    <div className="yd-page">
      <div className="rd-topbar">
        <div className="rd-topbar-title">Yahoo Draft Assistant</div>
        <button className="btn btn-secondary btn-sm" onClick={handleReset}>Change League</button>
      </div>
      <DraftBoard config={config} onReset={handleReset} />
    </div>
  )
}
