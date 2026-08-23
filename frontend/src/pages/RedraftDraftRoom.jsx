import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'

const STORAGE_KEY = 'espn_draft_config'
const POLL_MS = 5000

const POS_COLORS = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', K: '#8b90b0', DEF: '#666c8a' }

const TIER_COLORS = ['#01d9ac', '#5cb8e0', '#e0a45c', '#e05c5c', '#a05ce0', '#8b90b0']

const DEFAULT_SLOTS = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 2, K: 1, DEF: 1 }

function posNeeds(myPicks) {
  const filled = {}
  for (const pk of myPicks) {
    const pos = pk.position
    if (pos) filled[pos] = (filled[pos] || 0) + 1
  }
  const needed = {}
  for (const [pos, required] of Object.entries(DEFAULT_SLOTS)) {
    if (pos === 'FLEX') continue
    const have = filled[pos] || 0
    if (have < required) needed[pos] = required - have
  }
  if ((filled.RB || 0) + (filled.WR || 0) + (filled.TE || 0) < 2 + 2 + 1 + 2) {
    needed.FLEX = Math.max(0, 2 - Math.max(0, ((filled.RB || 0) + (filled.WR || 0) + (filled.TE || 0)) - 5))
  }
  return needed
}

function TierBadge({ tier }) {
  const color = TIER_COLORS[(tier - 1) % TIER_COLORS.length]
  return (
    <span className="rd-tier-badge" style={{ background: color + '22', color, borderColor: color + '66' }}>
      T{tier}
    </span>
  )
}

function VorChip({ vor }) {
  if (vor == null) return null
  const pos = vor >= 0
  return (
    <span className="rd-vor-chip" style={{ color: pos ? '#01d9ac' : '#e05c5c' }}>
      {pos ? '+' : ''}{Math.round(vor)}
    </span>
  )
}

function PosPill({ pos }) {
  return (
    <span className="rd-pos-pill" style={{ background: (POS_COLORS[pos] || '#8b90b0') + '22', color: POS_COLORS[pos] || '#8b90b0', borderColor: (POS_COLORS[pos] || '#8b90b0') + '55' }}>
      {pos || '?'}
    </span>
  )
}

