import { bikeKey } from './ratings'
import type { Bike, ExpertRating } from './types'

// Order of the search results, picked in the "Sortuj" select above the list.
export type SortOrder = 'rating_desc' | 'rating_asc' | 'name_asc' | 'name_desc'

export const DEFAULT_SORT: SortOrder = 'rating_desc'

export const SORT_OPTIONS: { value: SortOrder; label: string }[] = [
  { value: 'rating_desc', label: 'Ocena eksperta: od najwyższej' },
  { value: 'rating_asc',  label: 'Ocena eksperta: od najniższej' },
  { value: 'name_asc',    label: 'Nazwa: A–Z' },
  { value: 'name_desc',   label: 'Nazwa: Z–A' },
]

// Polish alphabet, case-insensitive, digits by value ("Marlin 5" before "Marlin 10").
const collator = new Intl.Collator('pl', { sensitivity: 'base', numeric: true })

const compareNames = (a: Bike, b: Bike): number =>
  collator.compare(a.brand, b.brand) || collator.compare(a.model, b.model)

// Name orders apply at once. Rating orders keep the backend order until every rating has
// settled, so cards do not jump; then rated bikes go by rating and "no rating" bikes last
// in both directions. Ties keep the backend order (stable sort).
export function sortBikes(
  bikes: Bike[],
  order: SortOrder,
  ratings: Record<string, ExpertRating>,
  ratingsSettled: boolean,
): Bike[] {
  if (order === 'name_asc')  return [...bikes].sort(compareNames)
  if (order === 'name_desc') return [...bikes].sort((a, b) => compareNames(b, a))
  if (!ratingsSettled) return bikes

  const direction = order === 'rating_desc' ? -1 : 1
  const rating = (b: Bike) => ratings[bikeKey(b)]?.rating ?? null
  return [...bikes].sort((a, b) => {
    const ra = rating(a)
    const rb = rating(b)
    if (ra == null || rb == null) return (ra == null ? 1 : 0) - (rb == null ? 1 : 0)
    return direction * (ra - rb)
  })
}
