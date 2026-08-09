import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import PositionalBreakdown from '../components/PositionalBreakdown'
import PlayerTable from '../components/PlayerTable'
import ContentionMeter from '../components/ContentionMeter'

const fmt = (n) => n?.toLocaleString() ?? '—'
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)

const POS_ORDER = ['QB', 'RB', 'WR', 'TE']
const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }

function RankingsTab({ players, positionalRank, numTeams, rankMode }) {
  const isDynasty = rankMode === 'dynasty'

  const byPos = {}
  for (const p of players) {
    if (!POS_ORDER.includes(p.position)) continue
    if (!byPos[p.position]) byPos[p.position] = []
    byPos[p.position].push(p)
  }
  const overallKey = isDynasty ? 'overall_rank' : 'redraft_overall_rank'
  for (const pos of POS_ORDER) {
    if (byPos[pos]) {
      byPos[pos].sort((a, b) => (a[overallKey] ?? 9999) - (b[overallKey] ?? 9999))
    }
  }

  const n = numTeams || 0

  return (
    <div className="rankings-tab">
      {POS_ORDER.filter((pos) => byPos[pos]?.length).map((pos) => {
        const leagueRank = positionalRank?.[pos]
        const third = n ? Math.ceil(n / 3) : 0
        const rankCls = leagueRank && third
          ? leagueRank <= third ? 'rank-tag-top' : leagueRank > n - third ? 'rank-tag-bot' : 'rank-tag-mid'
          : ''
        return (
          <div key={pos} className="rankings-pos-group">
            <div className="rankings-pos-header">
              <span className="rankings-pos-pill" style={{ background: POS_COLOR[pos] }}>{pos}</span>
              {leagueRank && n ? (
                <span className={`rank-tag ${rankCls}`} style={{ fontSize: '0.8rem' }}>
                  League <strong>#{leagueRank}</strong> of {n}
                </span>
              ) : null}
            </div>
            <div className="rankings-player-list">
              {byPos[pos].map((p) => {
                const overall = isDynasty ? p.overall_rank : p.redraft_overall_rank
                const posRank = isDynasty ? p.pos_rank : p.redraft_pos_rank
                const value = isDynasty ? p.fc_value : p.redraft_value
                return (
                  <div key={p.sleeper_id} className="rankings-player-row">
                    <span className="rankings-overall">{overall ? `#${overall}` : '—'}</span>
                    <span className="rankings-pos-rank" style={{ color: POS_COLOR[pos] }}>
                      {posRank ? `${pos}${posRank}` : '—'}
                    </span>
                    <span className="rankings-name">{p.name}</span>
                    <span className="rankings-team">{p.nfl_team}</span>
                    {p.age && <span className="rankings-age">{p.age}y</span>}
                    <span className="rankings-value">{fmt(value)}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const ROUND_LABEL = { 1: '1st', 2: '2nd', 3: '3rd', 4: '4th' }

function TradeModal({ p, ownerName, onClose }) {
  useEffect(() => {
    function handler(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const label = `${p.season} ${ROUND_LABEL[p.round] ?? `Rd ${p.round}`}`

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-sheet" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">{label} Round Pick</div>
            <div className="modal-subtitle">Originally owned by {p.original_owner_name}</div>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {p.trade_history?.length > 0 ? p.trade_history.map((hop, i) => (
            <div key={i} className="pick-hop">
              <div className="pick-hop-header">
                <div className="pick-hop-teams">
                  <span className="pick-chain-past">{hop.from}</span>
                  <span className="pick-chain-arrow">→</span>
                  <span className="pick-chain-current">{hop.to}</span>
                </div>
                {hop.date && <span className="pick-hop-date">{hop.date}</span>}
              </div>
              {hop.bonus?.length > 0 && (
                <div className="pick-chain-section">
                  <span className="pick-chain-section-label">{hop.to} received</span>
                  {hop.bonus.map((item, j) => <div key={j} className="pick-chain-item pick-chain-got">• {item}</div>)}
                </div>
              )}
              {hop.cost?.length > 0 && (
                <div className="pick-chain-section">
                  <span className="pick-chain-section-label">{hop.from} received</span>
                  {hop.cost.map((item, j) => <div key={j} className="pick-chain-item pick-chain-gave">• {item}</div>)}
                </div>
              )}
              {!hop.cost?.length && !hop.bonus?.length && (
                <div className="pick-chain-item" style={{fontStyle:'italic',opacity:0.5}}>No exchange details on record</div>
              )}
            </div>
          )) : (
            <div style={{color:'var(--text-muted)',fontStyle:'italic',padding:'12px 0'}}>No transaction data found for this pick.</div>
          )}
        </div>
      </div>
    </div>
  )
}

function PickPill({ p, ownerName }) {
  const [open, setOpen] = useState(false)
  const canExpand = !p.own_pick

  return (
    <>
      <div
        className={`pick-pill ${p.own_pick ? 'pick-own' : 'pick-traded'} ${canExpand ? 'pick-clickable' : ''}`}
        onClick={() => canExpand && setOpen(true)}
      >
        <span className="pick-pill-round">{ROUND_LABEL[p.round] ?? `Rd ${p.round}`}</span>
        {p.projected_slot && <span className="pick-pill-slot">~{p.projected_slot}</span>}
        <span className="pick-pill-val">{fmt(p.fc_value)}</span>
        {!p.own_pick && (
          <span className="pick-pill-from">{p.original_owner_name}</span>
        )}
      </div>
      {open && <TradeModal p={p} ownerName={ownerName} onClose={() => setOpen(false)} />}
    </>
  )
}

function PicksByYear({ picks, ownerName }) {
  // Group by season, sort rounds within each year
  const byYear = {}
  for (const p of picks) {
    const yr = p.season
    if (!byYear[yr]) byYear[yr] = []
    byYear[yr].push(p)
  }
  for (const yr of Object.keys(byYear)) {
    byYear[yr].sort((a, b) => a.round - b.round)
  }
  const years = Object.keys(byYear).sort()
  const totalAll = picks.reduce((s, p) => s + (p.fc_value || 0), 0)

  return (
    <div className="picks-section">
      <div className="picks-section-header">
        <h2 className="section-title">Draft Picks Owned</h2>
        <span className="picks-total-all">{fmt(totalAll)} total</span>
      </div>

      <div className="picks-by-year">
        {years.map((yr) => {
          const yearPicks = byYear[yr]
          const yearTotal = yearPicks.reduce((s, p) => s + (p.fc_value || 0), 0)
          return (
            <div key={yr} className="picks-year-row">
              <span className="picks-year-label">{yr}</span>
              <div className="picks-year-chips">
                {yearPicks.map((p, i) => (
                  <PickPill key={i} p={p} ownerName={ownerName} />
                ))}
              </div>
              <span className="picks-year-total">{fmt(yearTotal)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function TeamProfile() {
  const { leagueId, rosterId } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [rankMode, setRankMode] = useState('dynasty')

  useEffect(() => {
    api.getTeam(leagueId, rosterId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [leagueId, rosterId])

  if (loading) return <LoadingSpinner message="Loading team…" />
  if (error) return <div className="error-state"><p>❌ {error}</p></div>
  if (!data) return null

  const { categorized = {}, roster_data = {} } = data
  const playerPct = pct(data.player_value, data.total_value)
  const pickPct = 100 - playerPct
  const starterPct = pct(data.starter_value, data.player_value)
  const benchPct = 100 - starterPct

  return (
    <div className="team-profile">
      <div className="profile-nav">
        <Link to={`/league/${leagueId}`} className="btn btn-secondary btn-sm">← League Home</Link>
        <Link to={`/league/${leagueId}/trades?roster_id=${rosterId}`} className="btn btn-accent btn-sm">
          Trade Ideas for This Team
        </Link>
      </div>

      <div className="profile-header">
        {data.avatar && (
          <img
            className="team-avatar"
            src={`https://sleepercdn.com/avatars/thumbs/${data.avatar}`}
            alt={data.display_name}
          />
        )}
        <div>
          <h1 className="page-title">{data.display_name}</h1>
          <p className="page-sub">Total Value: <strong className="accent">{fmt(data.total_value)}</strong></p>
        </div>
      </div>

      <div className="rank-mode-toggle">
        <button
          className={`rank-mode-btn${rankMode === 'dynasty' ? ' active' : ''}`}
          onClick={() => setRankMode('dynasty')}
        >
          Dynasty Rankings
        </button>
        <button
          className={`rank-mode-btn${rankMode === 'redraft' ? ' active' : ''}`}
          onClick={() => setRankMode('redraft')}
        >
          Redraft Rankings
        </button>
      </div>

      {/* Value split */}
      <div className="card-grid">
        <div className="stat-card">
          <h3>Assets</h3>
          <div className="split-bar">
            <div className="split-segment current" style={{ width: `${playerPct}%` }}>
              <span>{playerPct}%</span>
            </div>
            <div className="split-segment future" style={{ width: `${pickPct}%` }}>
              <span>{pickPct}%</span>
            </div>
          </div>
          <div className="split-legend">
            <span className="legend-dot current" /> Current ({fmt(data.player_value)})
            <span className="legend-dot future" /> Future ({fmt(data.pick_value)})
          </div>
        </div>

        <div className="stat-card">
          <h3>Depth</h3>
          <div className="split-bar">
            <div className="split-segment starter" style={{ width: `${starterPct}%` }}>
              <span>{starterPct}%</span>
            </div>
            <div className="split-segment bench" style={{ width: `${benchPct}%` }}>
              <span>{benchPct}%</span>
            </div>
          </div>
          <div className="split-legend">
            <span className="legend-dot starter" /> Starters ({fmt(data.starter_value)})
            <span className="legend-dot bench" /> Bench ({fmt(data.bench_value)})
          </div>
        </div>

        <div className="stat-card">
          <h3>Contention Window</h3>
          <ContentionMeter score={data.contention_score} category={data.contention_category} />
        </div>
      </div>

      {/* Positional breakdown */}
      <PositionalBreakdown
        breakdown={data.positional_breakdown || {}}
        rank={data.positional_rank || {}}
        numTeams={data.num_teams}
      />

      {/* Player rankings with Dynasty / Redraft toggle */}
      <RankingsTab
        players={roster_data.players || []}
        positionalRank={data.positional_rank || {}}
        numTeams={(data.positional_rank || {}).n || 0}
        rankMode={rankMode}
      />

      {/* SPT categorization — always shown below rankings */}
      <div className="spt-section">
        <div className="spt-col smash-col">
          <h2 className="spt-heading smash-heading">
            <span className="badge badge-smash">SMASH</span>
            <span className="spt-count">{categorized.smash?.length ?? 0}</span>
          </h2>
          <p className="spt-desc">Core keepers — don't trade without elite return</p>
          <PlayerTable players={categorized.smash || []} leagueId={leagueId} />
        </div>
        <div className="spt-col pass-col">
          <h2 className="spt-heading pass-heading">
            <span className="badge badge-pass">PASS</span>
            <span className="spt-count">{categorized.pass?.length ?? 0}</span>
          </h2>
          <p className="spt-desc">Tradeable pieces — moveable without gutting the roster</p>
          <PlayerTable players={categorized.pass || []} leagueId={leagueId} />
        </div>
        <div className="spt-col trash-col">
          <h2 className="spt-heading trash-heading">
            <span className="badge badge-trash">TRASH</span>
            <span className="spt-count">{categorized.trash?.length ?? 0}</span>
          </h2>
          <p className="spt-desc">Low-value — cut candidates</p>
          <PlayerTable players={categorized.trash || []} leagueId={leagueId} />
        </div>
      </div>

      {/* Draft picks by year */}
      {roster_data.picks?.length > 0 && (
        <PicksByYear picks={roster_data.picks} ownerName={data.display_name} />
      )}
    </div>
  )
}
