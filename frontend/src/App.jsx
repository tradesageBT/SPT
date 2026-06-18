import { Routes, Route, Link } from 'react-router-dom'
import Home from './pages/Home'
import LeagueDashboard from './pages/LeagueDashboard'
import TeamProfile from './pages/TeamProfile'
import TradeIdeas from './pages/TradeIdeas'
import TradeEvaluator from './pages/TradeEvaluator'

export default function App() {
  return (
    <div className="app">
      <header className="site-header">
        <Link to="/" className="logo">
          <span className="logo-smash">SMASH</span>
          <span className="logo-pass">PASS</span>
          <span className="logo-trash">TRASH</span>
        </Link>
        <span className="logo-sub">Dynasty Value Engine</span>
      </header>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/league/:leagueId" element={<LeagueDashboard />} />
          <Route path="/league/:leagueId/team/:rosterId" element={<TeamProfile />} />
          <Route path="/league/:leagueId/trades" element={<TradeIdeas />} />
          <Route path="/league/:leagueId/evaluate" element={<TradeEvaluator />} />
        </Routes>
      </main>
    </div>
  )
}
