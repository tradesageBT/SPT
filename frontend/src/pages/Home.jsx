import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getRecentLeagues } from '../utils/recentLeagues'

const STORAGE_KEY = 'spt_mode'

export default function Home() {
  const [leagueId, setLeagueId] = useState('')
  const [mode, setMode] = useState(() => localStorage.getItem(STORAGE_KEY) || 'dynasty')
  const navigate = useNavigate()
  const recents = getRecentLeagues()

  function switchMode(m) {
    setMode(m)
    localStorage.setItem(STORAGE_KEY, m)
  }

  function handleSubmit(e) {
    e.preventDefault()
    const id = leagueId.trim()
    if (id) navigate(`/league/${id}`)
  }

  return (
    <div className="home-container">
      <div className="home-mode-tabs">
        <button
          className={`home-mode-tab${mode === 'dynasty' ? ' active' : ''}`}
          onClick={() => switchMode('dynasty')}
        >
          Dynasty League
        </button>
        <button
          className={`home-mode-tab${mode === 'redraft' ? ' active' : ''}`}
          onClick={() => switchMode('redraft')}
        >
          Redraft Draft
        </button>
      </div>

      {mode === 'redraft' ? (
        <div className="home-hero">
          <h1 className="home-title">
            Redraft draft assistant.<br />
            <span className="accent">Live ESPN integration.</span>
          </h1>
          <p className="home-sub">
            Connect to your ESPN redraft league via session cookies. Get real-time
            player rankings, tier breaks, and VOR analysis as the draft unfolds.
          </p>
          <button className="btn btn-primary" style={{ fontSize: '1rem', padding: '12px 28px' }} onClick={() => navigate('/redraft-draft')}>
            Open Draft Room →
          </button>
          <p className="home-hint">Supports ESPN leagues · Snake draft · PPR / Half-PPR / Standard</p>
        </div>
      ) : (
      <div className="home-hero">
        <h1 className="home-title">
          Dynasty analysis.<br />
          <span className="accent">Your league. Your trades.</span>
        </h1>
        <p className="home-sub">
          Connect your Sleeper dynasty league to rank every roster, surface hidden
          trade opportunities, and evaluate any deal — powered by live FantasyCalc
          dynasty values.
        </p>

        <form className="league-form" onSubmit={handleSubmit}>
          <input
            className="league-input"
            type="text"
            placeholder="Sleeper league ID (e.g. 1048199388)"
            value={leagueId}
            onChange={(e) => setLeagueId(e.target.value)}
            autoFocus
          />
          <button className="btn btn-primary" type="submit">
            Analyze League →
          </button>
        </form>

        <p className="home-hint">
          Find your league ID in the Sleeper app: League → Settings → League ID
        </p>

        {recents.length > 0 && (
          <div className="recent-leagues">
            <p className="recent-label">Recent leagues</p>
            <div className="recent-list">
              {recents.map((l) => (
                <button
                  key={l.id}
                  className="recent-league-btn"
                  onClick={() => navigate(`/league/${l.id}`)}
                >
                  <span className="recent-league-name">{l.name || l.id}</span>
                  {l.season && <span className="recent-league-season">{l.season}</span>}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      )}

      {mode === 'dynasty' && <div className="home-features">
        <div className="home-features-heading">What you get</div>

        <div className="feature-grid">
          <div className="feature-card">
            <div className="feature-icon">🏅</div>
            <h3>Full League Rankings</h3>
            <p>
              Every roster ranked by dynasty value with a contention window label —
              Championship Window, Ascending, Full Rebuild, and more. See exactly where
              every team stands.
            </p>
          </div>

          <div className="feature-card">
            <div className="spt-badges" style={{ marginBottom: '10px' }}>
              <span className="badge badge-smash">SMASH</span>
              <span className="badge badge-pass">PASS</span>
              <span className="badge badge-trash">TRASH</span>
            </div>
            <h3>Player Tiers Per Roster</h3>
            <p>
              Every team's players split into untouchables, tradeable pieces, and cut
              candidates. Know exactly who's available before you make an offer.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">📊</div>
            <h3>Positional League Ranks</h3>
            <p>
              See every team's league rank at each position — <em>#3 of 12 at WR,
              #9 at QB</em>. Instantly spot who needs what and who has surplus to deal.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">💡</div>
            <h3>Auto Trade Ideas</h3>
            <p>
              Value-balanced trades matched to positional needs across every team
              pairing. Filters for Win-Win deals, position, and lineup impact.
              Age impact and contention context on every card.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">⚖️</div>
            <h3>Manual Trade Evaluator</h3>
            <p>
              Build any trade by searching players by name — their team auto-populates.
              Get instant analysis: asset value, lineup delta, avg age shift, positional
              need match, and contention window fit.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">🔗</div>
            <h3>Picks, History & Acquisition</h3>
            <p>
              Every future pick with projected slot and full trade chain. Every player
              tagged as drafted, traded, or claimed. Click any player for their complete
              transaction history across all seasons.
            </p>
          </div>
        </div>
      </div>}
    </div>
  )
}
