import type { ExpertRating } from './types'

// Key of a bike in a ratings map. NUL cannot occur in a brand or model name, so no
// two brand/model pairs share a key.
export const bikeKey = (bike: { brand: string; model: string }): string =>
  `${bike.brand}\u0000${bike.model}`

export const PENDING_RATING: ExpertRating = { state: 'pending', rating: null }
export const NO_RATING: ExpertRating      = { state: 'error',   rating: null }
