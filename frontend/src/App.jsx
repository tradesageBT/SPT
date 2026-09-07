import { Routes, Route, Link } from 'react-router-dom'
import Home from './pages/Home'
import LeagueDashboard from './pages/LeagueDashboard'
import TeamProfile from './pages/TeamProfile'
import TradeIdeas from './pages/TradeIdeas'
import TradeEvaluator from './pages/TradeEvaluator'
import DraftRoom from './pages/DraftRoom'
import RedraftDraftRoom from './pages/RedraftDraftRoom'
import RedraftTrades from './pages/RedraftTrades'
import YahooDraftRoom from './pages/YahooDraftRoom'
import DraftAssistant from './pages/DraftAssistant'
import SleeperDraftRoom from './pages/SleeperDraftRoom'
import AuctionDraftRoom from './pages/AuctionDraftRoom'
import RedraftLeagueHub from './pages/RedraftLeagueHub'
import RedraftTeamPage from './pages/RedraftTeamPage'
import RedraftTradeIdeas from './pages/RedraftTradeIdeas'
import LineupOptimizer from './pages/LineupOptimizer'
import WaiverWire from './pages/WaiverWire'

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
          <Link to="/draft-assistant" className="site-nav-link">Draft Assistant</Link>
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
          <Route path="/draft-assistant" element={<DraftAssistant />} />
          <Route path="/sleeper-draft" element={<SleeperDraftRoom />} />
          <Route path="/auction-draft" element={<AuctionDraftRoom />} />
          <Route path="/yahoo-draft" element={<YahooDraftRoom />} />
          <Route path="/redraft/:leagueId" element={<RedraftLeagueHub />} />
          <Route path="/redraft/:leagueId/team/:rosterId" element={<RedraftTeamPage />} />
          <Route path="/redraft/:leagueId/trades" element={<RedraftTradeIdeas />} />
          {/* One component, two paths: weekly points are mode-agnostic, but the
              back-link has to return to the right kind of league hub. */}
          <Route path="/league/:leagueId/lineup" element={<LineupOptimizer basePath="league" />} />
          <Route path="/redraft/:leagueId/lineup" element={<LineupOptimizer basePath="redraft" />} />
          <Route path="/league/:leagueId/waivers" element={<WaiverWire basePath="league" />} />
          <Route path="/redraft/:leagueId/waivers" element={<WaiverWire basePath="redraft" />} />
          <Route path="/redraft-trades" element={<RedraftTrades />} />
        </Routes>
      </main>
    </div>
  )
}