function SetupForm({ onConnect }) {
  const saved = (() => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') } catch { return {} } })()
  const [form, setForm] = useState({
    leagueId: saved.leagueId || '',
    espnS2: saved.espnS2 || '',
    swid: saved.swid || '',
    mySlot: saved.mySlot || '1',
    season: saved.season || '2025',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [cookieHint, setCookieHint] = useState(false)

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function handleConnect(e) {
    e.preventDefault()
    if (!form.leagueId || !form.espnS2 || !form.swid) {
      setError('League ID, espn_s2, and SWID are required.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await api.getEspnDraftState(form.leagueId, form.espnS2, form.swid, form.season, form.mySlot)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(form))
      onConnect(form, data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rd-setup">
      <div className="rd-setup-card">
        <h2 className="rd-setup-title">ESPN Draft Room</h2>
        <p className="rd-setup-sub">Connect to your ESPN league to see live rankings, tier breaks, and VOR during your draft.</p>

        <form className="rd-setup-form" onSubmit={handleConnect}>
          <label className="rd-label">ESPN League ID
            <input className="rd-input" type="text" placeholder="e.g. 1234567" value={form.leagueId} onChange={e => set('leagueId', e.target.value)} />
          </label>
          <label className="rd-label">espn_s2 cookie
            <input className="rd-input" type="text" placeholder="AEB2..." value={form.espnS2} onChange={e => set('espnS2', e.target.value)} />
          </label>
          <label className="rd-label">SWID cookie
            <input className="rd-input" type="text" placeholder="{XXXXXXXX-XXXX-...}" value={form.swid} onChange={e => set('swid', e.target.value)} />
          </label>
          <div className="rd-setup-row">
            <label className="rd-label" style={{ flex: 1 }}>My Draft Slot
              <input className="rd-input" type="number" min="1" max="20" value={form.mySlot} onChange={e => set('mySlot', e.target.value)} />
            </label>
            <label className="rd-label" style={{ flex: 1 }}>Season
              <input className="rd-input" type="number" min="2020" max="2030" value={form.season} onChange={e => set('season', e.target.value)} />
            </label>
          </div>

          <button type="button" className="rd-cookie-toggle" onClick={() => setCookieHint(v => !v)}>
            How to find your cookies {cookieHint ? '▲' : '▼'}
          </button>
          {cookieHint && (
            <div className="rd-cookie-hint">
              <ol>
                <li>Open <strong>fantasy.espn.com</strong> and sign in</li>
                <li>Press <strong>F12</strong> → Application tab → Cookies → fantasy.espn.com</li>
                <li>Copy the <strong>espn_s2</strong> and <strong>SWID</strong> values</li>
              </ol>
            </div>
          )}

          {error && <div className="rd-error">{error}</div>}

          <button className="btn btn-primary rd-connect-btn" type="submit" disabled={loading}>
            {loading ? 'Connecting…' : 'Connect to Draft →'}
          </button>
        </form>
      </div>
    </div>
  )
}

function DraftBoard({ config, initialData }) {
  const [data, setData] = useState(initialData)
  const [posTab, setPosTab] = useState('ALL')
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const d = await api.getEspnDraftState(config.leagueId, config.espnS2, config.swid, config.season, config.mySlot)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [config])

  useEffect(() => {
    intervalRef.current = setInterval(refresh, POLL_MS)
    return () => clearInterval(intervalRef.current)
  }, [refresh])

  const myPicks = (data.teams || []).find(t => t.is_me)?.players || []
  const needs = posNeeds(myPicks)

  const available = (data.available || []).filter(p => {
    if (posTab !== 'ALL' && p.position !== posTab) return false
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="rd-board">
      <div className="rd-board-header">
        <div className="rd-board-status">
          {data.status === 'pre_draft' && <span className="rd-status-badge pre">Pre-Draft</span>}
          {data.status === 'drafting' && <span className="rd-status-badge live">LIVE</span>}
          {data.status === 'complete' && <span className="rd-status-badge done">Complete</span>}
          <span className="rd-board-picks">Pick {data.picks_made}/{data.total_picks}</span>
        </div>
        {error && <span className="rd-poll-error">Poll error — retrying</span>}
        <button className="btn btn-secondary btn-sm" onClick={refresh}>Refresh</button>
      </div>

      <div className="rd-board-body">
        {/* Left: Available Players */}
        <div className="rd-available">
          <div className="rd-available-header">
            <div className="rd-pos-tabs">
              {['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF'].map(pos => (
                <button
                  key={pos}
                  className={`rd-pos-tab${posTab === pos ? ' active' : ''}`}
                  style={posTab === pos && pos !== 'ALL' ? { background: POS_COLORS[pos] + '22', color: POS_COLORS[pos], borderColor: POS_COLORS[pos] + '88' } : {}}
                  onClick={() => setPosTab(pos)}
                >
                  {pos}
                </button>
              ))}
            </div>
            <input
              className="rd-search"
              type="text"
              placeholder="Search…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <div className="rd-player-list">
            <div className="rd-player-header">
              <span></span>
              <span>Player</span>
              <span className="rd-col-center">Rank</span>
              <span className="rd-col-center">Value</span>
              <span className="rd-col-center">VOR</span>
            </div>
            {available.length === 0 && (
              <div className="rd-empty">No available players matching filters.</div>
            )}
            {available.map((p, i) => {
              const prevTier = i > 0 ? available[i - 1].tier : p.tier
              const tierBreak = i > 0 && p.tier !== prevTier
              const isNeeded = needs[p.position] > 0
              return (
                <div key={p.sleeper_id}>
                  {tierBreak && (
                    <div className="rd-tier-break">
                      <span>— Tier {p.tier} —</span>
                    </div>
                  )}
                  <div className={`rd-player-row${isNeeded ? ' rd-needed' : ''}`}>
                    <TierBadge tier={p.tier} />
                    <div className="rd-player-info">
                      <PosPill pos={p.position} />
                      <span className="rd-player-name">{p.name}</span>
                      <span className="rd-player-team">{p.nfl_team}</span>
                    </div>
                    <span className="rd-col-center rd-rank">{p.redraft_pos_rank ? `${p.position}${p.redraft_pos_rank}` : '—'}</span>
                    <span className="rd-col-center rd-value">{p.redraft_value?.toLocaleString() ?? '—'}</span>
                    <VorChip vor={p.vor} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Right: Sidebar */}
        <div className="rd-sidebar">
          {/* On The Clock */}
          <div className={`rd-otc-card${data.my_pick_next ? ' my-turn' : ''}`}>
            {data.my_pick_next ? (
              <>
                <div className="rd-otc-label you">YOU'RE ON THE CLOCK</div>
                <div className="rd-otc-pick">Pick #{data.picks_made + 1}</div>
              </>
            ) : (
              <>
                <div className="rd-otc-label">On the Clock</div>
                <div className="rd-otc-team">{data.on_the_clock_team || '—'}</div>
                <div className="rd-otc-pick">Pick #{data.picks_made + 1}</div>
                {data.picks_until_my_turn > 0 && (
                  <div className="rd-otc-until">{data.picks_until_my_turn} pick{data.picks_until_my_turn !== 1 ? 's' : ''} until your turn</div>
                )}
              </>
            )}
          </div>

          {/* My Team */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title">My Team (Slot {config.mySlot})</div>
            {myPicks.length === 0 ? (
              <div className="rd-empty-sm">No picks yet</div>
            ) : (
              <div className="rd-my-picks">
                {['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].map(pos => {
                  const forPos = myPicks.filter(p => p.position === pos)
                  if (forPos.length === 0) return null
                  return (
                    <div key={pos} className="rd-my-pos-group">
                      <span className="rd-my-pos-label" style={{ color: POS_COLORS[pos] }}>{pos}</span>
                      <div className="rd-my-pos-players">
                        {forPos.map((p, i) => (
                          <span key={i} className="rd-my-chip">{p.player_name}</span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Positional Needs */}
          {Object.keys(needs).length > 0 && (
            <div className="rd-sidebar-section">
              <div className="rd-sidebar-title">Needs</div>
              <div className="rd-needs-grid">
                {Object.entries(needs).filter(([, n]) => n > 0).map(([pos, n]) => (
                  <span key={pos} className="rd-need-chip" style={{ background: (POS_COLORS[pos] || '#8b90b0') + '22', color: POS_COLORS[pos] || '#8b90b0' }}>
                    {pos} ×{n}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Recent Picks */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title">Recent Picks</div>
            {(data.recent_picks || []).length === 0 ? (
              <div className="rd-empty-sm">No picks yet</div>
            ) : (
              <div className="rd-recent-list">
                {(data.recent_picks || []).map((pk, i) => (
                  <div key={i} className="rd-recent-row">
                    <span className="rd-recent-pick-num">#{pk.overall}</span>
                    <PosPill pos={pk.position} />
                    <span className="rd-recent-name">{pk.player_name}</span>
                    <span className="rd-recent-team">{pk.team_name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function RedraftDraftRoom() {
  const [config, setConfig] = useState(null)
  const [initialData, setInitialData] = useState(null)

  function handleConnect(cfg, data) {
    setConfig(cfg)
    setInitialData(data)
  }

  function handleDisconnect() {
    setConfig(null)
    setInitialData(null)
  }

  if (!config || !initialData) {
    return <SetupForm onConnect={handleConnect} />
  }

  return (
    <div>
      <div className="rd-topbar">
        <button className="btn btn-secondary btn-sm" onClick={handleDisconnect}>← Back</button>
        <span className="rd-topbar-title">ESPN Draft Room · League {config.leagueId} · Season {config.season}</span>
      </div>
      <DraftBoard config={config} initialData={initialData} />
    </div>
  )
}
