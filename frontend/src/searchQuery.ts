import type { SearchFilters, SearchPayload } from './types'
import { EMPTY_FILTERS } from './types'

// The query string of a /search?… address. The names are the API fields (free text as `q`),
// always in this order, so one search has exactly one address.
const TEXT_PARAMS = ['brand', 'model', 'year', 'wheel_size', 'frame_size', 'bike_type'] as const

export function payloadToQuery(payload: SearchPayload): string {
  const q = new URLSearchParams()
  if (payload.search) q.set('q', payload.search)
  for (const key of TEXT_PARAMS) {
    const value = payload[key]
    if (value !== undefined && value !== '') q.set(key, String(value))
  }
  if (payload.is_electric !== undefined) q.set('is_electric', String(payload.is_electric))
  return q.toString()
}

// Bike types an older address may carry → the category code they became (TODO-047), so
// the form shows the option and the address is rewritten to the code.
const OLD_BIKE_TYPES: Record<string, string> = {
  'Hybrid/Commuter': 'City/Cross/Hybrid',
  'Cruiser':         'City/Cross/Hybrid',
}

// Unknown parameters, blank values, a year outside 1900–2100 and an is_electric other than
// true/false are dropped, so an edited address never sends the backend something it refuses.
export function queryToPayload(query: string): SearchPayload {
  const q = new URLSearchParams(query)
  const text = (key: string) => q.get(key)?.trim() || undefined
  const payload: SearchPayload = {}
  const search = text('q')
  if (search) payload.search = search
  for (const key of ['brand', 'model', 'wheel_size', 'frame_size', 'bike_type'] as const) {
    const value = text(key)
    if (value) payload[key] = key === 'bike_type' ? (OLD_BIKE_TYPES[value] ?? value) : value
  }
  const year = text('year')
  if (year && /^\d{4}$/.test(year) && +year >= 1900 && +year <= 2100) payload.year = +year
  const electric = text('is_electric')
  if (electric === 'true' || electric === 'false') payload.is_electric = electric === 'true'
  return payload
}

export const canonicalQuery = (query: string): string => payloadToQuery(queryToPayload(query))

// The filters panel as a search address fills it (free text goes into the search box).
export function payloadToFilters(payload: SearchPayload): SearchFilters {
  return {
    ...EMPTY_FILTERS,
    brand:       payload.brand ?? '',
    model:       payload.model ?? '',
    year:        payload.year != null ? String(payload.year) : '',
    wheel_size:  payload.wheel_size ?? '',
    bike_type:   payload.bike_type ?? '',
    frame_size:  payload.frame_size ?? '',
    is_electric: payload.is_electric,
  }
}
