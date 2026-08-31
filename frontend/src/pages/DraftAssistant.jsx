import { Link } from 'react-router-dom'

export default function DraftAssistant() {
  return (
    <div className="da-page">
      <div className="da-title">Draft Assistant</div>
      <p className="da-sub">Choose your platform to get started.</p>
      <div className="da-cards">
        <Link to="/sleeper-draft" className="da-card">
          <div className="da-card-icon">💤</div>
          <div className="da-card-name">Sleeper</div>
          <div className="da-card-modes">Snake draft · live sync</div>
        </Link>
        <Link to="/auction-draft" className="da-card">
          <div className="da-card-icon">💰</div>
          <div className="da-card-name">Auction Draft</div>
          <div className="da-card-modes">Any platform · manual entry</div>
        </Link>
        <Link to="/yahoo-draft" className="da-card">
          <div className="da-card-icon da-yahoo-icon">Y!</div>
          <div className="da-card-name">Yahoo Fantasy</div>
          <div className="da-card-modes">Snake · needs API approval</div>
        </Link>
      </div>
    </div>
  )
}
