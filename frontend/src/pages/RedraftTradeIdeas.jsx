import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import TradeCard from '../components/TradeCard'

export default function RedraftTradeIdeas() {
  const { leagueId } = useParams()
  const [params, setParams] = useSearchParams()
  const rosterId = params.get('roster_id') || ''

  const [data, setData] = useState(null)
  const [teams, setTeams] = useState([])
  const [players, setPlayers] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [includeSmash, setIncludeSmash] = useState(false)
  const [winWinOnly, setWinWinOnly] = useState(false)

  // Force a specific player into the pool — the redraft twin of the dynasty
  // search. `player` is the committed selection the backend generates around;
  // `query` is just what's typed.
  const [query, setQuery] = useState('')
  const [player, setPlayer] = useState(null)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    api.getRedraftLeague(leagueId).then(d => setTeams(d.teams || [])).catch(() => {})
  }, [leagueId])

  // Search list comes from the snapshot, same as the trades — so anyone you can
  // pick is someone the generator can actually see.
  function loadPlayers() {
    api.getRedraftPlayers(leagueId).then(setPlayers).catch(() => setPlayers([]))
  }
  useEffect(loadPlayers, [leagueId])

  function load() {
    setLoading(true)
    api.getRedraftTrades(leagueId, {
      rosterId: rosterId || undefined,
      includeSmash,
      forcePlayerId: player?.sleeper_id,
      expand: expanded,
    })
      .then(d => { setData(d); setError('') })
      .catch(e => { setError(e.message); setData(null) })
      .finally(() => setLoading(false))
  }
  useEffect(load, [leagueId, rosterId, includeSmash, player, expanded])

  async function sync() {
    setSyncing(true)
    try {
      await api.syncRedraftLeague(leagueId)
      loadPlayers()
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSyncing(false)
    }
  }

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q || player) return []
    return players.filter(p => p.name.toLowerCase().includes(q)).slice(0, 8)
  }, [query, players, player])

  function selectPlayer(p) {
    setPlayer(p)
    setQuery(p.name)
    setDropdownOpen(false)
    setExpanded(false)
  }

  function clearPlayer() {
    setPlayer(null)
    setQuery('')
    setExpanded(false)
    inputRef.current?.focus()
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
        <div className="player-filter-wrap">
          <div className="player-filter-input-row">
            <input
              ref={inputRef}
              className="player-filter-input"
              type="text"
              placeholder="Search any rostered player…"
              value={query}
              onChange={e => { setQuery(e.target.value); setPlayer(null); setDropdownOpen(true) }}
              onFocus={() => setDropdownOpen(true)}
              // Delayed so the mousedown on a suggestion still lands.
              onBlur={() => setTimeout(() => setDropdownOpen(false), 150)}
            />
            {player && <button className="filter-clear" onClick={clearPlayer} title="Clear player">✕</button>}
          </div>
          {dropdownOpen && suggestions.length > 0 && (
            <div className="player-filter-dropdown">
              {suggestions.map(p => (
                <button key={p.sleeper_id} className="filter-suggestion" onMouseDown={() => selectPlayer(p)}>
                  <span className="filter-sug-pos" data-pos={p.position}>{p.position}</span>
                  <span className="filter-sug-name">{p.name}</span>
                  <span className="filter-sug-team">{p.display_name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <select
          value={rosterId}
          onChange={e => {
            const v = e.target.value
            setParams(v ? { roster_id: v } : {})
          }}
        >
          <option value="">{player ? 'Any trade partner' : 'All teams'}</option>
          {teams
            .filter(t => !player || t.roster_id !== player.roster_id)
            .map(t => (
              <option key={t.roster_id} value={t.roster_id}>{t.display_name}</option>
            ))}
        </select>

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

        <span className="rl-spacer" />
        <button className="btn btn-secondary btn-sm" onClick={sync} disabled={syncing}>
          {syncing ? 'Syncing…' : 'Refresh rosters'}
        </button>
      </div>

      {player && (
        <div className="filter-active-banner">
          Building trades around <strong>{player.name}</strong>
          <span className="filter-banner-team"> ({player.display_name})</span>
          <button className="filter-clear-inline" onClick={clearPlayer}>clear ✕</button>
        </div>
      )}

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

      {!loading && !error && player && !expanded && trades.length < 8 && (
        <div className="expand-search-banner">
          <span className="expand-search-note">
            {trades.length === 0
              ? `No balanced trades for ${player.name}${rosterId ? ' with this team' : ''}.`
              : `Only ${trades.length} idea${trades.length !== 1 ? 's' : ''} for ${player.name} at standard fairness.`}
          </span>
          <button className="btn btn-accent btn-sm expand-search-btn" onClick={() => setExpanded(true)}>
            Expand Search
          </button>
        </div>
      )}

      {expanded && (
        <div className="expand-search-active">
          Expanded search — wider value gap allowed
          <button className="filter-clear-inline" onClick={() => setExpanded(false)}>reset ✕</button>
        </div>
      )}

      {!loading && !error && (
        trades.length === 0
          ? (
            <p className="eval-placeholder">
              {player
                ? `No trades for ${player.name} match. Try including top players.`
                : 'No trades match. Try including top players.'}
            </p>
          )
          : (
            <div className="trades-list">
              {trades.map((t, i) => (
                <TradeCard
                  key={i}
                  trade={t}
                  leagueId={leagueId}
                  isRedraft
                  basePath="redraft"
                  highlightId={player?.sleeper_id}
                />
              ))}
            </div>
          )
      )}
    </div>
  )
}
