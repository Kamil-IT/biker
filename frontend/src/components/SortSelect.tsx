import { CaretDown } from '@phosphor-icons/react'
import { SORT_OPTIONS, type SortOrder } from '../sortBikes'

interface SortSelectProps {
  value: SortOrder
  onChange: (order: SortOrder) => void
}

// "Sortuj" select above the search results: expert rating or name, each both ways.
export default function SortSelect({ value, onChange }: SortSelectProps) {
  return (
    <div className="flex items-center justify-end gap-2.5 mb-4">
      <label
        htmlFor="results-sort"
        className="font-mono text-[11px] text-muted uppercase tracking-wider"
      >
        Sortuj
      </label>
      <div className="relative">
        <select
          id="results-sort"
          value={value}
          onChange={e => onChange(e.target.value as SortOrder)}
          className="
            appearance-none cursor-pointer
            pl-3 pr-8 py-1.5
            bg-parchment text-charcoal
            border border-border rounded-lg
            font-body text-sm
            focus:outline-none focus:border-terra focus:ring-2 focus:ring-terra/20
            transition-colors duration-200
          "
        >
          {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <CaretDown
          size={12}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
          aria-hidden="true"
        />
      </div>
    </div>
  )
}
