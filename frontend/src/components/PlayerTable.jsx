import { useState } from 'react'
import PlayerHistoryModal from './PlayerHistoryModal'

const POS_COLOR = { QB: '#e05c5c', RB: '#5cb8e0', WR: '#01d9ac', TE: '#e0a45c' }
const fmt = (n) => n?.toLocaleString() ?? '—'

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
