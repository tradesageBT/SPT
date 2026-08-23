import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'

const STORAGE_KEY = 'espn_draft_config'  // legacy single-league key
const LEAGUES_KEY = 'espn_saved_leagues'  // new: array of saved leagues
const POLL_MS = 5000

function getSavedLeagues() {
  try {
    const arr = JSON.parse(localStorage.getItem(LEAGUES_KEY) || '[]')
    if (arr.length) return arr
    // migrate legacy single-league config
    const old = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (old.leagueId) return [{ ...old, savedAt: 0, name: `League ${old.leagueId}` }]
    return []
  } catch { return [] }
}

function saveLeague(cfg) {
  const leagues = getSavedLeagues()
  const idx = leagues.findIndex(l => l.leagueId === cfg.leagueId && String(l.season) === String(cfg.season))
  const entry = { ...cfg, savedAt: Date.now(), name: cfg.name || `League ${cfg.leagueId} (${cfg.season})` }
  if (idx >= 0) leagues[idx] = entry
  else leagues.unshift(entry)
  localStorage.setItem(LEAGUES_KEY, JSON.stringify(leagues.slice(0, 5)))
}

const POS_COLORS = {
  QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', K: '#8b90b0', DEF: '#666c8a',
  LB: '#c084fc', DL: '#fb923c', DB: '#60a5fa',
}
const TIER_COLORS = ['#01d9ac', '#5cb8e0', '#e0a45c', '#e05c5c', '#a05ce0', '#8b90b0']
const IDP_POSITIONS = ['LB', 'DL', 'DB']
const ALL_POS_TABS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF', ...IDP_POSITIONS]
const DEFAULT_POS_BUDGET = { QB: 20, RB: 75, WR: 65, TE: 25, K: 1, DEF: 1, LB: 5, DL: 5, DB: 3 }

function TierBadge({ tier }) {
  if (tier == null) return <span className="rd-tier-badge" style={{ background: 'transparent', borderColor: 'transparent', color: 'transparent' }}>—</span>
  const color = TIER_COLORS[(tier - 1) % TIER_COLORS.length]
  return (
    <span className="rd-tier-badge" style={{ background: color + '22', color, borderColor: color + '66' }}>
      T{tier}
    </span>
  )
}

function VorChip({ vor }) {
  if (vor == null) return <span className="rd-vor-chip rd-col-center" style={{ color: 'var(--text-muted)' }}>—</span>
  const pos = vor >= 0
  return <span className="rd-vor-chip rd-col-center" style={{ color: pos ? '#01d9ac' : '#e05c5c' }}>{pos ? '+' : ''}{Math.round(vor)}</span>
}

