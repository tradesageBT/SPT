export const CONTENTION_CLASS = {
  'Championship Window': 'winnow',
  'All-In': 'winnow',
  'Sustainable Contender': 'mixed',
  'Ascending': 'mixed',
  'Treading Water': 'neutral',
  'Retooling': 'rebuild',
  'Full Rebuild': 'rebuild',
}

export const CONTENTION_COLOR = {
  winnow: '#e05c5c',
  mixed: '#01d9ac',
  neutral: '#8b90b0',
  rebuild: '#5cb8e0',
}

export function contentionClass(category) {
  return CONTENTION_CLASS[category] || 'neutral'
}
