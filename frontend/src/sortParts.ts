import type { PartResult } from './types'

// Order of the parts results (TODO-046): by name only — brand, then model.
export type PartSortOrder = 'name_asc' | 'name_desc'

export const DEFAULT_PART_SORT: PartSortOrder = 'name_asc'

export const PART_SORT_OPTIONS: { value: PartSortOrder; label: string }[] = [
  { value: 'name_asc',  label: 'Nazwa: A–Z' },
  { value: 'name_desc', label: 'Nazwa: Z–A' },
]

// Polish alphabet, case-insensitive, digits by value ("CS-M6100" before "CS-M8100", "105" after "11").
const collator = new Intl.Collator('pl', { sensitivity: 'base', numeric: true })

// A row from a bike's spec tree has no brand yet: its name (which starts with the brand) stands in.
const compare = (a: PartResult, b: PartResult): number =>
  collator.compare(a.brand || a.name, b.brand || b.name) || collator.compare(a.model, b.model)

export function sortParts(parts: PartResult[], order: PartSortOrder): PartResult[] {
  return [...parts].sort(order === 'name_asc' ? compare : (a, b) => compare(b, a))
}
