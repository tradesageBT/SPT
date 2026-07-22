import { useEffect, useState, useRef, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'

const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }
const POS_TABS = ['ALL', 'QB', 'RB', 'WR', 'TE']
const POLL_MS = 5000

function getTargets(isStartup, numQbs) {
  if (isStartup) return { QB: numQbs >= 2 ? 3 : 2, RB: 6, WR: 6, TE: 2 }
  return { QB: numQbs >= 2 ? 2 : 1, RB: 2, WR: 2, TE: 1 }
}

function nextPickForSlot(startPickNum, mySlot, numTeams, totalPicks, isSnake) {
  for (let n = startPickNum; n <= totalPicks; n++) {
    const rnd = Math.floor((n - 1) / numTeams)
    const pos = (n - 1) % numTeams
    const slot = isSnake && rnd % 2 === 1 ? numTeams - pos : pos + 1
    if (slot === mySlot) return n
  }
  return null
}

function rankColor(rank, total) {
  const pct = rank / Math.max(total, 1)
  if (pct <= 0.25) return 'var(--accent)'
  if (pct <= 0.5)  return '#e0a45c'
  if (pct <= 0.75) return 'var(--text-muted)'
  return '#e05c5c'
}

// Returns { rosterId: { QB: {rank, val}, RB: ..., WR: ..., TE: ... } }
function computePosRanks(teams) {
  const teamPosVal = {}
  for (const team of teams) {
    const vals = { QB: 0, RB: 0, WR: 0, TE: 0 }
    for (const p of team.players) if (p.position in vals) vals[p.position] += p.fc_value
    teamPosVal[team.roster_id] = vals
  }
  const ranks = {}
  for (const pos of ['QB', 'RB', 'WR', 'TE']) {
    const sorted = [...teams].sort(
      (a, b) => (teamPosVal[b.roster_id]?.[pos] || 0) - (teamPosVal[a.roster_id]?.[pos] || 0)
    )
    sorted.forEach((team, i) => {
      ranks[team.roster_id] = ranks[team.roster_id] || {}
      ranks[team.roster_id][pos] = { rank: i + 1, val: teamPosVal[team.roster_id]?.[pos] || 0 }
    })
  }
  return ranks
}