function AuctionChip({ value, maxBid }) {
  if (value == null) return <span className="rd-col-center" style={{ color: 'var(--text-muted)' }}>—</span>
  const affordable = maxBid == null || value <= maxBid
  return (
    <span className="rd-col-center rd-auction-val" style={{ color: affordable ? '#01d9ac' : '#e05c5c', fontWeight: 600 }}>
      ${value}
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

function TeamNeeds({ player, teams, rosterSlots }) {
  if (!player || !rosterSlots) return null
  const pos = player.position
  const directSlots = rosterSlots[pos] || 0
  const flexSlots = ['RB', 'WR', 'TE'].includes(pos)
    ? (rosterSlots['FLEX'] || 0) + (rosterSlots['WTTE'] || 0)
    : 0
  const effectiveSlots = directSlots + flexSlots
  if (effectiveSlots === 0) return null

  const rows = [...teams]
    .filter(t => !t.is_me)
    .map(t => {
      const filled = (t.pos_counts || {})[pos] || 0
      const needs = filled < effectiveSlots
      const canAfford = (t.budget_remaining || 0) > (t.slots_remaining || 0) + 5
      return { ...t, filled, needs, canAfford, threat: needs && canAfford }
    })
    .sort((a, b) => {
      if (a.threat !== b.threat) return b.threat - a.threat
      if (a.needs !== b.needs) return b.needs - a.needs
      return (b.budget_remaining || 0) - (a.budget_remaining || 0)
    })

  return (
    <div className="rd-team-needs">
      <div className="rd-tn-header">Who needs {pos}?</div>
      <div className="rd-tn-grid">
        <span className="rd-tn-col-hdr">Team</span>
        <span className="rd-tn-col-hdr rd-tn-right">{pos} filled</span>
        <span className="rd-tn-col-hdr rd-tn-right">$ left</span>
        <span className="rd-tn-col-hdr rd-tn-right">max bid</span>
        {rows.map((t, i) => {
          const color = t.threat ? '#e05c5c' : t.needs ? '#e0a45c' : 'var(--text-muted)'
          return [
            <span key={i + 'n'} className="rd-tn-name" style={{ color }}>{t.team_name}</span>,
            <span key={i + 'f'} className="rd-tn-right" style={{ color }}>{t.filled}/{effectiveSlots}</span>,
            <span key={i + 'b'} className="rd-tn-right">${t.budget_remaining ?? '?'}</span>,
            <span key={i + 'm'} className="rd-tn-right" style={{ color }}>${t.max_bid ?? '?'}</span>,
          ]
        })}
      </div>
    </div>
  )
}

function SetupForm({ onConnect, savedLeagues, onDeleteLeague }) {
  const leagues = savedLeagues || []
  const prefill = leagues[0] || {}
  const [form, setForm] = useState({
    name: prefill.name || '',
    leagueId: prefill.leagueId || '',
    espnS2: prefill.espnS2 || '',
    swid: prefill.swid || '',
    mySlot: prefill.mySlot || '1',
    budget: prefill.budget || '200',
    season: prefill.season || '2026',
    posBudget: prefill.posBudget || { ...DEFAULT_POS_BUDGET },
  })
  const [loading, setLoading] = useState(false)
  const [loadingIdx, setLoadingIdx] = useState(null)
  const [error, setError] = useState(null)
  const [cookieHint, setCookieHint] = useState(false)
  const [budgetPlan, setBudgetPlan] = useState(false)

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }
  function setPosBudget(pos, v) { setForm(f => ({ ...f, posBudget: { ...f.posBudget, [pos]: parseInt(v) || 0 } })) }

  const posBudgetTotal = Object.values(form.posBudget).reduce((a, b) => a + b, 0)

  async function connectWith(cfg, idx = null) {
    if (idx !== null) setLoadingIdx(idx); else setLoading(true)
    setError(null)
    try {
      const data = await api.getEspnDraftState(cfg.leagueId, cfg.espnS2, cfg.swid, cfg.season, cfg.mySlot, cfg.budget)
      saveLeague(cfg)
      onConnect(cfg, data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setLoadingIdx(null)
    }
  }

  async function handleConnect(e) {
    e.preventDefault()
    if (!form.leagueId || !form.espnS2 || !form.swid) {
      setError('League ID, espn_s2, and SWID are required.')
      return
    }
    connectWith(form)
  }

  return (
    <div className="rd-setup">
      <div className="rd-setup-card">
        <h2 className="rd-setup-title">ESPN Auction Draft Room</h2>
        <p className="rd-setup-sub">Connect to your ESPN auction league for real-time rankings, tier breaks, VOR, and budget tracking.</p>

        {leagues.length > 0 && (
          <div className="rd-saved-leagues">
            <div className="rd-saved-section-title">Saved Leagues</div>
            {leagues.map((lg, i) => (
              <div key={i} className="rd-saved-row">
                <div className="rd-saved-info">
                  <span className="rd-saved-name">{lg.name || `League ${lg.leagueId}`}</span>
                  <span className="rd-saved-meta">Season {lg.season} · Slot #{lg.mySlot} · ${lg.budget} budget</span>
                </div>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={loadingIdx === i}
                  onClick={() => connectWith(lg, i)}
                >
                  {loadingIdx === i ? '…' : 'Connect'}
                </button>
                <button
                  type="button"
                  className="rd-saved-delete"
                  onClick={() => onDeleteLeague(i)}
                  title="Remove saved league"
                >×</button>
              </div>
            ))}
            <div className="rd-saved-divider"><span>Or connect to a different league</span></div>
          </div>
        )}

        <form className="rd-setup-form" onSubmit={handleConnect}>
          <div className="rd-setup-row">
            <label className="rd-label" style={{ flex: 2 }}>League Name (optional)
              <input className="rd-input" type="text" placeholder="e.g. Main League" value={form.name} onChange={e => set('name', e.target.value)} />
            </label>
            <label className="rd-label" style={{ flex: 1 }}>Season
              <input className="rd-input" type="number" min="2020" max="2030" value={form.season} onChange={e => set('season', e.target.value)} />
            </label>
          </div>
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
            <label className="rd-label" style={{ flex: 1 }}>Budget ($)
              <input className="rd-input" type="number" min="1" max="10000" value={form.budget} onChange={e => set('budget', e.target.value)} />
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

          <button type="button" className="rd-cookie-toggle" onClick={() => setBudgetPlan(v => !v)}>
            Budget plan by position {budgetPlan ? '▲' : '▼'}
          </button>
          {budgetPlan && (
            <div className="rd-cookie-hint">
              <div className="rd-budget-plan-note">
                Target spend per position — Total: <strong style={{ color: posBudgetTotal === parseInt(form.budget) ? '#01d9ac' : '#e0a45c' }}>${posBudgetTotal}</strong> / ${form.budget}
              </div>
              <div className="rd-budget-plan-grid">
                {Object.entries(form.posBudget).map(([pos, val]) => (
                  <label key={pos} className="rd-budget-plan-item">
                    <span className="rd-budget-plan-pos" style={{ color: POS_COLORS[pos] || 'inherit' }}>{pos}</span>
                    <input
                      className="rd-input rd-budget-plan-input"
                      type="number" min="0" max={parseInt(form.budget)}
                      value={val}
                      onChange={e => setPosBudget(pos, e.target.value)}
                    />
                  </label>
                ))}
              </div>
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
  const [selectedId, setSelectedId] = useState(null)
  const [budget, setBudget] = useState(parseInt(config.budget) || 200)
  const [editingBudget, setEditingBudget] = useState(false)
  const [budgetInput, setBudgetInput] = useState(String(config.budget || 200))
  const [mySlot, setMySlot] = useState(parseInt(config.mySlot) || 1)
  const intervalRef = useRef(null)

  const isIdpTab = IDP_POSITIONS.includes(posTab)

  function saveBudget() {
    const val = parseInt(budgetInput)
    if (val > 0) {
      setBudget(val)
      const saved = (() => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') } catch { return {} } })()
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...saved, budget: String(val) }))
    }
    setEditingBudget(false)
  }

  function changeMyTeam(slot) {
    setMySlot(slot)
    const leagues = getSavedLeagues()
    const idx = leagues.findIndex(l => l.leagueId === config.leagueId && String(l.season) === String(config.season))
    if (idx >= 0) { leagues[idx].mySlot = String(slot); localStorage.setItem(LEAGUES_KEY, JSON.stringify(leagues)) }
  }

  const refresh = useCallback(async () => {
    try {
      const d = await api.getEspnDraftState(config.leagueId, config.espnS2, config.swid, config.season, mySlot, budget)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [config, mySlot, budget])

  useEffect(() => {
    intervalRef.current = setInterval(refresh, POLL_MS)
    return () => clearInterval(intervalRef.current)
  }, [refresh])

  const myTeam = (data.teams || []).find(t => t.is_me)
  const myPicks = myTeam?.players || []

  const posBudget = config.posBudget || DEFAULT_POS_BUDGET
  const posSpent = {}
  myPicks.forEach(p => {
    const pos = p.position || 'OTHER'
    posSpent[pos] = (posSpent[pos] || 0) + (p.bid_amount || 0)
  })

  const allAvailable = data.available || []
  const idpAvailable = data.idp_available || []

  const available = (isIdpTab
    ? idpAvailable.filter(p => p.position === posTab)
    : allAvailable.filter(p => posTab === 'ALL' || p.position === posTab)
  ).filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()))

  const budgetPct = data.budget > 0 ? Math.min(100, (data.my_budget_spent / data.budget) * 100) : 0
  const budgetColor = budgetPct > 85 ? '#e05c5c' : budgetPct > 60 ? '#e0a45c' : '#01d9ac'

  function getComparables(player) {
    if (!player) return []
    return allAvailable.filter(p =>
      p.sleeper_id !== player.sleeper_id &&
      p.position === player.position &&
      p.tier != null && player.tier != null &&
      Math.abs(p.tier - player.tier) <= 1
    ).slice(0, 4)
  }

  return (
    <div className="rd-board">
      <div className="rd-board-header">
        <div className="rd-board-status">
          {data.status === 'pre_draft' && <span className="rd-status-badge pre">Pre-Draft</span>}
          {data.status === 'drafting' && <span className="rd-status-badge live">LIVE</span>}
          {data.status === 'complete' && <span className="rd-status-badge done">Complete</span>}
          <span className="rd-board-picks">{data.picks_made}/{data.total_picks} picks</span>
        </div>
        {error && <span className="rd-poll-error">Poll error — retrying</span>}
        <button className="btn btn-secondary btn-sm" onClick={refresh}>Refresh</button>
      </div>

      <div className="rd-board-body">
        {/* Left: Available Players */}
        <div className="rd-available">
          <div className="rd-available-header">
            <div className="rd-pos-tabs">
              {ALL_POS_TABS.map(pos => (
                <button
                  key={pos}
                  className={`rd-pos-tab${posTab === pos ? ' active' : ''}`}
                  style={posTab === pos && pos !== 'ALL' ? { background: (POS_COLORS[pos] || '#8b90b0') + '22', color: POS_COLORS[pos] || '#8b90b0', borderColor: (POS_COLORS[pos] || '#8b90b0') + '88' } : {}}
                  onClick={() => { setPosTab(pos); setSelectedId(null) }}
                >
                  {pos}
                </button>
              ))}
            </div>
            <input
              className="rd-search"
              type="text"
              placeholder="Search player…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          {data.max_bid != null && (
            <div className="rd-max-bid-bar">
              Max bid: <strong>${data.max_bid}</strong>
              <span className="rd-max-bid-note">(${data.my_budget_remaining} left · {data.my_slots_remaining} slots to fill)</span>
            </div>
          )}

          <div className="rd-player-list">
            {isIdpTab ? (
              <>
                <div className="rd-player-header rd-player-header-idp">
                  <span>Pos</span>
                  <span>Player</span>
                </div>
                {available.length === 0 && <div className="rd-empty">No available IDP players.</div>}
                {available.map((p, i) => (
                  <div key={p.espn_id || i} className="rd-player-row rd-player-row-idp">
                    <PosPill pos={p.position} />
                    <span className="rd-player-name">{p.name}</span>
                  </div>
                ))}
              </>
            ) : (
              <>
                <div className="rd-player-header">
                  <span>Player</span>
                  <span className="rd-col-center">Rank</span>
                  <span className="rd-col-center">$ Est</span>
                  <span className="rd-col-center">VOR</span>
                  <span className="rd-col-center rd-col-val">Val</span>
                </div>
                {available.length === 0 && <div className="rd-empty">No available players matching filters.</div>}
                {available.map((p, i) => {
                  const prevTier = i > 0 ? available[i - 1].tier : p.tier
                  const tierBreak = i > 0 && p.tier !== prevTier
                  const pid = p.sleeper_id || p.name
                  const isSelected = selectedId === pid
                  const comparables = isSelected ? getComparables(p) : []
                  const tierClass = p.tier ? ` rd-row-tier-${Math.min(p.tier, 6)}` : ''
                  return (
                    <div key={pid || i}>
                      {tierBreak && <div className="rd-tier-break">— Tier {p.tier} —</div>}
                      <div
                        className={`rd-player-row${tierClass}${isSelected ? ' rd-player-row-selected' : ''}`}
                        onClick={() => setSelectedId(isSelected ? null : pid)}
                      >
                        <div className="rd-player-info">
                          <PosPill pos={p.position} />
                          <span className="rd-player-name">{p.name}</span>
                          <span className="rd-player-team">{p.nfl_team}</span>
                        </div>
                        <span className="rd-col-center rd-rank">{p.redraft_pos_rank ? `${p.position}${p.redraft_pos_rank}` : '—'}</span>
                        <AuctionChip value={p.auction_value} maxBid={data.max_bid} />
                        <VorChip vor={p.vor} />
                        <span className="rd-col-center rd-value rd-col-val">{p.redraft_value?.toLocaleString() ?? '—'}</span>
                      </div>
                      {isSelected && (
                        <div className="rd-expansion-block">
                          {comparables.length > 0 && (
                            <div className="rd-comparables-row">
                              <span className="rd-comparables-label">Similar on board:</span>
                              <div className="rd-comparables-chips">
                                {comparables.map((c, ci) => (
                                  <span key={ci} className="rd-comparable-chip">
                                    <PosPill pos={c.position} />
                                    <span>{c.name}</span>
                                    {c.auction_value != null && <span className="rd-bid-tag">${c.auction_value}</span>}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          <TeamNeeds player={p} teams={data.teams || []} rosterSlots={data.roster_slots} />
                        </div>
                      )}
                    </div>
                  )
                })}
              </>
            )}
          </div>
        </div>

        {/* Right: Sidebar */}
        <div className="rd-sidebar">
          {/* My Budget */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title">My Budget</div>
            <div className="rd-budget-numbers">
              <span className="rd-budget-remaining" style={{ color: budgetColor }}>${data.my_budget_remaining}</span>
              {editingBudget ? (
                <span className="rd-budget-edit-row">
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>of $</span>
                  <input
                    className="rd-budget-edit-input"
                    type="number" min="1" max="10000"
                    value={budgetInput}
                    onChange={e => setBudgetInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') saveBudget(); if (e.key === 'Escape') setEditingBudget(false) }}
                    autoFocus
                  />
                  <button className="rd-budget-edit-save" onClick={saveBudget}>✓</button>
                  <button className="rd-budget-edit-cancel" onClick={() => setEditingBudget(false)}>✕</button>
                </span>
              ) : (
                <span className="rd-budget-of" style={{ cursor: 'pointer' }} onClick={() => { setBudgetInput(String(budget)); setEditingBudget(true) }}>
                  of ${budget} ✎
                </span>
              )}
              <span className="rd-budget-spent">spent ${data.my_budget_spent}</span>
            </div>
            <div className="rd-budget-bar-track">
              <div className="rd-budget-bar-fill" style={{ width: `${budgetPct}%`, background: budgetColor }} />
            </div>
            {data.max_bid != null && (
              <div className="rd-max-bid-pill">Max bid: <strong>${data.max_bid}</strong></div>
            )}
          </div>

          {/* Per-position budget */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title">Budget by Position</div>
            <div className="rd-pos-budget-grid">
              <span className="rd-pbg-hdr">Pos</span>
              <span className="rd-pbg-hdr rd-pbg-right">Target</span>
              <span className="rd-pbg-hdr rd-pbg-right">Spent</span>
              <span className="rd-pbg-hdr rd-pbg-right">Left</span>
              {Object.entries(posBudget).map(([pos, target]) => {
                const spent = posSpent[pos] || 0
                const left = target - spent
                const overBudget = left < 0
                const nearBudget = !overBudget && left < target * 0.25
                return [
                  <span key={pos + '-p'} className="rd-pbg-pos" style={{ color: POS_COLORS[pos] || 'inherit' }}>{pos}</span>,
                  <span key={pos + '-t'} className="rd-pbg-right rd-pbg-num">${target}</span>,
                  <span key={pos + '-s'} className="rd-pbg-right rd-pbg-num">${spent}</span>,
                  <span key={pos + '-l'} className="rd-pbg-right rd-pbg-num" style={{ color: overBudget ? '#e05c5c' : nearBudget ? '#e0a45c' : 'inherit' }}>${left}</span>,
                ]
              })}
            </div>
          </div>

          {/* My Picks */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span>My Team ({myPicks.length} players)</span>
              <select
                className="rd-team-picker"
                value={mySlot}
                onChange={e => changeMyTeam(parseInt(e.target.value))}
                title="Change which team is yours"
              >
                {(data.teams || []).map(t => (
                  <option key={t.slot} value={t.slot}>{t.team_name}</option>
                ))}
              </select>
            </div>
            {myPicks.length === 0 ? (
              <div className="rd-empty-sm">No picks yet</div>
            ) : (
              <div className="rd-my-picks">
                {Object.keys(POS_COLORS).map(pos => {
                  const forPos = myPicks.filter(p => p.position === pos)
                  if (forPos.length === 0) return null
                  return (
                    <div key={pos} className="rd-my-pos-group">
                      <span className="rd-my-pos-label" style={{ color: POS_COLORS[pos] }}>{pos}</span>
                      <div className="rd-my-pos-players">
                        {forPos.map((p, i) => (
                          <span key={i} className="rd-my-chip">
                            {p.player_name}
                            {p.bid_amount > 0 && <span className="rd-bid-tag">${p.bid_amount}</span>}
                          </span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* All Teams Budget */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title">Team Budgets</div>
            <div className="rd-team-budgets">
              {(data.teams || []).map((t, i) => (
                <div key={i} className={`rd-team-budget-row${t.is_me ? ' me' : ''}`}>
                  <span className="rd-tbr-name">{t.team_name}</span>
                  <span className="rd-tbr-remaining" style={{ color: t.budget_remaining < 20 ? '#e05c5c' : t.budget_remaining < 50 ? '#e0a45c' : 'inherit' }}>
                    ${t.budget_remaining}
                  </span>
                  <div className="rd-tbr-bar-track">
                    <div className="rd-tbr-bar-fill" style={{ width: `${Math.min(100, (t.budget_spent / data.budget) * 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Picks */}
          <div className="rd-sidebar-section">
            <div className="rd-sidebar-title">Recent Picks</div>
            {(data.recent_picks || []).length === 0 ? (
              <div className="rd-empty-sm">No picks yet</div>
            ) : (
              <div className="rd-recent-list">
                {(data.recent_picks || []).map((pk, i) => (
                  <div key={i} className="rd-recent-row">
                    {pk.bid_amount > 0 && <span className="rd-recent-bid">${pk.bid_amount}</span>}
                    <PosPill pos={pk.position} />
                    <span className="rd-recent-name">
                      {pk.player_name}
                      {pk.is_keeper && <span className="rd-keeper-badge">K</span>}
                    </span>
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
  const [autoConnecting, setAutoConnecting] = useState(false)
  const [savedLeagues, setSavedLeagues] = useState(() => getSavedLeagues())

  // Auto-connect to most recently used league on first load
  useEffect(() => {
    const leagues = getSavedLeagues()
    if (!leagues.length) return
    const last = leagues[0]
    setAutoConnecting(true)
    api.getEspnDraftState(last.leagueId, last.espnS2, last.swid, last.season, last.mySlot, last.budget)
      .then(data => { setConfig(last); setInitialData(data) })
      .catch(() => {})  // silent — fall through to setup form
      .finally(() => setAutoConnecting(false))
  }, [])

  function handleConnect(cfg, data) {
    setSavedLeagues(getSavedLeagues())
    setConfig(cfg)
    setInitialData(data)
  }

  function handleDeleteLeague(idx) {
    const leagues = getSavedLeagues()
    leagues.splice(idx, 1)
    localStorage.setItem(LEAGUES_KEY, JSON.stringify(leagues))
    setSavedLeagues([...leagues])
  }

  if (autoConnecting) {
    return (
      <div className="rd-setup">
        <div className="rd-auto-connecting">
          <div className="rd-spinner" />
          Reconnecting to last league…
        </div>
      </div>
    )
  }

  if (!config || !initialData) {
    return <SetupForm onConnect={handleConnect} savedLeagues={savedLeagues} onDeleteLeague={handleDeleteLeague} />
  }

  return (
    <div>
      <div className="rd-topbar">
        <button className="btn btn-secondary btn-sm" onClick={() => { setConfig(null); setInitialData(null) }}>← Back</button>
        <span className="rd-topbar-title">
          ESPN Auction · {config.name || `League ${config.leagueId}`} · Season {config.season} · ${config.budget} budget
        </span>
      </div>
      <DraftBoard config={config} initialData={initialData} />
    </div>
  )
}
