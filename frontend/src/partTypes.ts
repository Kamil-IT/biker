import type { PartType } from './types'

// The parts catalogue's part types (TODO-046): `value` is the slug the backend stores in
// equipment.part_type (backend/app/part_types.py — keep the two lists in step), `label` the
// Polish name shown in the filter and on the tiles.
export const PART_TYPES: { value: PartType; label: string }[] = [
  { value: 'cassette',        label: 'Kaseta' },
  { value: 'chain',           label: 'Łańcuch' },
  { value: 'rear_derailleur', label: 'Przerzutka tylna' },
  { value: 'shifter',         label: 'Manetka' },
  { value: 'crankset',        label: 'Korba' },
  { value: 'bottom_bracket',  label: 'Suport' },
  { value: 'brake',           label: 'Hamulec' },
  { value: 'rotor',           label: 'Tarcza hamulcowa' },
  { value: 'tyre',            label: 'Opona' },
  { value: 'wheel',           label: 'Koło' },
  { value: 'cockpit',         label: 'Kierownica / mostek' },
  { value: 'seat',            label: 'Siodło / sztyca' },
]

const LABELS = new Map<string, string>(PART_TYPES.map(t => [t.value, t.label]))

export const isPartType = (value: unknown): value is PartType => typeof value === 'string' && LABELS.has(value)

// Polish label of a slug, '' for null / an unknown one.
export const partTypeLabel = (slug: string | null | undefined): string => (slug ? LABELS.get(slug) ?? '' : '')
