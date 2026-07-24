import { useEffect, useState, useMemo, useRef } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'
import LoadingSpinner from '../components/LoadingSpinner'
import TradeCard from '../components/TradeCard'

const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }
const fmt = (n) => n?.toLocaleString() ?? '—'

function tradeContains(trade, sleeperId) {
  return [...trade.a_gives, ...trade.b_gives].some((p) => p.sleeper_id === sleeperId)
}

function tradeHasPos(trade, pos) {
  return [...trade.a_gives, ...trade.b_gives].some((p) => p.position === pos)
}

function RecentTrades({ leagueId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)

  function toggle() {
    if (!open && data === null) {
      setLoading(true)
      api.getRecentTrades(leagueId)
        .then(setData)
        .catch(() => setData([]))
        .finally(() => setLoading(false))
    }
    setOpen((v) => !v)
  }

  return (
    <div className="recent-trades-section">
      <button className="recent-trades-toggle" onClick={toggle}>
        League Activity {open ? '▲' : '▼'}
      </button>

      {open && (
        loading
          ? <p className="recent-trades-status">Loading…</p>
          : !data || data.length === 0
          ? <p className="recent-trades-status">No recent trades found.</p>
          : <div className="recent-trades-list">
              {data.map((t, i) => (
                <div key={i} className="recent-trade-item">
                  {t.date && <div className="recent-trade-date">{t.date}</div>}
                  <div className="recent-trade-sides">
                    {t.sides.map((side, j) => (
                      <div key={j} className="recent-trade-side">
                        <span className="recent-trade-team">{side.team_name} gave</span>
                        <span className="recent-trade-assets">
                          {side.gave.map((p, k) => (
                            <span key={k} className="recent-trade-asset">
                              <span
                                className="recent-trade-pos"
                                style={{ background: POS_COLOR[p.position] || '#888' }}
                              >
                                {p.position || '?'}
                              </span>
                              {p.name}
                            </span>
                          ))}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
      )}
    </div>
  )
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

  // Player filter
  const [query, setQuery] = useState('')
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const inputRef = useRef(null)

  // Sort / filter
  const [winWinOnly, setWinWinOnly] = useState(false)
  const [posFilter, setPosFilter] = useState(null)   // null | 'QB' | 'RB' | 'WR' | 'TE'
  const [countFilter, setCountFilter] = useState(null) // null | 1 | 2
  const [sortBy, setSortBy] = useState('default')    // 'default' | 'fairness' | 'lineup'
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    api.getLeaguePlayers(leagueId).then(setLeaguePlayers).catch(() => {})
  }, [leagueId])

  useEffect(() => {
    setLoading(true)
    setError(null)
    const opts = { includeSmash, includePicks, forcePlayerId: selectedPlayer?.sleeper_id ?? null, expand: expanded }
    const fetcher = focusRosterId
      ? api.getTradesForTeam(leagueId, focusRosterId, opts)
      : api.getAllTrades(leagueId, opts)

    fetcher
      .then(setTrades)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [leagueId, focusRosterId, includeSmash, includePicks, selectedPlayer, expanded])

  const suggestions = useMemo(() => {
    if (!query.trim() || selectedPlayer) return []
    const q = query.toLowerCase()
    return leaguePlayers.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8)
  }, [query, leaguePlayers, selectedPlayer])

  const displayedTrades = useMemo(() => {
    let result = selectedPlayer ? trades.filter((t) => tradeContains(t, selectedPlayer.sleeper_id)) : trades
    if (winWinOnly) result = result.filter((t) => t.lineup_delta_a > 0 && t.lineup_delta_b > 0)
    if (posFilter)  result = result.filter((t) => tradeHasPos(t, posFilter))
    if (countFilter != null) result = result.filter((t) => t.a_gives.length === countFilter && t.b_gives.length === countFilter)
    if (sortBy === 'fairness') result = [...result].sort((a, b) => a.value_delta - b.value_delta)
    if (sortBy === 'lineup')   result = [...result].sort((a, b) => (b.lineup_delta_a + b.lineup_delta_b) - (a.lineup_delta_a + a.lineup_delta_b))
    return result
  }, [trades, selectedPlayer, winWinOnly, posFilter, countFilter, sortBy])

  function selectPlayer(player) {
    setSelectedPlayer(player)
    setQuery(player.name)
    setDropdownOpen(false)
    setExpanded(false)
  }

  function clearFilter() {
    setSelectedPlayer(null)
    setQuery('')
    setExpanded(false)
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
          {focusRosterId && <p className="page-sub">Focused on roster {focusRosterId}</p>}
        </div>

        <div className="trades-controls">
          <div className="pool-options">
            <label className="pool-option">
              <input type="checkbox" checked={includeSmash} onChange={(e) => setIncludeSmash(e.target.checked)} />
              <span>Include Smash</span>
            </label>
            <label className="pool-option">
              <input type="checkbox" checked={includePicks} onChange={(e) => setIncludePicks(e.target.checked)} />
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
                onChange={(e) => { setQuery(e.target.value); setSelectedPlayer(null); setDropdownOpen(true) }}
                onFocus={() => setDropdownOpen(true)}
                onBlur={() => setTimeout(() => setDropdownOpen(false), 150)}
              />
              {selectedPlayer && (
                <button className="filter-clear" onClick={clearFilter} title="Clear filter">✕</button>
              )}
            </div>
            {dropdownOpen && suggestions.length > 0 && (
              <div className="player-filter-dropdown">
                {suggestions.map((p) => (
                  <button key={p.sleeper_id} className="filter-suggestion" onMouseDown={() => selectPlayer(p)}>
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

      {/* Sort / filter bar */}
      <div className="trade-filter-bar">
        <div className="trade-filter-group">
          <button
            className={`trade-filter-btn${winWinOnly ? ' active' : ''}`}
            onClick={() => setWinWinOnly((v) => !v)}
          >
            Win-Win only
          </button>
        </div>

        <div className="trade-filter-group">
          {[1, 2].map((n) => (
            <button
              key={n}
              className={`trade-filter-btn${countFilter === n ? ' active' : ''}`}
              onClick={() => setCountFilter((v) => (v === n ? null : n))}
            >
              {n}v{n}
            </button>
          ))}
        </div>

        <div className="trade-filter-group">
          {['QB', 'RB', 'WR', 'TE'].map((pos) => (
            <button
              key={pos}
              className={`trade-filter-btn trade-filter-pos${posFilter === pos ? ' active' : ''}`}
              style={posFilter === pos ? { background: POS_COLOR[pos], color: '#fff', borderColor: POS_COLOR[pos] } : {}}
              onClick={() => setPosFilter((v) => (v === pos ? null : pos))}
            >
              {pos}
            </button>
          ))}
        </div>

        <div className="trade-filter-group trade-sort-group">
          <span className="trade-filter-label">Sort:</span>
          {[['default', 'Best match'], ['fairness', 'Fairness'], ['lineup', 'Lineup impact']].map(([val, label]) => (
            <button
              key={val}
              className={`trade-filter-btn${sortBy === val ? ' active' : ''}`}
              onClick={() => setSortBy(val)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {selectedPlayer && (
        <div className="filter-active-banner">
          Showing {displayedTrades.length} trade{displayedTrades.length !== 1 ? 's' : ''} involving{' '}
          <strong>{selectedPlayer.name}</strong>
          {selectedPlayer.display_name && (
            <span className="filter-banner-team"> ({selectedPlayer.display_name})</span>
          )}
          <button className="filter-clear-inline" onClick={clearFilter}>clear ✕</button>
        </div>
      )}

      {selectedPlayer && !expanded && trades.length < 8 && (
        <div className="expand-search-banner">
          <span className="expand-search-note">
            {trades.length === 0
              ? `No trade ideas found for ${selectedPlayer.name} at standard fairness.`
              : `Only ${trades.length} trade idea${trades.length !== 1 ? 's' : ''} found for ${selectedPlayer.name}.`}
          </span>
          <button
            className="btn btn-accent btn-sm expand-search-btn"
            onClick={() => setExpanded(true)}
          >
            Expand Search
          </button>
        </div>
      )}

      {expanded && (
        <div className="expand-search-active">
          Expanded search active — showing trades up to ±35% value difference
          <button className="filter-clear-inline" onClick={() => setExpanded(false)}>reset ✕</button>
        </div>
      )}

      {displayedTrades.length === 0 ? (
        <div className="empty-state">
          <p>
            {selectedPlayer && countFilter != null && trades.length > 0
              ? `No ${countFilter}v${countFilter} trades found for ${selectedPlayer.name} — try removing the ${countFilter}v${countFilter} filter to see all results.`
              : countFilter != null && trades.length > 0
              ? `No ${countFilter}v${countFilter} trades match the current filters — try removing the ${countFilter}v${countFilter} filter.`
              : selectedPlayer
              ? `No trade ideas found involving ${selectedPlayer.name}.`
              : winWinOnly || posFilter
              ? 'No trades match the current filters.'
              : 'No balanced trade opportunities found.'}
          </p>
          {countFilter != null && trades.length > 0 && (
            <button
              className="btn btn-sm"
              style={{ marginTop: '0.5rem' }}
              onClick={() => setCountFilter(null)}
            >
              Remove {countFilter}v{countFilter} filter
            </button>
          )}
        </div>
      ) : (
        <div className="trades-list">
          {displayedTrades.map((trade, i) => (
            <TradeCard key={i} trade={trade} leagueId={leagueId} highlightId={selectedPlayer?.sleeper_id} />
          ))}
        </div>
      )}

      <RecentTrades leagueId={leagueId} />
    </div>
  )
}
