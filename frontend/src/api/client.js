const BASE = '/api'

async function request(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export const api = {
  getLeague: (leagueId) => request(`/leagues/${leagueId}`),
  syncLeague: (leagueId) =>
    fetch(`${BASE}/leagues/${leagueId}/sync`, { method: 'POST' }).then((r) => {
      if (!r.ok) return r.json().catch(() => ({ detail: r.statusText })).then((e) => { throw new Error(e.detail || 'Sync failed') })
      return r.json()
    }),
  getTeam: (leagueId, rosterId) => request(`/leagues/${leagueId}/teams/${rosterId}`),
  getTradesForTeam: (leagueId, rosterId, opts = {}) => {
    const params = new URLSearchParams({ roster_id: rosterId })
    if (opts.includeSmash) params.set('include_smash', 'true')
    if (opts.includePicks) params.set('include_picks', 'true')
    if (opts.forcePlayerId) params.set('force_player_id', opts.forcePlayerId)
    if (opts.expand) params.set('expand', 'true')
    if (opts.excludedPlayerIds?.length) opts.excludedPlayerIds.forEach((id) => params.append('exclude', id))
    return request(`/leagues/${leagueId}/trades?${params}`)
  },
  getAllTrades: (leagueId, opts = {}) => {
    const params = new URLSearchParams()
    if (opts.includeSmash) params.set('include_smash', 'true')
    if (opts.includePicks) params.set('include_picks', 'true')
    if (opts.forcePlayerId) params.set('force_player_id', opts.forcePlayerId)
    if (opts.expand) params.set('expand', 'true')
    if (opts.excludedPlayerIds?.length) opts.excludedPlayerIds.forEach((id) => params.append('exclude', id))
    const qs = params.toString()
    return request(`/leagues/${leagueId}/trades${qs ? `?${qs}` : ''}`)
  },
  getLeaguePlayers: (leagueId) => request(`/leagues/${leagueId}/players`),
  getPlayerHistory: (leagueId, playerId) => request(`/leagues/${leagueId}/player/${playerId}/history`),
  getRecentTrades: (leagueId) => request(`/leagues/${leagueId}/recent-transactions`),
  getDraftState: (leagueId) => request(`/leagues/${leagueId}/draft`),
  getEspnDraftState: (leagueId, espnS2, swid, season, mySlot, budget) => {
    const p = new URLSearchParams({ league_id: leagueId, espn_s2: espnS2, swid, season, my_slot: mySlot, budget })
    return request(`/espn-draft/state?${p}`)
  },
  searchPlayers: (q = '', limit = 20, mode = 'redraft') =>
    request(`/espn-draft/players/search?q=${encodeURIComponent(q)}&limit=${limit}&mode=${mode}`),
  searchRedraftPlayers: (q = '', limit = 20) =>
    request(`/espn-draft/players/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  getSleeperDraftState: (leagueId) => request(`/sleeper-draft/state?league_id=${encodeURIComponent(leagueId)}`),
  getAuctionPool: (s) => {
    const p = new URLSearchParams({
      teams: s.teams, budget: s.budget, ppr: s.ppr,
      qb: s.qb, rb: s.rb, wr: s.wr, te: s.te,
      flex: s.flex, sflex: s.sflex, wr_rb_flex: s.wr_rb_flex, rec_flex: s.rec_flex,
      k: s.k, dst: s.dst, bench: s.bench,
    })
    return request(`/auction-draft/pool?${p}`)
  },
  getYahooStatus: () => request('/yahoo-draft/status'),
  getYahooLeagues: () => request('/yahoo-draft/leagues'),
  getYahooDraftState: (leagueKey) => request(`/yahoo-draft/state?league_key=${encodeURIComponent(leagueKey)}`),
  disconnectYahoo: () =>
    fetch(`${BASE}/yahoo-draft/auth`, { method: 'DELETE' }).then(r => r.json()),
  evaluateTrade: (leagueId, body) =>
    fetch(`${BASE}/leagues/${leagueId}/evaluate-trade`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((res) => {
      if (!res.ok) return res.json().then((e) => { throw new Error(e.detail || 'Request failed') })
      return res.json()
    }),
}
