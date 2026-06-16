import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function PlayerHistoryModal({ leagueId, player, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    function handler(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    api.getPlayerHistory(leagueId, player.sleeper_id)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [leagueId, player.sleeper_id])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-sheet" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">{player.name}</div>
            <div className="modal-subtitle">
              {player.position}{player.nfl_team ? ` · ${player.nfl_team}` : ''} · Trade History
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          {loading && (
            <div style={{ color: 'var(--text-muted)', padding: '12px 0' }}>Loading…</div>
          )}
          {error && (
            <div style={{ color: '#e05c5c', padding: '12px 0' }}>Error: {error}</div>
          )}
          {data && data.trades.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', padding: '12px 0' }}>
              No trade history found — player may have been on the same roster since league inception.
            </div>
          )}
          {data && data.trades.map((t, i) => (
            <div key={i} className="pick-hop">
              <div className="pick-hop-header">
                <div className="pick-hop-teams">
                  <span className="pick-chain-past">{t.from}</span>
                  <span className="pick-chain-arrow">→</span>
                  <span className="pick-chain-current">{t.to}</span>
                </div>
                {t.date && <span className="pick-hop-date">{t.date}</span>}
              </div>
              {t.gave_up.length > 0 && (
                <div className="pick-chain-section">
                  <span className="pick-chain-section-label">{t.to} gave up</span>
                  {t.gave_up.map((item, j) => (
                    <div key={j} className="pick-chain-item pick-chain-gave">• {item}</div>
                  ))}
                </div>
              )}
              {t.also_received.length > 0 && (
                <div className="pick-chain-section">
                  <span className="pick-chain-section-label">{t.to} also received</span>
                  {t.also_received.map((item, j) => (
                    <div key={j} className="pick-chain-item pick-chain-got">• {item}</div>
                  ))}
                </div>
              )}
              {t.gave_up.length === 0 && t.also_received.length === 0 && (
                <div className="pick-chain-item" style={{ fontStyle: 'italic', opacity: 0.5 }}>
                  No exchange details on record
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
