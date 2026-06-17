import { useState } from 'react'
import PlayerHistoryModal from './PlayerHistoryModal'

const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }
const fmt = (n) => n?.toLocaleString() ?? '—'

const DraftIcon = () => (
  <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
    {/* Pen body — straight diagonal shaft */}
    <path d="M3.5 2.5 L10.5 9.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    {/* Filled nib at the tip */}
    <path d="M10.5 9.5 L12.5 13 L9 11.5 Z" fill="currentColor"/>
    {/* Signature squiggle below */}
    <path d="M0.5 13 Q2.5 11.5 4.5 13 Q6.5 14.5 8.5 13" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" fill="none"/>
  </svg>
)

const TradeIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <path d="M2 4.5 H10 M8 2.5 L10 4.5 L8 6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M11 8.5 H3 M5 6.5 L3 8.5 L5 10.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const ClaimIcon = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <circle cx="6.5" cy="6.5" r="5" stroke="currentColor" strokeWidth="1.4"/>
    <path d="M6.5 3.5 V9.5 M3.5 6.5 H9.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
  </svg>
)

function AcqBadge({ type, faab }) {
  if (!type || type === 'homegrown')
    return <span className="acq-icon acq-drafted" title="Drafted by this team"><DraftIcon /></span>
  if (type === 'traded')
    return <span className="acq-icon acq-traded" title="Acquired via trade"><TradeIcon /></span>
  const label = faab > 0 ? `$${faab}` : ''
  return (
    <span className="acq-icon acq-claimed" title={faab > 0 ? `Claimed (FAAB: $${faab})` : 'Waiver / FA claim'}>
      <ClaimIcon />{label && <span className="acq-faab">{label}</span>}
    </span>
  )
}

export default function PlayerTable({ players = [], leagueId }) {
  const [selected, setSelected] = useState(null)

  if (!players.length) return <p className="empty-players">None</p>
  return (
    <>
      <div className="player-table">
        {players.map((p) => (
          <div
            key={p.sleeper_id}
            className={`player-row${leagueId ? ' player-row-clickable' : ''}`}
            onClick={() => leagueId && setSelected(p)}
          >
            <span
              className="player-pos-badge"
              style={{ background: POS_COLOR[p.position] || '#666' }}
            >
              {p.position || '?'}
            </span>
            <span className="player-name">{p.name}</span>
            <AcqBadge type={p.acquisition_type} faab={p.faab_bid} />
            {p.on_taxi && <span className="player-status-badge status-taxi">TAXI</span>}
            {p.on_ir && <span className="player-status-badge status-ir">IR</span>}
            <span className="player-team">{p.nfl_team}</span>
            {p.age && <span className="player-age">{p.age}y</span>}
            <span className="player-value">{fmt(p.fc_value)}</span>
          </div>
        ))}
      </div>
      {selected && (
        <PlayerHistoryModal
          leagueId={leagueId}
          player={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  )
}
