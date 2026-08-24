import { Routes, Route, Link } from 'react-router-dom'
import Home from './pages/Home'
import LeagueDashboard from './pages/LeagueDashboard'
import TeamProfile from './pages/TeamProfile'
import TradeIdeas from './pages/TradeIdeas'
import TradeEvaluator from './pages/TradeEvaluator'
import DraftRoom from './pages/DraftRoom'
import RedraftDraftRoom from './pages/RedraftDraftRoom'
import RedraftTrades from './pages/RedraftTrades'

export default function App() {
  return (
    <div className="app">
      <header className="site-header">
        <Link to="/" className="logo">
          <span className="logo-smash">SMASH</span>
          <span className="logo-pass">PASS</span>
          <span className="logo-trash">TRASH</span>
        </Link>
        <span className="logo-sub">Fantasy Value Engine</span>
        <nav className="site-nav">
          <Link to="/redraft-draft" className="site-nav-link">Redraft Draft</Link>
          <Link to="/redraft-trades" className="site-nav-link">Trade Evaluator</Link>
        </nav>
      </header>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/league/:leagueId" element={<LeagueDashboard />} />
          <Route path="/league/:leagueId/team/:rosterId" element={<TeamProfile />} />
          <Route path="/league/:leagueId/trades" element={<TradeIdeas />} />
          <Route path="/league/:leagueId/evaluate" element={<TradeEvaluator />} />
          <Route path="/league/:leagueId/draft" element={<DraftRoom />} />
          <Route path="/redraft-draft" element={<RedraftDraftRoom />} />
          <Route path="/redraft-trades" element={<RedraftTrades />} />
        </Routes>
      </main>
    </div>
  )
}
