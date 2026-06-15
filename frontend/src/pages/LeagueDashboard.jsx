import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import TeamCard from '../components/TeamCard'
import LoadingSpinner from '../components/LoadingSpinner'
import { saveRecentLeague } from '../utils/recentLeagues'

export default function LeagueDashboard() {
  const { leagueId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    api.getLeague(leagueId)
      .then((d) => {
        setData(d)
        saveRecentLeague({ id: leagueId, name: d.league_name, season: d.season })
      })
      .catch(async () => {
        // League not in DB (e.g. after a server restart) — auto-sync then load
        try {
          setSyncing(true)
          await api.syncLeague(leagueId)
          const d = await api.getLeague(leagueId)
          setData(d)
          saveRecentLeague({ id: leagueId, name: d.league_name, season: d.season })
        } catch (e2) {
          setError(e2.message)
        } finally {
          setSyncing(false)
        }
      })
      .finally(() => setLoading(false))
  }, [leagueId])

  async function handleSync() {
    setSyncing(true)
    try {
      await api.syncLeague(leagueId)
      const fresh = await api.getLeague(leagueId)
      setData(fresh)
    } catch (e) {
      setError(e.message)
    } finally {
      setSyncing(false)
    }
  }

  if (loading) return <LoadingSpinner message={syncing ? 'Syncing league data…' : 'Fetching league data…'} />
  if (error) return (
    <div className="error-state">
      <p>❌ {error}</p>
      <button className="btn btn-secondary" onClick={() => navigate('/')}>← Back</button>
    </div>
  )
  if (!data) return null

  const maxValue = Math.max(...data.teams.map((t) => t.total_value || 0), 1)

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1 className="page-title">{data.league_name}</h1>
          <div className="league-meta">
            <span className="page-sub">{data.season} Season · {data.teams.length} Teams</span>
            <div className="scoring-badges">
              {data.superflex && <span className="scoring-badge">Superflex</span>}
              {data.ppr === 1 && <span className="scoring-badge">Full PPR</span>}
              {data.ppr === 0.5 && <span className="scoring-badge">Half PPR</span>}
              {data.ppr === 0 && <span className="scoring-badge">Standard</span>}
              {data.tep > 0 && <span className="scoring-badge">TEP +{data.tep}</span>}
            </div>
          </div>
        </div>
        <div className="dashboard-actions">
          <Link to={`/league/${leagueId}/trades`} className="btn btn-accent">
            Trade Ideas
          </Link>
          <button
            className="btn btn-secondary"
            onClick={handleSync}
            disabled={syncing}
          >
            {syncing ? 'Syncing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div className="team-list">
        {data.teams.map((team, idx) => (
          <TeamCard
            key={team.roster_id}
            team={team}
            rank={idx + 1}
            maxValue={maxValue}
            leagueId={leagueId}
          />
        ))}
      </div>
    </div>
  )
}
