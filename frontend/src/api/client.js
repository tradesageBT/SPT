const BASE = '/api'

async function request(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    // FastAPI validation errors return `detail` as an array of objects, which
    // would otherwise stringify to a useless "[object Object]".
    const d = err.detail
    throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : 'Request failed')
  }
  return res.json()
}

async function send(path, method, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    // FastAPI validation errors return `detail` as an array of objects, which
    // would otherwise stringify to a useless "[object Object]".
    const d = err.detail
    throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : 'Request failed')
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
  getSleeperDraftState: (leagueId, myRosterId) => {
    const p = new URLSearchParams({ league_id: leagueId })
    // Optional: setup loads teams before you've picked one. When present the
    // server flags which available players fill a need for you.
    if (myRosterId != null) p.set('my_roster_id', myRosterId)
    return request(`/sleeper-draft/state?${p}`)
  },
  getRedraftLeague: (leagueId) => request(`/redraft-league/${encodeURIComponent(leagueId)}`),
  getRedraftTeam: (leagueId, rosterId) =>
    request(`/redraft-league/${encodeURIComponent(leagueId)}/teams/${rosterId}`),
  syncRedraftLeague: (leagueId) =>
    send(`/redraft-league/${encodeURIComponent(leagueId)}/sync`, 'POST', {}),
  getRedraftPlayers: (leagueId) =>
    request(`/redraft-league/${encodeURIComponent(leagueId)}/players`),
  getRedraftTrades: (leagueId, opts = {}) => {
    const p = new URLSearchParams()
    if (opts.rosterId) p.set('roster_id', opts.rosterId)
    if (opts.includeSmash) p.set('include_smash', 'true')
    if (opts.expand) p.set('expand', 'true')
    if (opts.forcePlayerId) p.set('force_player_id', opts.forcePlayerId)
    const qs = p.toString()
    return request(`/redraft-league/${encodeURIComponent(leagueId)}/trades${qs ? `?${qs}` : ''}`)
  },
  getWeeklyState: () => request('/weekly/state'),
  getSleeperUser: (username) => request(`/weekly/user/${encodeURIComponent(username)}`),
  getSleeperUserLeagues: (userId, season) =>
    request(`/weekly/user/${encodeURIComponent(userId)}/leagues${season ? `?season=${season}` : ''}`),
  getWeeklyLineup: (leagueId, rosterId, week) => {
    const p = new URLSearchParams({ roster_id: rosterId })
    if (week) p.set('week', week)
    return request(`/weekly/league/${encodeURIComponent(leagueId)}/lineup?${p}`)
  },
  getWeeklyWaivers: (leagueId, rosterId, opts = {}) => {
    const p = new URLSearchParams({ roster_id: rosterId })
    if (opts.week) p.set('week', opts.week)
    if (opts.limit) p.set('limit', opts.limit)
    if (opts.mode) p.set('mode', opts.mode)
    return request(`/weekly/league/${encodeURIComponent(leagueId)}/waivers?${p}`)
  },
  getAuctionPool: (s) => {
    const p = new URLSearchParams({
      teams: s.teams, budget: s.budget, ppr: s.ppr,
      qb: s.qb, rb: s.rb, wr: s.wr, te: s.te,
      flex: s.flex, sflex: s.sflex, wr_rb_flex: s.wr_rb_flex, rec_flex: s.rec_flex,
      k: s.k, dst: s.dst, bench: s.bench,
      pass_td_pts: s.passTdPts ?? 4, rush_att_pts: s.rushAttPts ?? 0,
    })
    return request(`/auction-draft/pool?${p}`)
  },
  createAuctionRoom: (settings) => send('/auction-draft/room', 'POST', { settings }),
  getAuctionRoom: (code) => request(`/auction-draft/room/${encodeURIComponent(code)}`),
  addAuctionPick: (code, pick) =>
    send(`/auction-draft/room/${encodeURIComponent(code)}/pick`, 'POST', pick),
  deleteAuctionPick: (code, id) =>
    send(`/auction-draft/room/${encodeURIComponent(code)}/pick/${id}`, 'DELETE'),
  clearAuctionPicks: (code) =>
    send(`/auction-draft/room/${encodeURIComponent(code)}/picks`, 'DELETE'),
  setAuctionNomination: (code, player) =>
    send(`/auction-draft/room/${encodeURIComponent(code)}/nominate`, 'POST', { player }),
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
