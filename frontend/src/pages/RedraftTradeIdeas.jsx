import { useEffect, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import TradeCard from '../components/TradeCard'

export default function RedraftTradeIdeas() {
  const { leagueId } = useParams()
  const [params, setParams] = useSearchParams()
  const rosterId = params.get('roster_id') || ''

  const [data, setData] = useState(null)
  const [teams, setTeams] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [includeSmash, setIncludeSmash] = useState(false)
  const [winWinOnly, setWinWinOnly] = useState(false)

  useEffect(() => {
    api.getRedraftLeague(leagueId).then(d => setTeams(d.teams || [])).catch(() => {})
  }, [leagueId])

  function load() {
    setLoading(true)
    api.getRedraftTrades(leagueId, {
      rosterId: rosterId || undefined,
      includeSmash,
    })
      .then(d => { setData(d); setError('') })
      .catch(e => { setError(e.message); setData(null) })
      .finally(() => setLoading(false))
  }
  useEffect(load, [leagueId, rosterId, includeSmash])

  async function sync() {
    setSyncing(true)
    try {
      await api.syncRedraftLeague(leagueId)
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSyncing(false)
    }
  }

  const trades = (data?.trades || []).filter(t =>
    !winWinOnly || (t.lineup_delta_a > 0 && t.lineup_delta_b > 0)
  )
  const focus = teams.find(t => String(t.roster_id) === String(rosterId))

  return (
    <div className="trades-page">
      <div className="profile-nav">
        <Link to={`/redraft/${leagueId}`} className="btn btn-secondary btn-sm">← League</Link>
      </div>

      {/* Plain block, not .trades-header — that's space-between, which would
          shove the focus line to the opposite edge from the title. */}
      <div className="rl-page-header">
        <h1 className="page-title">Trade Ideas</h1>
        {focus && <p className="rl-page-sub">for {focus.display_name}</p>}
      </div>

      <div className="rl-controls">
        <div className="rl-control-group">
          <label className="pool-option">
            <input type="checkbox" checked={includeSmash} onChange={e => setIncludeSmash(e.target.checked)} />
            Include top players
          </label>
          <label className="pool-option">
            <input type="checkbox" checked={winWinOnly} onChange={e => setWinWinOnly(e.target.checked)} />
            Win-win only
          </label>
        </div>
        <select
          value={rosterId}
          onChange={e => {
            const v = e.target.value
            setParams(v ? { roster_id: v } : {})
          }}
        >
          <option value="">All teams</option>
          {teams.map(t => (
            <option key={t.roster_id} value={t.roster_id}>{t.display_name}</option>
          ))}
        </select>
        <span className="rl-spacer" />
        <button className="btn btn-secondary btn-sm" onClick={sync} disabled={syncing}>
          {syncing ? 'Syncing…' : 'Refresh rosters'}
        </button>
      </div>

      {data?.computed_at && (
        <p className="rl-note">
          {/* Trades come from a snapshot, unlike the live rankings — say so, or a
              stale idea after a waiver claim looks like a bug. */}
          Rosters as of {new Date(data.computed_at).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
          })} · Refresh after waiver moves
        </p>
      )}

      {error && (
        <div className="rd-error">
          {error}
          <button className="btn btn-primary btn-sm" style={{ marginTop: 10 }} onClick={sync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
        </div>
      )}

      {loading && <p className="eval-placeholder">Finding trades…</p>}

      {!loading && !error && (
        trades.length === 0
          ? <p className="eval-placeholder">No trades match. Try including top players.</p>
          : (
            <div className="trades-list">
              {trades.map((t, i) => (
                <TradeCard
                  key={i}
                  trade={t}
                  leagueId={leagueId}
                  isRedraft
                  basePath="redraft"
                />
              ))}
            </div>
          )
      )}
    </div>
  )
}
