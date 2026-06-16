export const CONTENTION_CLASS = {
  'Championship Window': 'winnow',
  'Fire Sale': 'winnow',
  'Win-Now Push': 'urgent',
  'Retooling': 'urgent',
  'Sustainable Contender': 'mixed',
  'Ascending': 'rebuild',
  'Full Rebuild': 'rebuild',
  'Treading Water': 'neutral',
}

export const CONTENTION_COLOR = {
  winnow: '#e05c5c',
  urgent: '#e0a45c',
  mixed: '#01d9ac',
  neutral: '#8b90b0',
  rebuild: '#5cb8e0',
}

export function contentionClass(category) {
  return CONTENTION_CLASS[category] || 'neutral'
}
