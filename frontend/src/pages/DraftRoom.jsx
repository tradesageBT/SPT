import { useEffect, useState, useRef, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'

const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }
const SUFFIXES = new Set(['Jr', 'Jr.', 'Sr', 'Sr.', 'II', 'III', 'IV'])
const POLL_MS = 5000

function getTargets(isStartup, numQbs) {
  if (isStartup) return { QB: numQbs >= 2 ? 3 : 2, RB: 6, WR: 6, TE: 2 }
  return { QB: numQbs >= 2 ? 2 : 1, RB: 2, WR: 2, TE: 1 }
}

function nextPickForSlot(start, mySlot, N, total, isSnake) {
  for (let n = start; n <= total; n++) {
    const rnd = Math.floor((n - 1) / N)
    const pos = (n - 1) % N
    const slot = isSnake && rnd % 2 === 1 ? N - pos : pos + 1
    if (slot === mySlot) return n
  }
  return null
}

function rankColor(rank, total) {
  const p = rank / Math.max(total, 1)
  if (p <= 0.25) return 'var(--accent)'
  if (p <= 0.5)  return '#e0a45c'
  if (p <= 0.75) return 'var(--text-muted)'
  return '#e05c5c'
}

function computePosRanks(teams) {
  const vals = {}
  for (const t of teams) {
    const v = { QB: 0, RB: 0, WR: 0, TE: 0 }
    for (const p of t.players) if (p.position in v) v[p.position] += p.fc_value
    vals[t.roster_id] = v
  }
  const ranks = {}
  for (const pos of ['QB', 'RB', 'WR', 'TE']) {
    const sorted = [...teams].sort((a, b) => (vals[b.roster_id]?.[pos] || 0) - (vals[a.roster_id]?.[pos] || 0))
    sorted.forEach((t, i) => {
      ranks[t.roster_id] = ranks[t.roster_id] || {}
      ranks[t.roster_id][pos] = { rank: i + 1, val: vals[t.roster_id]?.[pos] || 0 }
    })
  }
  return ranks
}

function calcOdds(team, targets) {
  const counts = { QB: 0, RB: 0, WR: 0, TE: 0 }
  for (const p of team.players) if (p.position in counts) counts[p.position]++
  const needs = {}
  let total = 0
  for (const pos of ['QB', 'RB', 'WR', 'TE']) {
    const n = Math.max(0, (targets[pos] || 0) - (counts[pos] || 0))
    needs[pos] = n
    total += n
  }
  if (total === 0) return { QB: 0.25, RB: 0.25, WR: 0.25, TE: 0.25 }
  return Object.fromEntries(Object.entries(needs).map(([pos, n]) => [pos, n / total]))
}

function lastName(name) {
  if (!name) return '?'
  const parts = name.split(' ')
  if (parts.length === 1) return parts[0]
  const last = parts[parts.length - 1]
  return SUFFIXES.has(last) && parts.length > 1 ? parts[parts.length - 2] : last
}

