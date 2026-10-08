import { ArrowRight, CaretDown, MagnifyingGlass, SlidersHorizontal } from '@phosphor-icons/react'
import type { SearchFilters, SearchPayload } from '../types'

interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  filters: SearchFilters
  onFilterChange: <K extends keyof SearchFilters>(key: K, val: SearchFilters[K]) => void
  showFilters: boolean
  onShowFiltersChange: (v: boolean) => void
  isParsing: boolean
  onSubmit: (payload: SearchPayload) => void
  isLoading: boolean
}

const fieldClass =
  'w-full px-3 py-2.5 bg-parchment text-charcoal border border-border rounded-xl font-body text-sm placeholder:text-muted focus:outline-none focus:border-terra focus:ring-2 focus:ring-terra/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200'

const labelClass = 'block font-mono text-[10px] text-muted uppercase tracking-wider mb-1'

const WHEEL_SIZES = ['12"', '14"', '16"', '20"', '24"', '26"', '27.5"', '28"', '29"', '700c', '650b']
const FRAME_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL']

// `value` is what the backend receives and matches against its English data —
// only `label` is translated.
interface Option { value: string; label: string }

// The values are the bike.category codes 1:1 (backend/app/bike_categories.py
// BIKE_CATEGORIES, enforced by the database since TODO-047). Keep the two lists in step;
// the labels match specLabels.ts BIKE_CATEGORY_LABELS.
const BIKE_TYPES: Option[] = [
  { value: 'Road',              label: 'Szosowy' },
  { value: 'MTB',               label: 'Górski (MTB)' },
  { value: 'Gravel',            label: 'Gravel' },
  { value: 'City/Cross/Hybrid', label: 'Miejski / crossowy' },
  { value: 'Touring',           label: 'Trekkingowy' },
  { value: 'BMX',               label: 'BMX' },
  { value: 'Folding',           label: 'Składany' },
  { value: 'Kids',              label: 'Dziecięcy' },
]

export default function SearchInput({
  value, onChange,
  filters, onFilterChange,
  showFilters, onShowFiltersChange,
  isParsing,
  onSubmit, isLoading,
}: SearchInputProps) {

  const f = filters

  const hasAny = !!(
    value.trim() ||
    f.brand.trim() || f.model.trim() || f.year.trim() || f.wheel_size ||
    f.bike_type || f.frame_size ||
    f.is_electric !== undefined
  )

  const buildPayload = (): SearchPayload => {
    const p: SearchPayload = {}
    if (value.trim())                p.search              = value.trim()
    if (f.brand.trim())              p.brand               = f.brand.trim()
    if (f.model.trim())              p.model               = f.model.trim()
    if (f.year.trim())               p.year                = parseInt(f.year, 10)
    if (f.bike_type)                 p.bike_type           = f.bike_type
    if (f.wheel_size)                p.wheel_size          = f.wheel_size
    if (f.frame_size)                p.frame_size          = f.frame_size
    if (f.is_electric !== undefined)    p.is_electric      = f.is_electric
    return p
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!hasAny || isLoading || isParsing) return
    onSubmit(buildPayload())
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSubmit(e as unknown as React.FormEvent)
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      {/* Main search input */}
      <div className="relative">
        <label htmlFor="bike-search" className="sr-only">
          Opisz swój idealny rower
        </label>
        <MagnifyingGlass
          className="absolute left-4 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
          size={18}
          aria-hidden="true"
        />
        <input
          id="bike-search"
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Kross, Romet, Ecobike, Trek Madone..."
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

      {/* Filters toggle */}
      <button
        type="button"
        onClick={() => onShowFiltersChange(!showFilters)}
        aria-expanded={showFilters}
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

      {/* Filters panel */}
      {showFilters && (
        <div className="mt-3">
          {/* ── Basic group ─────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="bike-brand" className={labelClass}>Marka</label>
              <input
                id="bike-brand"
                type="text"
                value={f.brand}
                onChange={e => onFilterChange('brand', e.target.value)}
                placeholder="np. Trek, Specialized"
                disabled={isLoading}
                autoComplete="off"
                className={fieldClass}
              />
            </div>

            <div>
              <label htmlFor="bike-model" className={labelClass}>Model</label>
              <input
                id="bike-model"
                type="text"
                value={f.model}
                onChange={e => onFilterChange('model', e.target.value)}
                placeholder="np. Marlin 7, Diverge"
                disabled={isLoading}
                autoComplete="off"
                className={fieldClass}
              />
            </div>

            <div>
              <label htmlFor="bike-type" className={labelClass}>Typ roweru</label>
              <select
                id="bike-type"
                value={f.bike_type}
                onChange={e => onFilterChange('bike_type', e.target.value)}
                disabled={isLoading}
                className={`${fieldClass} appearance-none`}
              >
                <option value="">Dowolny</option>
                {BIKE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>

            <div>
              <label htmlFor="bike-year" className={labelClass}>Rok</label>
              <input
                id="bike-year"
                type="number"
                value={f.year}
                onChange={e => onFilterChange('year', e.target.value)}
                placeholder="np. 2022"
                min={1990}
                max={2030}
                disabled={isLoading}
                className={fieldClass}
              />
            </div>

            <div>
              <label htmlFor="bike-wheel" className={labelClass}>Rozmiar kół</label>
              <select
                id="bike-wheel"
                value={f.wheel_size}
                onChange={e => onFilterChange('wheel_size', e.target.value)}
                disabled={isLoading}
                className={`${fieldClass} appearance-none`}
              >
                <option value="">Dowolny</option>
                {WHEEL_SIZES.map(w => <option key={w} value={w}>{w}</option>)}
              </select>
            </div>

            <div>
              <label htmlFor="bike-frame-size" className={labelClass}>Rozmiar ramy</label>
              <select
                id="bike-frame-size"
                value={f.frame_size}
                onChange={e => onFilterChange('frame_size', e.target.value)}
                disabled={isLoading}
                className={`${fieldClass} appearance-none`}
              >
                <option value="">Dowolny</option>
                {FRAME_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          {/* Basic toggles */}
          <div className="flex flex-col gap-2.5 pt-3">
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={f.is_electric === true}
                onChange={e => onFilterChange('is_electric', e.target.checked ? true : undefined)}
                disabled={isLoading}
                className="w-4 h-4 accent-terra rounded"
              />
              <span className="font-body text-sm text-ink">Tylko rowery elektryczne (e-bike)</span>
            </label>
          </div>
        </div>
      )}

      {/* Submit button */}
      <button
        type="submit"
        disabled={!hasAny || isLoading || isParsing}
        aria-label={isLoading ? 'Szukamy rekomendacji rowerów' : isParsing ? 'Odczytujemy pola z Twojego tekstu' : 'Znajdź rekomendacje rowerów'}
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
        {isLoading ? (
          <>
            <span
              className="spin w-4 h-4 rounded-full border-2 border-parchment/30 border-t-parchment"
              aria-hidden="true"
            />
            Analizuję…
          </>
        ) : isParsing ? (
          <>
            <span
              className="spin w-4 h-4 rounded-full border-2 border-parchment/30 border-t-parchment"
              aria-hidden="true"
            />
            Odczytuję pola…
          </>
        ) : (
          <>
            Znajdź mój rower
            <ArrowRight size={17} weight="bold" aria-hidden="true" />
          </>
        )}
      </button>
    </form>
  )
}
