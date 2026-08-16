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
  const [partnerFilter, setPartnerFilter] = useState(null) // null | roster_id
  const [sortBy, setSortBy] = useState('default')    // 'default' | 'fairness' | 'lineup'
  const [expanded, setExpanded] = useState(false)

  // Player frequency / exclusions
  const [excludedPlayers, setExcludedPlayers] = useState(new Set())
  const [blockedPlayers, setBlockedPlayers] = useState(new Set()) // sent to backend on regenerate
  const [freqOpen, setFreqOpen] = useState(true)

  function toggleExclude(sleeperId) {
    setExcludedPlayers((prev) => {
      const next = new Set(prev)
      if (next.has(sleeperId)) next.delete(sleeperId)
      else next.add(sleeperId)
      return next
    })
  }

  useEffect(() => {
    api.getLeaguePlayers(leagueId).then(setLeaguePlayers).catch(() => {})
  }, [leagueId])

  useEffect(() => {
    setLoading(true)
    setError(null)
    const opts = {
      includeSmash,
      includePicks,
      forcePlayerId: selectedPlayer?.sleeper_id ?? null,
      expand: expanded,
      excludedPlayerIds: blockedPlayers.size > 0 ? [...blockedPlayers] : undefined,
    }
    const fetcher = focusRosterId
      ? api.getTradesForTeam(leagueId, focusRosterId, opts)
      : api.getAllTrades(leagueId, opts)

    fetcher
      .then(setTrades)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [leagueId, focusRosterId, includeSmash, includePicks, selectedPlayer, expanded, blockedPlayers])

  const suggestions = useMemo(() => {
    if (!query.trim() || selectedPlayer) return []
    const q = query.toLowerCase()
    return leaguePlayers.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8)
  }, [query, leaguePlayers, selectedPlayer])

  // All unique counterparty teams derived from the trades list
  const partnerTeams = useMemo(() => {
    const focusId = focusRosterId ? parseInt(focusRosterId) : null
    const map = {}
    for (const t of trades) {
      if (t.team_a.roster_id !== focusId) map[t.team_a.roster_id] = t.team_a.display_name
      if (t.team_b.roster_id !== focusId) map[t.team_b.roster_id] = t.team_b.display_name
    }
    return Object.entries(map)
      .map(([id, name]) => ({ roster_id: parseInt(id), display_name: name }))
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
  }, [trades, focusRosterId])

  // Player frequency — computed from raw trades before exclusion filter
  const playerFrequency = useMemo(() => {
    const map = {}
    for (const trade of trades) {
      for (const p of [...trade.a_gives, ...trade.b_gives]) {
        if (p.position === 'PK') continue
        if (!map[p.sleeper_id]) map[p.sleeper_id] = { sleeper_id: p.sleeper_id, name: p.name, position: p.position, count: 0 }
        map[p.sleeper_id].count++
      }
    }
    return Object.values(map).sort((a, b) => b.count - a.count)
  }, [trades])

  const displayedTrades = useMemo(() => {
    let result = selectedPlayer ? trades.filter((t) => tradeContains(t, selectedPlayer.sleeper_id)) : trades
    if (excludedPlayers.size > 0) result = result.filter((t) => ![...t.a_gives, ...t.b_gives].some((p) => excludedPlayers.has(p.sleeper_id)))
    if (partnerFilter != null) result = result.filter((t) => t.team_a.roster_id === partnerFilter || t.team_b.roster_id === partnerFilter)
    if (winWinOnly) result = result.filter((t) => t.lineup_delta_a > 0 && t.lineup_delta_b > 0)
    if (posFilter)  result = result.filter((t) => tradeHasPos(t, posFilter))
    if (countFilter != null) result = result.filter((t) => {
      const playersA = t.a_gives.filter(p => p.position !== 'PK').length
      const playersB = t.b_gives.filter(p => p.position !== 'PK').length
      return playersA === countFilter && playersB === countFilter
    })
    if (sortBy === 'fairness') result = [...result].sort((a, b) => a.value_delta - b.value_delta)
    if (sortBy === 'lineup')   result = [...result].sort((a, b) => (b.lineup_delta_a + b.lineup_delta_b) - (a.lineup_delta_a + a.lineup_delta_b))
    return result
  }, [trades, selectedPlayer, excludedPlayers, partnerFilter, winWinOnly, posFilter, countFilter, sortBy])

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
        <Link to={`/league/${leagueId}`} className="btn btn-secondary btn-sm">← League Home</Link>
      </div>

      <div className="trades-header">
        <div>
          <h1 className="page-title">Trade Ideas</h1>
          {focusRosterId && (
            <p className="page-sub">
              {leaguePlayers.find((p) => String(p.roster_id) === focusRosterId)?.display_name ?? `Team ${focusRosterId}`}
            </p>
          )}
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

          {partnerTeams.length > 0 && (
            <div className="partner-filter-wrap">
              <span className="partner-filter-label">Trade with:</span>
              <select
                className="partner-filter-select"
                value={partnerFilter ?? ''}
                onChange={(e) => setPartnerFilter(e.target.value ? parseInt(e.target.value) : null)}
              >
                <option value="">Any team</option>
                {partnerTeams.map((t) => (
                  <option key={t.roster_id} value={t.roster_id}>{t.display_name}</option>
                ))}
              </select>
              {partnerFilter != null && (
                <button className="filter-clear" onClick={() => setPartnerFilter(null)} title="Clear">✕</button>
              )}
            </div>
          )}
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

      {selectedPlayer && !expanded && displayedTrades.length < 8 && (
        <div className="expand-search-banner">
          <span className="expand-search-note">
            {displayedTrades.length === 0
              ? `No trade ideas found for ${selectedPlayer.name}${partnerFilter != null ? ' with this team' : ''} at standard fairness.`
              : `Only ${displayedTrades.length} trade idea${displayedTrades.length !== 1 ? 's' : ''} found for ${selectedPlayer.name}.`}
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
          Expanded search active — showing trades up to ±50% value difference
          <button className="filter-clear-inline" onClick={() => setExpanded(false)}>reset ✕</button>
        </div>
      )}

      {playerFrequency.length > 0 && (
        <div className="player-freq-panel">
          <div className="player-freq-header" onClick={() => setFreqOpen((v) => !v)}>
            <span className="player-freq-title">Players in these trades</span>
            {excludedPlayers.size > 0 && (
              <button
                className="player-freq-clear"
                onClick={(e) => { e.stopPropagation(); setExcludedPlayers(new Set()) }}
              >
                Clear {excludedPlayers.size} exclusion{excludedPlayers.size !== 1 ? 's' : ''}
              </button>
            )}
            <span className="player-freq-toggle">{freqOpen ? '▲' : '▼'}</span>
          </div>
          {freqOpen && (
            <div className="player-freq-list">
              {playerFrequency.map((p) => {
                const excluded = excludedPlayers.has(p.sleeper_id)
                return (
                  <div key={p.sleeper_id} className={`player-freq-row${excluded ? ' freq-excluded' : ''}`}>
                    <span className="chip-pos" style={{ background: POS_COLOR[p.position] || '#666', fontSize: '0.65rem', padding: '1px 4px', borderRadius: 3 }}>
                      {p.position}
                    </span>
                    <span className="player-freq-name">{p.name}</span>
                    <span className="player-freq-count">{p.count}</span>
                    <button
                      className={`player-freq-btn${excluded ? ' freq-btn-include' : ' freq-btn-exclude'}`}
                      onClick={() => toggleExclude(p.sleeper_id)}
                      title={excluded ? 'Include this player' : 'Exclude this player'}
                    >
                      {excluded ? 'include' : 'exclude'}
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {blockedPlayers.size > 0 && (
        <div className="expand-search-active">
          Regenerated excluding {blockedPlayers.size} player{blockedPlayers.size !== 1 ? 's' : ''}
          <button
            className="filter-clear-inline"
            onClick={() => { setBlockedPlayers(new Set()); setExcludedPlayers(new Set()) }}
          >
            reset ✕
          </button>
        </div>
      )}

      {displayedTrades.length === 0 ? (
        <div className="empty-state">
          <p>
            {selectedPlayer && countFilter != null && trades.length > 0
              ? `No ${countFilter}v${countFilter} trades found for ${selectedPlayer.name} — try removing the ${countFilter}v${countFilter} filter to see all results.`
              : countFilter != null && trades.length > 0
              ? `No ${countFilter}v${countFilter} trades match the current filters — try removing the ${countFilter}v${countFilter} filter.`
              : excludedPlayers.size > 0 && trades.length > 0
              ? `All trades filtered out by ${excludedPlayers.size} exclusion${excludedPlayers.size !== 1 ? 's' : ''}. Regenerate to find new trades that avoid those players.`
              : selectedPlayer
              ? `No trade ideas found involving ${selectedPlayer.name}.`
              : winWinOnly || posFilter
              ? 'No trades match the current filters.'
              : 'No balanced trade opportunities found.'}
          </p>
          {excludedPlayers.size > 0 && trades.length > 0 && (
            <button
              className="btn btn-accent btn-sm"
              style={{ marginTop: '0.75rem' }}
              onClick={() => {
                setBlockedPlayers((prev) => new Set([...prev, ...excludedPlayers]))
                setExcludedPlayers(new Set())
              }}
            >
              ↻ Regenerate without excluded players
            </button>
          )}
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