export default function DraftRoom() {
  const { leagueId } = useParams()
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [view, setView] = useState('ALL')
  const [search, setSearch] = useState('')
  const [showPicker, setShowPicker] = useState(false)
  const [expandedTeam, setExpandedTeam] = useState(null)
  const [myRosterId, setMyRosterId] = useState(() => {
    try { return JSON.parse(localStorage.getItem(`draft_me_${leagueId}`)) } catch { return null }
  })
  const [queue, setQueue] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem(`draft_queue_${leagueId}`)) || []) } catch { return new Set() }
  })
  const intervalRef = useRef(null)
  const gridRef = useRef(null)
  const wasMyTurnRef = useRef(false)

  // Request notification permission once on mount
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  function pickTeam(rosterId) {
    setMyRosterId(rosterId)
    localStorage.setItem(`draft_me_${leagueId}`, JSON.stringify(rosterId))
    setShowPicker(false)
    setView('YOU')
  }

  function toggleQueue(sleeperId) {
    setQueue(prev => {
      const next = new Set(prev)
      if (next.has(sleeperId)) next.delete(sleeperId)
      else next.add(sleeperId)
      localStorage.setItem(`draft_queue_${leagueId}`, JSON.stringify([...next]))
      return next
    })
  }

  async function fetchDraft() {
    try {
      const data = await api.getDraftState(leagueId)
      setState(data)
      setError(null)
      if (data.status === 'complete') { clearInterval(intervalRef.current); intervalRef.current = null }
    } catch (e) {
      setError(e?.message || 'Failed to load draft')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDraft()
    intervalRef.current = setInterval(fetchDraft, POLL_MS)
    return () => clearInterval(intervalRef.current)
  }, [leagueId])

  useEffect(() => {
    if (view === 'GRID' && gridRef.current) {
      const el = gridRef.current.querySelector('.draft-grid-cell.otc')
      if (el) el.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' })
    }
  }, [view, state?.picks_made])

  const myTeam = useMemo(() =>
    state && myRosterId != null ? (state.teams.find(t => t.roster_id === myRosterId) ?? null) : null,
    [state, myRosterId])

  const myCounts = useMemo(() => {
    const c = { QB: 0, RB: 0, WR: 0, TE: 0 }
    if (myTeam) for (const p of myTeam.players) if (p.position in c) c[p.position]++
    return c
  }, [myTeam])

  const targets = useMemo(
    () => getTargets(state?.is_startup ?? false, state?.num_qbs ?? 1),
    [state?.is_startup, state?.num_qbs])

  const posRanks = useMemo(() => state ? computePosRanks(state.teams) : {}, [state?.teams])
  const isMyTurn = !!(state && myRosterId != null && state.on_the_clock_roster === myRosterId)

  // Fire browser notification when OTC flips to the user
  useEffect(() => {
    if (isMyTurn && !wasMyTurnRef.current && state?.status === 'drafting') {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Your Pick!', {
          body: `You are on the clock — Pick #${state.picks_made + 1}`,
          tag: 'draft-otc',
        })
      }
    }
    wasMyTurnRef.current = isMyTurn
  }, [isMyTurn])

  const nextMyPick = useMemo(() => {
    if (!state || !myTeam?.slot) return null
    return nextPickForSlot(state.picks_made + 1, myTeam.slot, state.num_teams, state.total_picks, state.type === 'snake')
  }, [state, myTeam?.slot])

  const picksUntilMine = nextMyPick != null ? nextMyPick - state.picks_made - 1 : null

  // Available players sorted/filtered per view
  const baseList = useMemo(() => {
    if (!state) return []
    if (view === 'QUEUE') {
      return state.available
        .filter(p => queue.has(p.sleeper_id))
        .sort((a, b) => b.fc_value - a.fc_value)
    }
    if (view === 'YOU') {
      return [...state.available]
        .map(p => {
          const t = targets[p.position] || 0
          const need = t > 0 ? Math.max(0, (t - (myCounts[p.position] || 0)) / t) : 0
          return { ...p, _score: p.fc_value * (1 + need * 1.5) }
        })
        .sort((a, b) => b._score - a._score)
        .slice(0, 100)
    }
    const list = view === 'ALL' ? state.available : state.available.filter(p => p.position === view)
    return list.slice(0, 100)
  }, [state?.available, view, myCounts, targets, queue])

  // Apply search filter
  const searchFiltered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return baseList
    return baseList.filter(p => p.name.toLowerCase().includes(q))
  }, [baseList, search])

  // Insert tier breaks
  const tieredList = useMemo(() => {
    const PLAYER_VIEWS_ALL = ['ALL', 'QB', 'RB', 'WR', 'TE', 'YOU', 'QUEUE']
    if (!PLAYER_VIEWS_ALL.includes(view) || !searchFiltered.length) return []
    const result = []
    let tier = 1, rank = 0
    result.push({ _type: 'tier', label: `Tier ${tier}` })
    for (let i = 0; i < searchFiltered.length; i++) {
      result.push({ _type: 'player', _rank: ++rank, ...searchFiltered[i] })
      if (i < searchFiltered.length - 1) {
        const drop = searchFiltered[i].fc_value - searchFiltered[i + 1].fc_value
        if (drop > 250 && drop / Math.max(searchFiltered[i].fc_value, 1) > 0.12) {
          result.push({ _type: 'tier', label: `Tier ${++tier}` })
        }
      }
    }
    return result
  }, [searchFiltered, view])

  // All picks indexed by pick_no
  const allPicksMap = useMemo(() => {
    if (!state) return {}
    const m = {}
    for (const t of state.teams)
      for (const p of t.players)
        if (p.overall_pick) m[p.overall_pick] = { ...p, roster_id: t.roster_id, team_name: t.team_name }
    return m
  }, [state?.teams])

  // Snake grid: rows = rounds, cols = draft slots
  const draftGrid = useMemo(() => {
    if (!state) return []
    const isSnake = state.type === 'snake'
    const N = state.num_teams
    const mySlot = myTeam?.slot
    return Array.from({ length: state.num_rounds }, (_, r) => {
      const round = r + 1
      return {
        round,
        cells: Array.from({ length: N }, (_, s) => {
          const slot = s + 1
          const pickNo = isSnake && round % 2 === 0 ? (round - 1) * N + (N - slot + 1) : (round - 1) * N + slot
          const pick = allPicksMap[pickNo]
          return {
            pick_no: pickNo,
            slot,
            is_mine_slot: slot === mySlot,
            is_otc: pickNo === state.picks_made + 1 && state.status === 'drafting',
            is_my_pick: pick?.roster_id === myRosterId,
            player: pick || null,
          }
        }),
      }
    })
  }, [state, myTeam?.slot, myRosterId, allPicksMap])

  // Pick feed grouped by round
  const pickFeed = useMemo(() => {
    if (!state) return []
    const all = []
    for (const t of state.teams)
      for (const p of t.players)
        all.push({ ...p, roster_id: t.roster_id, team_name: t.team_name })
    all.sort((a, b) => (a.overall_pick || 0) - (b.overall_pick || 0))
    const byRound = {}
    const N = state.num_teams
    for (const p of all) {
      const rnd = Math.ceil((p.overall_pick || 1) / N)
      ;(byRound[rnd] = byRound[rnd] || []).push(p)
    }
    return Object.entries(byRound)
      .sort((a, b) => +a[0] - +b[0])
      .map(([rnd, picks]) => ({ round: +rnd, picks }))
  }, [state?.teams, state?.num_teams])

  const leagueBoard = useMemo(() => {
    if (!state) return []
    return [...state.teams].sort((a, b) =>
      b.players.reduce((s, p) => s + p.fc_value, 0) - a.players.reduce((s, p) => s + p.fc_value, 0))
  }, [state?.teams])

  if (loading) return <LoadingSpinner message="Loading draft room…" />
  if (error) return (
    <div className="error-state">
      <p>❌ {error}</p>
      <Link to={`/league/${leagueId}`} className="btn btn-secondary" style={{ marginTop: '12px' }}>← Back to League</Link>
    </div>
  )
  if (!state) return null

  const statusLabel = { drafting: 'Live', complete: 'Complete', pre_draft: 'Pre-Draft' }[state.status] ?? state.status
  const N = state.num_teams
  const PLAYER_VIEWS = ['ALL', 'QB', 'RB', 'WR', 'TE']
  const isPlayerView = PLAYER_VIEWS.includes(view) || view === 'YOU' || view === 'QUEUE'

  return (
    <div className="draft-room">
      {/* Header */}
      <div className="draft-room-header">
        <div>
          <h1 className="page-title">Draft Room</h1>
          <p className="page-sub">
            {state.picks_made} / {state.total_picks} picks ·{' '}
            <span className={`draft-status-badge draft-status-${state.status}`}>{statusLabel}</span>
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button className={`btn btn-sm ${myTeam ? 'btn-secondary' : 'btn-accent'}`} onClick={() => setShowPicker(true)}>
            {myTeam ? `👤 ${myTeam.team_name}` : '👤 Select My Team'}
          </button>
          <Link to={`/league/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
        </div>
      </div>

      {/* Team picker */}
      {showPicker && (
        <div className="draft-picker-overlay" onClick={() => setShowPicker(false)}>
          <div className="draft-picker-modal" onClick={e => e.stopPropagation()}>
            <div className="draft-picker-title">Which team are you?</div>
            {state.teams.map(team => (
              <button key={team.roster_id}
                className={`draft-picker-row${myRosterId === team.roster_id ? ' selected' : ''}`}
                onClick={() => pickTeam(team.roster_id)}>
                {team.slot != null && <span className="draft-team-slot">#{team.slot}</span>}
                {team.team_name}
              </button>
            ))}
            <button className="btn btn-secondary btn-sm" style={{ marginTop: '10px', width: '100%' }} onClick={() => setShowPicker(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* OTC banners */}
      {state.status === 'drafting' && isMyTurn && (
        <div className="draft-otc-banner draft-otc-mine">
          <span className="draft-otc-label">Your Pick!</span>
          <span className="draft-otc-team">You're on the clock</span>
          <span className="draft-otc-pick">Pick #{state.picks_made + 1}</span>
        </div>
      )}
      {state.status === 'drafting' && !isMyTurn && state.on_the_clock_team && (
        <div className="draft-otc-banner">
          <span className="draft-otc-label">On the Clock</span>
          <span className="draft-otc-team">{state.on_the_clock_team}</span>
          <span className="draft-otc-pick">
            Pick #{state.picks_made + 1}
            {picksUntilMine != null && picksUntilMine > 0 && (
              <span className="draft-otc-countdown"> · {picksUntilMine} pick{picksUntilMine !== 1 ? 's' : ''} until yours</span>
            )}
          </span>
        </div>
      )}

      <div className="draft-room-body">
        {/* Left panel */}
        <div className="draft-available">
          <div className="draft-section-title">
            {view === 'LEAGUE' ? 'League Board' : view === 'GRID' ? 'Draft Grid' : view === 'FEED' ? 'Pick Feed' : 'Available Players'}
            {isPlayerView && <span className="draft-available-count">{state.available.length}</span>}
          </div>

          <div className="draft-pos-filters">
            {myTeam && (
              <button className={`trade-filter-btn draft-you-tab${view === 'YOU' ? ' active' : ''}`} onClick={() => setView('YOU')}>
                ★ You
              </button>
            )}
            <button className={`trade-filter-btn draft-queue-tab${view === 'QUEUE' ? ' active' : ''}`} onClick={() => setView('QUEUE')}>
              ☆ Queue{queue.size > 0 && ` (${queue.size})`}
            </button>
            {PLAYER_VIEWS.map(v => (
              <button key={v} className={`trade-filter-btn${view === v ? ' active' : ''}`} onClick={() => setView(v)}>{v}</button>
            ))}
            <span className="draft-filter-sep" />
            {[['LEAGUE', 'Board'], ['GRID', 'Grid'], ['FEED', 'Feed']].map(([v, label]) => (
              <button key={v} className={`trade-filter-btn${view === v ? ' active' : ''}`} onClick={() => setView(v)}>{label}</button>
            ))}
          </div>

          {/* Search bar for player views */}
          {isPlayerView && (
            <div className="draft-search-wrap">
              <input
                className="draft-search"
                type="text"
                placeholder="Search players…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              {search && (
                <button className="draft-search-clear" onClick={() => setSearch('')}>✕</button>
              )}
            </div>
          )}

          {/* Available players with tier breaks */}
          {isPlayerView && (
            <div className="draft-player-list">
              {tieredList.length === 0
                ? <p className="draft-empty">{view === 'QUEUE' ? 'No players queued' : 'No players found'}</p>
                : tieredList.map((item, i) =>
                  item._type === 'tier' ? (
                    <div key={`t${i}`} className="draft-tier-break"><span>{item.label}</span></div>
                  ) : (
                    <div key={item.sleeper_id} className="draft-player-row">
                      {view === 'YOU' && <span className="draft-rank">{item._rank}</span>}
                      <span className="draft-player-pos" style={{ color: POS_COLOR[item.position] || 'var(--text-muted)' }}>{item.position}</span>
                      <span className="draft-player-name">{item.name}</span>
                      <span className="draft-player-nfl">{item.nfl_team}</span>
                      <span className="draft-player-val">{item.fc_value.toLocaleString()}</span>
                      <button
                        className={`draft-queue-btn${queue.has(item.sleeper_id) ? ' queued' : ''}`}
                        onClick={e => { e.stopPropagation(); toggleQueue(item.sleeper_id) }}
                        title={queue.has(item.sleeper_id) ? 'Remove from queue' : 'Add to queue'}
                      >
                        {queue.has(item.sleeper_id) ? '★' : '☆'}
                      </button>
                    </div>
                  )
                )
              }
            </div>
          )}

          {/* League board with team inspector */}
          {view === 'LEAGUE' && (
            <div className="draft-league-board">
              <div className="draft-board-header">
                <span>Team</span>
                {['QB', 'RB', 'WR', 'TE'].map(pos => (
                  <span key={pos} style={{ color: POS_COLOR[pos] }}>{pos}</span>
                ))}
              </div>
              {leagueBoard.map(team => {
                const ranks = posRanks[team.roster_id] || {}
                const isMe = team.roster_id === myRosterId
                const isOpen = expandedTeam === team.roster_id
                const odds = calcOdds(team, targets)
                return (
                  <div key={team.roster_id}>
                    <div
                      className={`draft-board-row${isMe ? ' mine' : ''} clickable`}
                      onClick={() => setExpandedTeam(isOpen ? null : team.roster_id)}
                    >
                      <span className="draft-board-team">
                        {team.slot != null && <span className="draft-team-slot">#{team.slot}</span>}
                        {team.team_name}
                        <span className="draft-board-expand">{isOpen ? '▲' : '▼'}</span>
                      </span>
                      {['QB', 'RB', 'WR', 'TE'].map(pos => {
                        const r = ranks[pos]
                        return (
                          <span key={pos} className="draft-board-rank"
                            style={{ color: r ? rankColor(r.rank, N) : 'var(--border)' }}>
                            {r ? `#${r.rank}` : '—'}
                          </span>
                        )
                      })}
                    </div>

                    {isOpen && (
                      <div className="draft-team-inspector">
                        <div className="draft-inspector-cols">
                          <div className="draft-inspector-section">
                            <div className="draft-inspector-label">Picks so far</div>
                            {team.players.length === 0
                              ? <p className="draft-empty">No picks yet</p>
                              : ['QB', 'RB', 'WR', 'TE'].map(pos => {
                                const pp = team.players.filter(p => p.position === pos)
                                if (!pp.length) return null
                                return (
                                  <div key={pos} className="draft-inspector-pos-group">
                                    <span className="draft-inspector-pos" style={{ color: POS_COLOR[pos] }}>{pos}</span>
                                    <div className="draft-inspector-players">
                                      {pp.map(p => (
                                        <span key={p.sleeper_id} className="draft-inspector-player">
                                          {p.name}
                                          <span className="draft-inspector-pick-no">#{p.overall_pick}</span>
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )
                              })
                            }
                          </div>
                          <div className="draft-inspector-section">
                            <div className="draft-inspector-label">Likely next pick</div>
                            <div className="draft-odds-rows">
                              {['QB', 'RB', 'WR', 'TE'].map(pos => (
                                <div key={pos} className="draft-odds-row">
                                  <span className="draft-odds-pos" style={{ color: POS_COLOR[pos] }}>{pos}</span>
                                  <div className="draft-odds-bar-wrap">
                                    <div className="draft-odds-bar" style={{ width: `${Math.round((odds[pos] || 0) * 100)}%`, background: POS_COLOR[pos] }} />
                                  </div>
                                  <span className="draft-odds-pct">{Math.round((odds[pos] || 0) * 100)}%</span>
                                </div>
                              ))}
                            </div>
                            <p className="draft-odds-note">Based on positional need vs. draft targets</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Draft grid */}
          {view === 'GRID' && (
            <div className="draft-grid-wrap" ref={gridRef}>
              <table className="draft-grid-table">
                <thead>
                  <tr>
                    <th className="draft-grid-rnd-hdr">Rd</th>
                    {Array.from({ length: N }, (_, i) => i + 1).map(slot => {
                      const team = state.teams.find(t => t.slot === slot)
                      const isMe = team?.roster_id === myRosterId
                      return (
                        <th key={slot} className={`draft-grid-team-hdr${isMe ? ' mine' : ''}`}>
                          {team ? lastName(team.team_name) : `#${slot}`}
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {draftGrid.map(({ round, cells }) => (
                    <tr key={round}>
                      <td className="draft-grid-rnd-lbl">R{round}</td>
                      {cells.map(cell => (
                        <td key={cell.slot} className={[
                          'draft-grid-cell',
                          cell.player ? 'picked' : 'empty',
                          cell.is_mine_slot ? 'my-slot' : '',
                          cell.is_otc ? 'otc' : '',
                          cell.is_my_pick ? 'my-pick' : '',
                        ].filter(Boolean).join(' ')}>
                          {cell.player ? (
                            <>
                              <span className="draft-grid-pos" style={{ color: POS_COLOR[cell.player.position] || 'var(--text-muted)' }}>
                                {cell.player.position}
                              </span>
                              <span className="draft-grid-name">{lastName(cell.player.name)}</span>
                            </>
                          ) : cell.is_otc ? (
                            <span className="draft-grid-otc">●</span>
                          ) : (
                            <span className="draft-grid-empty">{cell.pick_no}</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pick feed */}
          {view === 'FEED' && (
            <div className="draft-feed">
              {pickFeed.length === 0
                ? <p className="draft-empty">No picks yet</p>
                : pickFeed.map(({ round, picks }) => (
                  <div key={round} className="draft-feed-round">
                    <div className="draft-feed-rnd-label">Round {round}</div>
                    {picks.map(p => (
                      <div key={p.overall_pick} className={`draft-feed-row${p.roster_id === myRosterId ? ' mine' : ''}`}>
                        <span className="draft-feed-pick-no">#{p.overall_pick}</span>
                        <span className="draft-feed-team">{p.team_name}</span>
                        <span className="draft-player-pos" style={{ color: POS_COLOR[p.position] || 'var(--text-muted)' }}>{p.position}</span>
                        <span className="draft-player-name">{p.name}</span>
                        <span className="draft-player-nfl">{p.nfl_team}</span>
                      </div>
                    ))}
                  </div>
                ))
              }
            </div>
          )}
        </div>

        {/* Right sidebar */}
        <div className="draft-sidebar">
          {myTeam ? (
            <>
              <div className="draft-section-title">My Team</div>
              <div className="draft-my-needs">
                {['QB', 'RB', 'WR', 'TE'].map(pos => {
                  const count = myCounts[pos] || 0
                  const target = targets[pos] || 0
                  const done = count >= target
                  const rank = posRanks[myRosterId]?.[pos]?.rank
                  return (
                    <div key={pos} className="draft-need-row">
                      <span className="draft-need-pos" style={{ color: POS_COLOR[pos] }}>{pos}</span>
                      <div className="draft-need-bar-wrap">
                        <div className="draft-need-bar" style={{
                          width: `${target > 0 ? Math.min(1, count / target) * 100 : 100}%`,
                          background: done ? 'var(--border)' : POS_COLOR[pos],
                        }} />
                      </div>
                      <span className={`draft-need-count${done ? ' done' : ''}`}>{done ? count : `${count}/${target}`}</span>
                      {rank != null && (
                        <span className="draft-pos-rank" style={{ color: rankColor(rank, N) }}>#{rank}</span>
                      )}
                    </div>
                  )
                })}
              </div>
              <div className="draft-my-picks">
                {myTeam.players.length === 0
                  ? <p className="draft-empty">No picks yet</p>
                  : myTeam.players.map(p => (
                    <div key={p.sleeper_id} className="draft-my-pick-row">
                      <span className="draft-player-pos" style={{ color: POS_COLOR[p.position] || 'var(--text-muted)' }}>{p.position}</span>
                      <span className="draft-my-pick-name">{p.name}</span>
                      <span className="draft-my-pick-num">#{p.overall_pick}</span>
                    </div>
                  ))
                }
              </div>
              <div className="draft-sidebar-divider" />
            </>
          ) : (
            <div className="draft-setup-prompt">
              <div className="draft-setup-icon">👤</div>
              <p className="draft-setup-text">Select your team for personalized recommendations and pick countdowns</p>
              <button className="btn btn-accent btn-sm" onClick={() => setShowPicker(true)}>Select My Team</button>
            </div>
          )}

          <div className="draft-section-title">Recent Picks</div>
          <div className="draft-recent-list">
            {state.recent_picks.length === 0
              ? <p className="draft-empty">No picks yet</p>
              : state.recent_picks.map((pick, i) => (
                <div key={i} className={`draft-recent-row${pick.roster_id === myRosterId ? ' mine' : ''}`}>
                  <div className="draft-recent-meta">
                    <span className="draft-recent-pick-num">#{pick.overall_pick}</span>
                    <span className="draft-recent-team-name">{pick.team_name}</span>
                  </div>
                  <div className="draft-recent-player">
                    <span className="draft-player-pos" style={{ color: POS_COLOR[pick.position] || 'var(--text-muted)' }}>{pick.position}</span>
                    <span className="draft-player-name">{pick.player_name}</span>
                    <span className="draft-player-nfl">{pick.nfl_team}</span>
                  </div>
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </div>
  )
}
