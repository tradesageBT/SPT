import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import { saveRecentLeague } from '../utils/recentLeagues'
import TeamCard from '../components/TeamCard'

const fmt = (n) => n?.toLocaleString() ?? '—'

export default function RedraftLeagueHub() {
  const { leagueId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.getRedraftLeague(leagueId)
      .then(d => {
        setData(d)
        setError('')
        saveRecentLeague({ id: leagueId, name: d.league_name, season: d.season, mode: 'redraft' })
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [leagueId])

  if (loading) return <div className="rd-loading">Loading league…</div>
  if (error) return <div className="rd-error">{error}</div>
  if (!data) return null

  const s = data.settings || {}
  const teams = data.teams || []
  // Rankings are by roster value; the bar is scaled to the strongest roster.
  const maxValue = Math.max(...teams.map(t => t.total_value || 0), 1)
  const flex = Object.entries(s.flex || {}).filter(([, n]) => n > 0)

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1 className="page-title">{data.league_name}</h1>
        <p className="league-meta">
          {data.season} Season · {data.num_teams} Teams · Redraft
        </p>
        <div className="scoring-badges">
          <span className="badge">
            {s.ppr === 1 ? 'Full PPR' : s.ppr === 0.5 ? 'Half PPR' : 'Standard'}
          </span>
          {s.superflex && <span className="badge">Superflex</span>}
          {flex.map(([k, n]) => (
            <span key={k} className="badge">
              {n}× {k === 'sflex' ? 'SUPERFLEX' : k === 'wr_rb_flex' ? 'W/R'
                : k === 'rec_flex' ? 'W/T' : 'FLEX'}
            </span>
          ))}
        </div>
      </div>

      <div className="dashboard-actions">
        <Link to={`/redraft/${leagueId}/trades`} className="btn btn-secondary">Trade Ideas</Link>
      </div>

      <p className="league-meta" style={{ marginBottom: 10 }}>
        Ranked by roster value. Positional ranks compare each team's best
        starters at that position against the rest of the league.
      </p>

      <div className="team-list">
        {teams.map((team, i) => (
          <TeamCard
            key={team.roster_id}
            team={team}
            rank={i + 1}
            maxValue={maxValue}
            leagueId={leagueId}
            rankMode="redraft"
            basePath="redraft"
          />
        ))}
      </div>
    </div>
  )
}
