import { useEffect, useState, useMemo, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'

const ROUND_LABEL = { 1: '1st', 2: '2nd', 3: '3rd', 4: '4th' }
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c', PK: '#888' }
const fmt = (n) => n?.toLocaleString() ?? '—'
const fmtDelta = (n) => (n >= 0 ? '+' : '') + n?.toLocaleString()

function pickUid(pick) {
  return `pick_${pick.season}_${pick.round}_${pick.original_roster_id}`
}

function pickAsset(pick) {
  const label = ROUND_LABEL[pick.round] ?? `Rd ${pick.round}`
  const slot = pick.projected_slot ? ` (~${pick.projected_slot})` : ''
  const from = !pick.own_pick ? ` · ${pick.original_owner_name}` : ''
  return {
    sleeper_id: pickUid(pick),
    name: `${pick.season} ${label}${slot}${from}`,
    position: 'PK',
    fc_value: pick.fc_value || 0,
  }
}

function PlayerSearch({ leaguePlayers, addedIds, onAdd }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef(null)

  const suggestions = useMemo(() => {
    if (!query.trim()) return []
    const q = query.toLowerCase()
    return leaguePlayers
      .filter((p) => !addedIds.has(p.sleeper_id) && p.name.toLowerCase().includes(q))
      .slice(0, 8)
  }, [query, leaguePlayers, addedIds])

  function handleSelect(player) {
    onAdd(
      { sleeper_id: player.sleeper_id, name: player.name, position: player.position, fc_value: player.fc_value },
      player.roster_id,
      player.display_name,
    )
    setQuery('')
    setOpen(false)
    inputRef.current?.focus()
  }

  return (
    <div className="eval-search-wrap">
      <input
        ref={inputRef}
        className="eval-search-input"
        placeholder="Search player by name…"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && suggestions.length > 0 && (
        <div className="eval-search-dropdown">
          {suggestions.map((p) => (
            <button key={p.sleeper_id} className="eval-suggestion" onMouseDown={() => handleSelect(p)}>
              <span className="eval-sug-pos" style={{ background: POS_COLOR[p.position] || '#666' }}>
                {p.position}
              </span>
              <span className="eval-sug-name">{p.name}</span>
              <span className="eval-sug-team">{p.display_name}</span>
              <span className="eval-sug-val">{fmt(p.fc_value)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function SidePanel({ label, assets, teamContext, onAdd, onRemove, leaguePlayers, teamsData }) {
  const [pickOpen, setPickOpen] = useState(false)
  const addedIds = useMemo(() => new Set(assets.map((a) => a.sleeper_id)), [assets])

  const teamPicks = useMemo(() => {
    if (!teamContext) return []
    const team = teamsData.find((t) => t.roster_id === teamContext.roster_id)
    return team?.roster_data?.picks || []
  }, [teamContext, teamsData])

  const availablePicks = teamPicks.filter((p) => !addedIds.has(pickUid(p)))
  const total = assets.reduce((s, a) => s + (a.fc_value || 0), 0)

  return (
    <div className="eval-side">
      <div className="eval-side-header">
        <span className="eval-side-label">{label}</span>
        {teamContext && <span className="eval-side-team">{teamContext.display_name}</span>}
      </div>

      <PlayerSearch leaguePlayers={leaguePlayers} addedIds={addedIds} onAdd={onAdd} />

      {teamContext && availablePicks.length > 0 && (
        <div className="eval-pick-wrap">
          <button className="eval-add-pick-btn" onClick={() => setPickOpen((v) => !v)}>
            + Add Pick {pickOpen ? '▲' : '▼'}
          </button>
          {pickOpen && (
            <div className="eval-pick-dropdown">
              {availablePicks.map((p, i) => (
                <button
                  key={i}
                  className="eval-pick-option"
                  onClick={() => { onAdd(pickAsset(p), null, null); setPickOpen(false) }}
                >
                  <span className="eval-pick-label">
                    {p.season} {ROUND_LABEL[p.round] ?? `Rd ${p.round}`}
                    {p.projected_slot && ` (~${p.projected_slot})`}
                    {!p.own_pick && ` · from ${p.original_owner_name}`}
                  </span>
                  <span className="eval-pick-val">{fmt(p.fc_value)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="eval-assets">
        {assets.length === 0
          ? <div className="eval-empty-side">No assets added yet</div>
          : assets.map((a) => (
            <div key={a.sleeper_id} className="eval-asset-chip">
              <span className="eval-chip-pos" style={{ background: POS_COLOR[a.position] || '#666' }}>
                {a.position}
              </span>
              <span className="eval-chip-name">{a.name}</span>
              <span className="eval-chip-val">{fmt(a.fc_value)}</span>
              <button className="eval-chip-remove" onClick={() => onRemove(a.sleeper_id)}>✕</button>
            </div>
          ))
        }
      </div>

      {assets.length > 0 && (
        <div className="eval-side-total">Total: <strong>{fmt(total)}</strong></div>
      )}
    </div>
  )
}

const CONTENTION_BLURB = {
  'Championship Window': 'in their Championship Window — adding proven production fits',
  'Sustainable Contender': 'a Sustainable Contender — balancing present and future',
  'Win-Now Push': 'making a Win-Now Push — proven starters are the goal',
  'Ascending': 'Ascending — adding young talent accelerates the build',
  'Treading Water': 'Treading Water — direction of this trade matters',
  'Full Rebuild': 'in a Full Rebuild — picks and youth are ideal here',
  'Retooling': 'Retooling — young assets fit the timeline',
  'Fire Sale': 'in Fire Sale mode — moving veterans for future capital makes sense',
}

function posContext(receivedAssets, posRank, teamName, n) {
  if (!n) return []
  const positions = [...new Set(receivedAssets.filter((a) => a.position !== 'PK').map((a) => a.position))]
  return positions.flatMap((pos) => {
    const rank = posRank?.[pos]
    if (!rank) return []
    const third = Math.ceil(n / 3)
    const tier = rank <= third ? 'strength' : rank > n - third ? 'need' : 'depth'
    const suffix =
      tier === 'need' ? `fills a need (ranked #${rank} of ${n})`
      : tier === 'strength' ? `already a strength (ranked #${rank} of ${n})`
      : `adds depth (ranked #${rank} of ${n})`
    return [`${teamName} receives ${pos} — ${suffix}`]
  })
}

function AnalysisPanel({ analysis, sideA, sideB }) {
  const {
    value_a_gives, value_b_gives, value_delta,
    lineup_delta_a, lineup_delta_b, breakdown_a, breakdown_b,
    avg_age_a_gives, avg_age_b_gives,
    team_a_name, team_b_name,
    contention_a, contention_b,
    positional_rank_a, positional_rank_b,
    num_teams, is_win_win, winner,
  } = analysis

  const fairness = value_delta < 200 ? 'Fair ✓' : value_delta < 500 ? 'Close ~' : 'Lopsided ⚠'
  const fairnessClass = value_delta < 200 ? 'fair' : value_delta < 500 ? 'close' : 'lopsided'

  const verdictText = is_win_win
    ? 'Win-Win'
    : winner === 'a' ? `${team_a_name} Wins`
    : winner === 'b' ? `${team_b_name} Wins`
    : 'About Even'
  const verdictClass = is_win_win ? 'verdict-winwin'
    : winner === 'even' ? 'verdict-even'
    : 'verdict-winner'

  // Age context
  let ageNote = null
  if (avg_age_a_gives != null && avg_age_b_gives != null) {
    const diff = avg_age_b_gives - avg_age_a_gives
    if (Math.abs(diff) >= 0.5) {
      const younger = diff > 0 ? team_a_name : team_b_name
      ageNote = `${younger} receives assets ${Math.abs(diff).toFixed(1)} yrs younger on average`
    }
  }

  const posA = posContext(sideB, positional_rank_a, team_a_name, num_teams)
  const posB = posContext(sideA, positional_rank_b, team_b_name, num_teams)

  const contextLines = [
    ageNote,
    ...posA,
    ...posB,
    contention_a && CONTENTION_BLURB[contention_a] ? `${team_a_name} is ${CONTENTION_BLURB[contention_a]}` : null,
    contention_b && CONTENTION_BLURB[contention_b] ? `${team_b_name} is ${CONTENTION_BLURB[contention_b]}` : null,
  ].filter(Boolean)

  return (
    <div className="eval-analysis">
      <div className={`eval-verdict ${verdictClass}`}>
        {is_win_win && <span className="eval-verdict-icon">🤝 </span>}
        {verdictText}
      </div>

      <div className="eval-metrics">
        <div className="eval-metric-block">
          <div className="eval-metric-header">
            <span className="eval-metric-label">Asset Value</span>
            <span className={`eval-fairness eval-fairness-${fairnessClass}`}>Δ {fmt(value_delta)} — {fairness}</span>
          </div>
          <div className="eval-metric-sides">
            <div className="eval-metric-team">
              <span className="eval-metric-team-name">{team_a_name}</span>
              <span className="eval-metric-val">{fmt(value_a_gives)}</span>
            </div>
            <div className="eval-metric-team eval-metric-team-right">
              <span className="eval-metric-team-name">{team_b_name}</span>
              <span className="eval-metric-val">{fmt(value_b_gives)}</span>
            </div>
          </div>
        </div>

        <div className="eval-metric-block">
          <div className="eval-metric-header">
            <span className="eval-metric-label">Lineup Impact</span>
          </div>
          <div className="eval-metric-sides">
            <div className="eval-metric-team">
              <span className="eval-metric-team-name">{team_a_name}</span>
              <span className={lineup_delta_a > 0 ? 'eval-pos' : lineup_delta_a < 0 ? 'eval-neg' : 'eval-neu'}>
                {lineup_delta_a > 0 ? '▲' : lineup_delta_a < 0 ? '▼' : '~'} {fmtDelta(lineup_delta_a)}
              </span>
            </div>
            <div className="eval-metric-team eval-metric-team-right">
              <span className="eval-metric-team-name">{team_b_name}</span>
              <span className={lineup_delta_b > 0 ? 'eval-pos' : lineup_delta_b < 0 ? 'eval-neg' : 'eval-neu'}>
                {lineup_delta_b > 0 ? '▲' : lineup_delta_b < 0 ? '▼' : '~'} {fmtDelta(lineup_delta_b)}
              </span>
            </div>
          </div>
          {(Math.abs(breakdown_a.starters_lost) >= 50 || Math.abs(breakdown_a.starters_gained) >= 50 ||
            Math.abs(breakdown_b.starters_lost) >= 50 || Math.abs(breakdown_b.starters_gained) >= 50) && (
            <div className="eval-breakdown-row">
              <div className="eval-breakdown-side">
                {Math.abs(breakdown_a.starters_gained - breakdown_a.starters_lost) >= 50 && (
                  <span className={(breakdown_a.starters_gained - breakdown_a.starters_lost) > 0 ? 'eval-pos' : 'eval-neg'}>
                    Starter quality {fmtDelta(breakdown_a.starters_gained - breakdown_a.starters_lost)}
                  </span>
                )}
                {Math.abs(breakdown_a.bench_gained - breakdown_a.bench_lost) >= 50 && (
                  <span className={(breakdown_a.bench_gained - breakdown_a.bench_lost) > 0 ? 'eval-pos' : 'eval-neg'}>
                    Bench {fmtDelta(breakdown_a.bench_gained - breakdown_a.bench_lost)}
                  </span>
                )}
              </div>
              <div className="eval-breakdown-side eval-breakdown-side-right">
                {Math.abs(breakdown_b.starters_gained - breakdown_b.starters_lost) >= 50 && (
                  <span className={(breakdown_b.starters_gained - breakdown_b.starters_lost) > 0 ? 'eval-pos' : 'eval-neg'}>
                    Starter quality {fmtDelta(breakdown_b.starters_gained - breakdown_b.starters_lost)}
                  </span>
                )}
                {Math.abs(breakdown_b.bench_gained - breakdown_b.bench_lost) >= 50 && (
                  <span className={(breakdown_b.bench_gained - breakdown_b.bench_lost) > 0 ? 'eval-pos' : 'eval-neg'}>
                    Bench {fmtDelta(breakdown_b.bench_gained - breakdown_b.bench_lost)}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {(avg_age_a_gives != null || avg_age_b_gives != null) && (
          <div className="eval-metric-block">
            <div className="eval-metric-header">
              <span className="eval-metric-label">Avg Age Given</span>
            </div>
            <div className="eval-metric-sides">
              <div className="eval-metric-team">
                <span className="eval-metric-team-name">{team_a_name}</span>
                <span>{avg_age_a_gives != null ? `${avg_age_a_gives} yrs` : '—'}</span>
              </div>
              <div className="eval-metric-team eval-metric-team-right">
                <span className="eval-metric-team-name">{team_b_name}</span>
                <span>{avg_age_b_gives != null ? `${avg_age_b_gives} yrs` : '—'}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {contextLines.length > 0 && (
        <div className="eval-context">
          {contextLines.map((line, i) => (
            <div key={i} className="eval-context-line">• {line}</div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function TradeEvaluator() {
  const { leagueId } = useParams()
  const [leaguePlayers, setLeaguePlayers] = useState([])
  const [teamsData, setTeamsData] = useState([])
  const [sideA, setSideA] = useState([])
  const [sideB, setSideB] = useState([])
  const [teamA, setTeamA] = useState(null)
  const [teamB, setTeamB] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [evalLoading, setEvalLoading] = useState(false)

  useEffect(() => {
    api.getLeaguePlayers(leagueId).then(setLeaguePlayers).catch(() => {})
    api.getLeague(leagueId).then((d) => setTeamsData(d.teams || [])).catch(() => {})
  }, [leagueId])

  // Re-evaluate whenever sides or teams change
  useEffect(() => {
    if (!teamA || !teamB || sideA.length === 0 || sideB.length === 0) {
      setAnalysis(null)
      return
    }
    setEvalLoading(true)
    api.evaluateTrade(leagueId, {
      a_roster_id: teamA.roster_id,
      b_roster_id: teamB.roster_id,
      a_gives: sideA,
      b_gives: sideB,
    })
      .then(setAnalysis)
      .catch(() => setAnalysis(null))
      .finally(() => setEvalLoading(false))
  }, [leagueId, teamA?.roster_id, teamB?.roster_id, sideA, sideB])

  function handleAddA(asset, rosterId, displayName) {
    setSideA((prev) => prev.some((a) => a.sleeper_id === asset.sleeper_id) ? prev : [...prev, asset])
    if (!teamA && rosterId) setTeamA({ roster_id: rosterId, display_name: displayName || `Team ${rosterId}` })
  }

  function handleAddB(asset, rosterId, displayName) {
    setSideB((prev) => prev.some((a) => a.sleeper_id === asset.sleeper_id) ? prev : [...prev, asset])
    if (!teamB && rosterId) setTeamB({ roster_id: rosterId, display_name: displayName || `Team ${rosterId}` })
  }

  function handleRemoveA(sleeperId) {
    setSideA((prev) => {
      const next = prev.filter((a) => a.sleeper_id !== sleeperId)
      if (next.length === 0) setTeamA(null)
      return next
    })
  }

  function handleRemoveB(sleeperId) {
    setSideB((prev) => {
      const next = prev.filter((a) => a.sleeper_id !== sleeperId)
      if (next.length === 0) setTeamB(null)
      return next
    })
  }

  function clearAll() {
    setSideA([]); setSideB([])
    setTeamA(null); setTeamB(null)
    setAnalysis(null)
  }

  const ready = teamA && teamB && sideA.length > 0 && sideB.length > 0

  return (
    <div className="eval-page">
      <div className="profile-nav">
        <Link to={`/league/${leagueId}`} className="back-link">← League</Link>
        <Link to={`/league/${leagueId}/trades`} className="back-link">Trade Ideas</Link>
        {(sideA.length > 0 || sideB.length > 0) && (
          <button className="btn btn-sm" style={{ marginLeft: 'auto' }} onClick={clearAll}>Clear All</button>
        )}
      </div>

      <h1 className="page-title">Trade Evaluator</h1>
      <p className="page-sub">Search any player by name — their team populates automatically.</p>

      <div className="eval-builder">
        <SidePanel
          label="Side A gives"
          assets={sideA}
          teamContext={teamA}
          onAdd={handleAddA}
          onRemove={handleRemoveA}
          leaguePlayers={leaguePlayers}
          teamsData={teamsData}
        />

        <div className="eval-divider">⇄</div>

        <SidePanel
          label="Side B gives"
          assets={sideB}
          teamContext={teamB}
          onAdd={handleAddB}
          onRemove={handleRemoveB}
          leaguePlayers={leaguePlayers}
          teamsData={teamsData}
        />
      </div>

      {!ready && sideA.length === 0 && sideB.length === 0 && (
        <p className="eval-placeholder">Add players to both sides to see the full analysis.</p>
      )}

      {evalLoading && <p className="eval-placeholder">Evaluating…</p>}

      {!evalLoading && analysis && (
        <AnalysisPanel analysis={analysis} sideA={sideA} sideB={sideB} />
      )}
    </div>
  )
}
