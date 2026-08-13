export const CONTENTION_CLASS = {
  'All-In': 'winnow',
  'Championship Window': 'winnow',
  'Sustainable Contender': 'mixed',
  'Ascending': 'rebuild',
  'Treading Water': 'neutral',
  'Retooling': 'urgent',
  'Full Rebuild': 'rebuild',
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
