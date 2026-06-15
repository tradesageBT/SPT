import { useEffect, useState, useMemo, useRef } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import TradeCard from '../components/TradeCard'

function tradeContains(trade, sleeperId) {
  return [...trade.a_gives, ...trade.b_gives].some((p) => p.sleeper_id === sleeperId)
}

export default function TradeIdeas() {
  const { leagueId } = useParams()
  const [searchParams] = useSearchParams()
  const focusRosterId = searchParams.get('roster_id')

  const [trades, setTrades] = useState([])
  const [leaguePlayers, setLeaguePlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Pool options
  const [includeSmash, setIncludeSmash] = useState(false)
  const [includePicks, setIncludePicks] = useState(false)

  // Player filter — may force a backend re-fetch when player isn't in pool
  const [query, setQuery] = useState('')
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const inputRef = useRef(null)

  // Load all league players once for the search pool
  useEffect(() => {
    api.getLeaguePlayers(leagueId).then(setLeaguePlayers).catch(() => {})
  }, [leagueId])

  // Fetch trades — re-runs when options or selected player changes
  useEffect(() => {
    setLoading(true)
    setError(null)
    const opts = { includeSmash, includePicks, forcePlayerId: selectedPlayer?.sleeper_id ?? null }
    const fetcher = focusRosterId
      ? api.getTradesForTeam(leagueId, focusRosterId, opts)
      : api.getAllTrades(leagueId, opts)

    fetcher
      .then(setTrades)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [leagueId, focusRosterId, includeSmash, includePicks, selectedPlayer])

  const suggestions = useMemo(() => {
    if (!query.trim() || selectedPlayer) return []
    const q = query.toLowerCase()
    return leaguePlayers
      .filter((p) => p.name.toLowerCase().includes(q))
      .slice(0, 8)
  }, [query, leaguePlayers, selectedPlayer])

  const filteredTrades = useMemo(() => {
    if (!selectedPlayer) return trades
    return trades.filter((t) => tradeContains(t, selectedPlayer.sleeper_id))
  }, [trades, selectedPlayer])

  function selectPlayer(player) {
    setSelectedPlayer(player)
    setQuery(player.name)
    setDropdownOpen(false)
  }

  function clearFilter() {
    setSelectedPlayer(null)
    setQuery('')
    inputRef.current?.focus()
  }

  if (loading) return <LoadingSpinner message="Generating trade ideas…" />
  if (error) return <div className="error-state"><p>❌ {error}</p></div>

  return (
    <div className="trades-page">
      <div className="profile-nav">
        <Link to={`/league/${leagueId}`} className="back-link">← League</Link>
      </div>

      <div className="trades-header">
        <div>
          <h1 className="page-title">Trade Ideas</h1>
          {focusRosterId && (
            <p className="page-sub">Focused on roster {focusRosterId}</p>
          )}
        </div>

        <div className="trades-controls">
          <div className="pool-options">
            <label className="pool-option">
              <input
                type="checkbox"
                checked={includeSmash}
                onChange={(e) => setIncludeSmash(e.target.checked)}
              />
              <span>Include Smash players</span>
            </label>
            <label className="pool-option">
              <input
                type="checkbox"
                checked={includePicks}
                onChange={(e) => setIncludePicks(e.target.checked)}
              />
              <span>Include picks</span>
            </label>
          </div>

          <div className="player-filter-wrap">
            <div className="player-filter-input-row">
              <input
                ref={inputRef}
                className="player-filter-input"
                type="text"
                placeholder="Search any player in league…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value)
                  setSelectedPlayer(null)
                  setDropdownOpen(true)
                }}
                onFocus={() => setDropdownOpen(true)}
                onBlur={() => setTimeout(() => setDropdownOpen(false), 150)}
              />
              {selectedPlayer && (
                <button className="filter-clear" onClick={clearFilter} title="Clear filter">
                  ✕
                </button>
              )}
            </div>

            {dropdownOpen && suggestions.length > 0 && (
              <div className="player-filter-dropdown">
                {suggestions.map((p) => (
                  <button
                    key={p.sleeper_id}
                    className="filter-suggestion"
                    onMouseDown={() => selectPlayer(p)}
                  >
                    <span className="filter-sug-pos" data-pos={p.position}>{p.position}</span>
                    <span className="filter-sug-name">{p.name}</span>
                    <span className="filter-sug-team">{p.display_name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {selectedPlayer && (
        <div className="filter-active-banner">
          Showing {filteredTrades.length} trade{filteredTrades.length !== 1 ? 's' : ''} involving{' '}
          <strong>{selectedPlayer.name}</strong>
          {selectedPlayer.display_name && (
            <span className="filter-banner-team"> ({selectedPlayer.display_name})</span>
          )}
          <button className="filter-clear-inline" onClick={clearFilter}>clear ✕</button>
        </div>
      )}

      {filteredTrades.length === 0 ? (
        <div className="empty-state">
          <p>
            {selectedPlayer
              ? `No trade ideas found involving ${selectedPlayer.name}.`
              : 'No balanced trade opportunities found.'}
          </p>
        </div>
      ) : (
        <div className="trades-list">
          {filteredTrades.map((trade, i) => (
            <TradeCard
              key={i}
              trade={trade}
              leagueId={leagueId}
              highlightId={selectedPlayer?.sleeper_id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
