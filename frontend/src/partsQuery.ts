import { isPartType } from './partTypes'
import type { PartsFilters, PartsSearchPayload } from './types'
import { EMPTY_PARTS_FILTERS } from './types'

// The query string of a /parts?… address (TODO-046), the parts counterpart of searchQuery.ts.
// Short names (free text `q`, `type`, `brand`, `model`, `group`), always in this order, so one
// search has exactly one address.
const PARAMS: [keyof PartsSearchPayload, string][] = [
  ['search', 'q'], ['part_type', 'type'], ['brand', 'brand'], ['model', 'model'], ['groupset', 'group'],
]

export function payloadToQuery(payload: PartsSearchPayload): string {
  const q = new URLSearchParams()
  for (const [field, param] of PARAMS) {
    const value = payload[field]?.trim()
    if (value) q.set(param, value)
  }
  return q.toString()
}

// Unknown parameters, blank values and a type outside the 12 are dropped, so an edited address
// never sends the backend something it refuses.
export function queryToPayload(query: string): PartsSearchPayload {
  const q = new URLSearchParams(query)
  const payload: PartsSearchPayload = {}
  for (const [field, param] of PARAMS) {
    const value = q.get(param)?.trim()
    if (!value) continue
    if (field === 'part_type') {
      if (isPartType(value)) payload.part_type = value
    } else {
      payload[field] = value
    }
  }
  return payload
}

export const canonicalQuery = (query: string): string => payloadToQuery(queryToPayload(query))

// The filters panel as a /parts?… address fills it (free text goes into the search box).
export function payloadToFilters(payload: PartsSearchPayload): PartsFilters {
  return {
    ...EMPTY_PARTS_FILTERS,
    part_type: payload.part_type ?? '',
    brand:     payload.brand ?? '',
    model:     payload.model ?? '',
    groupset:  payload.groupset ?? '',
  }
}