export default function DraftRoom() {
  const { leagueId } = useParams()
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [posFilter, setPosFilter] = useState('ALL')
  const [showPicker, setShowPicker] = useState(false)
  const [myRosterId, setMyRosterId] = useState(() => {
    try { return JSON.parse(localStorage.getItem(`draft_me_${leagueId}`)) } catch { return null }
  })
  const intervalRef = useRef(null)

  function pickTeam(rosterId) {
    setMyRosterId(rosterId)
    localStorage.setItem(`draft_me_${leagueId}`, JSON.stringify(rosterId))
    setShowPicker(false)
    setPosFilter('YOU')
  }

  async function fetchDraft() {
    try {
      const data = await api.getDraftState(leagueId)
      setState(data)
      setError(null)
      if (data.status === 'complete') {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
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

  const myTeam = useMemo(() => {
    if (!state || myRosterId == null) return null
    return state.teams.find(t => t.roster_id === myRosterId) ?? null
  }, [state, myRosterId])

  const myCounts = useMemo(() => {
    const counts = { QB: 0, RB: 0, WR: 0, TE: 0 }
    if (myTeam) for (const p of myTeam.players) if (p.position in counts) counts[p.position]++
    return counts
  }, [myTeam])

  const targets = useMemo(
    () => getTargets(state?.is_startup ?? false, state?.num_qbs ?? 1),
    [state?.is_startup, state?.num_qbs],
  )

  const posRanks = useMemo(() => state ? computePosRanks(state.teams) : {}, [state?.teams])

  const isMyTurn = state && myRosterId != null && state.on_the_clock_roster === myRosterId

  const nextMyPick = useMemo(() => {
    if (!state || !myTeam?.slot) return null
    return nextPickForSlot(
      state.picks_made + 1, myTeam.slot, state.num_teams, state.total_picks, state.type === 'snake',
    )
  }, [state, myTeam?.slot])

  const picksUntilMine = nextMyPick != null ? nextMyPick - state.picks_made - 1 : null

  const displayList = useMemo(() => {
    if (!state || posFilter === 'LEAGUE') return []
    const list = state.available
    if (posFilter === 'YOU') {
      return [...list]
        .map(p => {
          const target = targets[p.position] || 0
          const need = target > 0
            ? Math.max(0, (target - (myCounts[p.position] || 0)) / target)
            : 0
          return { ...p, _score: p.fc_value * (1 + need * 1.5) }
        })
        .sort((a, b) => b._score - a._score)
        .slice(0, 100)
    }
    const filtered = posFilter === 'ALL' ? list : list.filter(p => p.position === posFilter)
    return filtered.slice(0, 100)
  }, [state?.available, posFilter, myCounts, targets])

  // League board sorted by total drafted value
  const leagueBoard = useMemo(() => {
    if (!state) return []
    return [...state.teams].sort((a, b) => {
      const totA = a.players.reduce((s, p) => s + p.fc_value, 0)
      const totB = b.players.reduce((s, p) => s + p.fc_value, 0)
      return totB - totA
    })
  }, [state?.teams])

  if (loading) return <LoadingSpinner message="Loading draft room…" />
  if (error) return (
    <div className="error-state">
      <p>❌ {error}</p>
      <Link to={`/league/${leagueId}`} className="btn btn-secondary" style={{ marginTop: '12px' }}>
        ← Back to League
      </Link>
    </div>
  )
  if (!state) return null

  const statusLabel = { drafting: 'Live', complete: 'Complete', pre_draft: 'Pre-Draft' }[state.status] ?? state.status
  const numTeams = state.num_teams

  return (
    <div className="draft-room">
      <div className="draft-room-header">
        <div>
          <h1 className="page-title">Draft Room</h1>
          <p className="page-sub">
            {state.picks_made} / {state.total_picks} picks ·{' '}
            <span className={`draft-status-badge draft-status-${state.status}`}>{statusLabel}</span>
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            className={`btn btn-sm ${myTeam ? 'btn-secondary' : 'btn-accent'}`}
            onClick={() => setShowPicker(true)}
          >
            {myTeam ? `👤 ${myTeam.team_name}` : '👤 Select My Team'}
          </button>
          <Link to={`/league/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
        </div>
      </div>

      {showPicker && (
        <div className="draft-picker-overlay" onClick={() => setShowPicker(false)}>
          <div className="draft-picker-modal" onClick={e => e.stopPropagation()}>
            <div className="draft-picker-title">Which team are you?</div>
            {state.teams.map(team => (
              <button
                key={team.roster_id}
                className={`draft-picker-row${myRosterId === team.roster_id ? ' selected' : ''}`}
                onClick={() => pickTeam(team.roster_id)}
              >
                {team.slot != null && <span className="draft-team-slot">#{team.slot}</span>}
                {team.team_name}
              </button>
            ))}
            <button className="btn btn-secondary btn-sm" style={{ marginTop: '10px', width: '100%' }} onClick={() => setShowPicker(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

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
        <div className="draft-available">
          <div className="draft-section-title">
            {posFilter === 'LEAGUE' ? 'League Positional Board' : 'Available Players'}
            {posFilter !== 'LEAGUE' && (
              <span className="draft-available-count">{state.available.length}</span>
            )}
          </div>

          <div className="draft-pos-filters">
            {myTeam && (
              <button
                className={`trade-filter-btn draft-you-tab${posFilter === 'YOU' ? ' active' : ''}`}
                onClick={() => setPosFilter('YOU')}
              >
                ★ Best for You
              </button>
            )}
            {POS_TABS.map(pos => (
              <button
                key={pos}
                className={`trade-filter-btn${posFilter === pos ? ' active' : ''}`}
                onClick={() => setPosFilter(pos)}
              >
                {pos}
              </button>
            ))}
            <button
              className={`trade-filter-btn${posFilter === 'LEAGUE' ? ' active' : ''}`}
              onClick={() => setPosFilter('LEAGUE')}
            >
              League
            </button>
          </div>

          {posFilter === 'LEAGUE' ? (
            <div className="draft-league-board">
              <div className="draft-board-header">
                <span>Team</span>
                <span style={{ color: POS_COLOR.QB }}>QB</span>
                <span style={{ color: POS_COLOR.RB }}>RB</span>
                <span style={{ color: POS_COLOR.WR }}>WR</span>
                <span style={{ color: POS_COLOR.TE }}>TE</span>
              </div>
              {leagueBoard.map(team => {
                const ranks = posRanks[team.roster_id] || {}
                const isMe = team.roster_id === myRosterId
                return (
                  <div key={team.roster_id} className={`draft-board-row${isMe ? ' mine' : ''}`}>
                    <span className="draft-board-team">
                      {team.slot != null && <span className="draft-team-slot">#{team.slot}</span>}
                      {team.team_name}
                    </span>
                    {['QB', 'RB', 'WR', 'TE'].map(pos => {
                      const r = ranks[pos]
                      return (
                        <span
                          key={pos}
                          className="draft-board-rank"
                          style={{ color: r ? rankColor(r.rank, numTeams) : 'var(--border)' }}
                        >
                          {r ? `#${r.rank}` : '—'}
                        </span>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="draft-player-list">
              {displayList.map((p, i) => (
                <div key={p.sleeper_id} className="draft-player-row">
                  {posFilter === 'YOU' && <span className="draft-rank">{i + 1}</span>}
                  <span className="draft-player-pos" style={{ color: POS_COLOR[p.position] || 'var(--text-muted)' }}>
                    {p.position}
                  </span>
                  <span className="draft-player-name">{p.name}</span>
                  <span className="draft-player-nfl">{p.nfl_team}</span>
                  <span className="draft-player-val">{p.fc_value.toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="draft-sidebar">
          {myTeam ? (
            <>
              <div className="draft-section-title">My Team</div>

              <div className="draft-my-needs">
                {['QB', 'RB', 'WR', 'TE'].map(pos => {
                  const count = myCounts[pos] || 0
                  const target = targets[pos] || 0
                  const done = count >= target
                  const pct = target > 0 ? Math.min(1, count / target) : 1
                  const rank = posRanks[myRosterId]?.[pos]?.rank
                  return (
                    <div key={pos} className="draft-need-row">
                      <span className="draft-need-pos" style={{ color: POS_COLOR[pos] }}>{pos}</span>
                      <div className="draft-need-bar-wrap">
                        <div
                          className="draft-need-bar"
                          style={{ width: `${pct * 100}%`, background: done ? 'var(--border)' : POS_COLOR[pos] }}
                        />
                      </div>
                      <span className={`draft-need-count${done ? ' done' : ''}`}>{count}/{target}</span>
                      {rank != null && (
                        <span className="draft-pos-rank" style={{ color: rankColor(rank, numTeams) }}>
                          #{rank}
                        </span>
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
                      <span className="draft-player-pos" style={{ color: POS_COLOR[p.position] || 'var(--text-muted)' }}>
                        {p.position}
                      </span>
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
              <button className="btn btn-accent btn-sm" onClick={() => setShowPicker(true)}>
                Select My Team
              </button>
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
                    <span className="draft-player-pos" style={{ color: POS_COLOR[pick.position] || 'var(--text-muted)' }}>
                      {pick.position}
                    </span>
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
