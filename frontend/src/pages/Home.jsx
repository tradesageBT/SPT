import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getRecentLeagues } from '../utils/recentLeagues'

export default function Home() {
  const [leagueId, setLeagueId] = useState('')
  const navigate = useNavigate()
  const recents = getRecentLeagues()

  function handleSubmit(e) {
    e.preventDefault()
    const id = leagueId.trim()
    if (id) navigate(`/league/${id}`)
  }

  return (
    <div className="home-container">
      <div className="home-hero">
        <h1 className="home-title">
          Dynasty value.<br />
          <span className="accent">Instantly.</span>
        </h1>
        <p className="home-sub">
          Paste your Sleeper league ID to see team valuations, positional
          breakdowns, and trade ideas — powered by FantasyCalc dynasty values.
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

      <div className="feature-grid">
        <div className="feature-card">
          <div className="feature-icon">📊</div>
          <h3>Team Value Profiles</h3>
          <p>Total value, starter vs bench split, positional breakdown vs league average</p>
        </div>
        <div className="feature-card">
          <div className="feature-icon">🏆</div>
          <div className="spt-badges">
            <span className="badge badge-smash">SMASH</span>
            <span className="badge badge-pass">PASS</span>
            <span className="badge badge-trash">TRASH</span>
          </div>
          <h3>Player Categorization</h3>
          <p>Core keepers, tradeable pieces, and cut candidates for every roster</p>
        </div>
        <div className="feature-card">
          <div className="feature-icon">🔄</div>
          <h3>Trade Ideas</h3>
          <p>Value-balanced trade suggestions matched to positional needs</p>
        </div>
      </div>
    </div>
  )
}
