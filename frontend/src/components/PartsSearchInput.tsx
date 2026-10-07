import { ArrowRight, CaretDown, MagnifyingGlass, SlidersHorizontal } from '@phosphor-icons/react'
import { PART_TYPES } from '../partTypes'
import type { PartsFilters, PartsSearchPayload, PartType } from '../types'

interface PartsSearchInputProps {
  value: string
  onChange: (value: string) => void
  filters: PartsFilters
  onFilterChange: <K extends keyof PartsFilters>(key: K, val: PartsFilters[K]) => void
  showFilters: boolean
  onShowFiltersChange: (v: boolean) => void
  isParsing: boolean
  onSubmit: (payload: PartsSearchPayload) => void
  isLoading: boolean
}

const fieldClass =
  'w-full px-3 py-2.5 bg-parchment text-charcoal border border-border rounded-xl font-body text-sm placeholder:text-muted focus:outline-none focus:border-terra focus:ring-2 focus:ring-terra/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200'

const labelClass = 'block font-mono text-[10px] text-muted uppercase tracking-wider mb-1'

// The parts search form (TODO-046): free text + the "Filtry" panel — part type, brand, model,
// groupset. No type-specific parameters (speeds, rotor mount …): out of scope for now. The
// bike search's SearchInput is the model; this is its own file so neither grows past 500 lines.
export default function PartsSearchInput({
  value, onChange, filters: f, onFilterChange, showFilters, onShowFiltersChange, isParsing, onSubmit, isLoading,
}: PartsSearchInputProps) {
  const hasAny = !!(value.trim() || f.part_type || f.brand.trim() || f.model.trim() || f.groupset.trim())

  const buildPayload = (): PartsSearchPayload => {
    const p: PartsSearchPayload = {}
    if (value.trim())      p.search    = value.trim()
    if (f.part_type)       p.part_type = f.part_type
    if (f.brand.trim())    p.brand     = f.brand.trim()
    if (f.model.trim())    p.model     = f.model.trim()
    if (f.groupset.trim()) p.groupset  = f.groupset.trim()
    return p
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!hasAny || isLoading || isParsing) return
    onSubmit(buildPayload())
  }

  const text = (id: string, key: 'brand' | 'model' | 'groupset', label: string, placeholder: string, max: number) => (
    <div>
      <label htmlFor={id} className={labelClass}>{label}</label>
      <input
        id={id}
        type="text"
        value={f[key]}
        onChange={e => onFilterChange(key, e.target.value)}
        placeholder={placeholder}
        maxLength={max}
        disabled={isLoading}
        autoComplete="off"
        className={fieldClass}
      />
    </div>
  )

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div className="relative">
        <label htmlFor="parts-search" className="sr-only">Jakiej części szukasz?</label>
        <MagnifyingGlass
          className="absolute left-4 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
          size={18}
          aria-hidden="true"
        />
        <input
          id="parts-search"
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="np. kaseta 12 rzędów Shimano 10-51, tarcza 180 mm Center Lock"
          maxLength={500}
          disabled={isLoading}
          autoComplete="off"
          autoFocus
          className="
            w-full pl-11 pr-4 py-4
            bg-parchment text-charcoal
            border border-border rounded-xl
            font-body text-base leading-snug
            placeholder:text-muted placeholder:font-body
            focus:outline-none focus:border-terra focus:ring-2 focus:ring-terra/20
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-colors duration-200
          "
        />
      </div>

      <button
        type="button"
        onClick={() => onShowFiltersChange(!showFilters)}
        aria-expanded={showFilters}
        aria-controls="parts-filters"
        className="mt-2 flex items-center gap-1.5 font-mono text-[11px] text-muted uppercase tracking-wider hover:text-terra transition-colors duration-150"
      >
        <SlidersHorizontal size={13} aria-hidden="true" />
        {showFilters ? 'Ukryj filtry' : 'Filtry'}
        <CaretDown
          size={12}
          aria-hidden="true"
          style={{ transform: showFilters ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 150ms' }}
        />
      </button>

      {showFilters && (
        <div id="parts-filters" className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label htmlFor="part-type" className={labelClass}>Typ części</label>
            <select
              id="part-type"
              value={f.part_type}
              onChange={e => onFilterChange('part_type', e.target.value as PartType | '')}
              disabled={isLoading}
              className={`${fieldClass} appearance-none`}
            >
              <option value="">Dowolny</option>
              {PART_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          {text('part-brand', 'brand', 'Marka', 'np. Shimano, SRAM', 255)}
          {text('part-model', 'model', 'Model', 'np. CS-M6100-12', 255)}
          {text('part-group', 'groupset', 'Grupa osprzętu', 'np. Deore, GRX, GX Eagle', 128)}
        </div>
      )}

      <button
        type="submit"
        disabled={!hasAny || isLoading || isParsing}
        aria-label={isLoading ? 'Szukamy części' : isParsing ? 'Odczytujemy pola z Twojego tekstu' : 'Szukaj części'}
        className="
          mt-3 w-full flex items-center justify-center gap-2.5
          py-4 px-8
          bg-terra text-parchment
          font-display font-bold text-lg tracking-widest uppercase
          rounded-xl
          hover:bg-terra-dark
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra focus-visible:ring-offset-2 focus-visible:ring-offset-sand
          disabled:opacity-40 disabled:cursor-not-allowed
          active:scale-[0.985]
          transition-all duration-150
        "
      >
        {isLoading || isParsing ? (
          <>
            <span className="spin w-4 h-4 rounded-full border-2 border-parchment/30 border-t-parchment" aria-hidden="true" />
            {isLoading ? 'Szukam…' : 'Odczytuję pola…'}
          </>
        ) : (
          <>
            Szukaj części
            <ArrowRight size={17} weight="bold" aria-hidden="true" />
          </>
        )}
      </button>
    </form>
  )
}
