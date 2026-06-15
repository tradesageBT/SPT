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
      .catch((e) => setError(e.message))
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

  if (loading) return <LoadingSpinner message="Fetching league data…" />
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
          <p className="page-sub">{data.season} Season · {data.teams.length} Teams</p>
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
