import { ArrowRight, CaretDown, MagnifyingGlass, SlidersHorizontal } from '@phosphor-icons/react'
import type { SearchFilters, SearchPayload } from '../types'

interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  filters: SearchFilters
  onFilterChange: <K extends keyof SearchFilters>(key: K, val: SearchFilters[K]) => void
  showFilters: boolean
  onShowFiltersChange: (v: boolean) => void
  showAdvanced: boolean
  onShowAdvancedChange: (v: boolean) => void
  isParsing: boolean
  onSubmit: (payload: SearchPayload) => void
  isLoading: boolean
}

const fieldClass =
  'w-full px-3 py-2.5 bg-parchment text-charcoal border border-border rounded-xl font-body text-sm placeholder:text-muted focus:outline-none focus:border-terra focus:ring-2 focus:ring-terra/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200'

const labelClass = 'block font-mono text-[10px] text-muted uppercase tracking-wider mb-1'

const WHEEL_SIZES = ['12"', '14"', '16"', '20"', '24"', '26"', '27.5"', '28"', '29"', '700c', '650b']
const BIKE_TYPES = ['Road', 'MTB', 'Gravel', 'Hybrid/Commuter', 'Touring', 'BMX', 'Cruiser', 'Folding']
const FRAME_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL']
const GENDERS = ['Male', 'Female', 'Universal']
const FRAME_MATERIALS = ['Aluminum', 'Carbon', 'Steel']
const BRAKE_TYPES = ['Hydraulic Disc', 'Mechanical Disc', 'V-brake', 'Rim']
const DRIVETRAINS = ['1x', '2x', '3x']

export default function SearchInput({
  value, onChange,
  filters, onFilterChange,
  showFilters, onShowFiltersChange,
  showAdvanced, onShowAdvancedChange,
  isParsing,
  onSubmit, isLoading,
}: SearchInputProps) {

  const f = filters

  const hasAny = !!(
    value.trim() ||
    f.brand.trim() || f.model.trim() || f.year.trim() || f.wheel_size ||
    f.bike_type || f.frame_size || f.rider_height_cm.trim() || f.price_max.trim() ||
    f.gender || f.frame_material || f.brake_type || f.drivetrain ||
    f.battery_capacity_wh.trim() ||
    f.is_electric !== undefined || f.has_suspension !== undefined ||
    f.is_kids !== undefined || f.belt_drive !== undefined
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
    if (f.rider_height_cm.trim())    p.rider_height_cm     = parseInt(f.rider_height_cm, 10)
    if (f.price_max.trim())          p.price_max           = parseInt(f.price_max, 10)
    if (f.gender)                    p.gender              = f.gender
    if (f.frame_material)            p.frame_material      = f.frame_material
    if (f.brake_type)                p.brake_type          = f.brake_type
    if (f.drivetrain)                p.drivetrain          = f.drivetrain
    if (f.is_electric !== undefined)    p.is_electric      = f.is_electric
    if (f.has_suspension !== undefined) p.has_suspension   = f.has_suspension
    if (f.is_kids !== undefined)        p.is_kids          = f.is_kids
    if (f.belt_drive !== undefined)     p.belt_drive       = f.belt_drive
    if (f.is_electric === true && f.battery_capacity_wh.trim())
      p.battery_capacity_wh = parseInt(f.battery_capacity_wh, 10)
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
          Describe your ideal bike
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
          placeholder="e.g. comfortable bike for daily 10 km city commute, mostly paved roads…"
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
        {showFilters ? 'Hide filters' : 'Filters'}
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
              <label htmlFor="bike-brand" className={labelClass}>Brand</label>
              <input
                id="bike-brand"
                type="text"
                value={f.brand}
                onChange={e => onFilterChange('brand', e.target.value)}
                placeholder="e.g. Trek, Specialized"
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
                placeholder="e.g. Marlin 7, Diverge"
                disabled={isLoading}
                autoComplete="off"
                className={fieldClass}
              />
            </div>

            <div>
              <label htmlFor="bike-type" className={labelClass}>Bike type</label>
              <select
                id="bike-type"
                value={f.bike_type}
                onChange={e => onFilterChange('bike_type', e.target.value)}
                disabled={isLoading}
                className={`${fieldClass} appearance-none`}
              >
                <option value="">Any</option>
                {BIKE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            <div>
              <label htmlFor="bike-year" className={labelClass}>Year</label>
              <input
                id="bike-year"
                type="number"
                value={f.year}
                onChange={e => onFilterChange('year', e.target.value)}
                placeholder="e.g. 2022"
                min={1990}
                max={2030}
                disabled={isLoading}
                className={fieldClass}
              />
            </div>

            <div>
              <label htmlFor="bike-wheel" className={labelClass}>Wheel size</label>
              <select
                id="bike-wheel"
                value={f.wheel_size}
                onChange={e => onFilterChange('wheel_size', e.target.value)}
                disabled={isLoading}
                className={`${fieldClass} appearance-none`}
              >
                <option value="">Any</option>
                {WHEEL_SIZES.map(w => <option key={w} value={w}>{w}</option>)}
              </select>
            </div>

            <div>
              <label htmlFor="bike-frame-size" className={labelClass}>Frame size</label>
              <select
                id="bike-frame-size"
                value={f.frame_size}
                onChange={e => onFilterChange('frame_size', e.target.value)}
                disabled={isLoading}
                className={`${fieldClass} appearance-none`}
              >
                <option value="">Any</option>
                {FRAME_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>

            <div>
              <label htmlFor="bike-rider-height" className={labelClass}>Rider height (cm)</label>
              <input
                id="bike-rider-height"
                type="number"
                value={f.rider_height_cm}
                onChange={e => onFilterChange('rider_height_cm', e.target.value)}
                placeholder="80–210"
                min={80}
                max={210}
                disabled={isLoading}
                className={fieldClass}
              />
            </div>

            <div>
              <label htmlFor="bike-price-max" className={labelClass}>Max price (PLN)</label>
              <input
                id="bike-price-max"
                type="number"
                value={f.price_max}
                onChange={e => onFilterChange('price_max', e.target.value)}
                placeholder="e.g. 5000"
                min={0}
                disabled={isLoading}
                className={fieldClass}
              />
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
              <span className="font-body text-sm text-ink">Electric bike (e-bike) only</span>
            </label>
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={f.has_suspension === true}
                onChange={e => onFilterChange('has_suspension', e.target.checked ? true : undefined)}
                disabled={isLoading}
                className="w-4 h-4 accent-terra rounded"
              />
              <span className="font-body text-sm text-ink">Has suspension (front or full)</span>
            </label>
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={f.is_kids === true}
                onChange={e => onFilterChange('is_kids', e.target.checked ? true : undefined)}
                disabled={isLoading}
                className="w-4 h-4 accent-terra rounded"
              />
              <span className="font-body text-sm text-ink">Kids bike</span>
            </label>
          </div>

          {/* ── Advanced sub-toggle ───────────────────── */}
          <button
            type="button"
            onClick={() => onShowAdvancedChange(!showAdvanced)}
            aria-expanded={showAdvanced}
            className="mt-4 flex items-center gap-1.5 font-mono text-[11px] text-muted uppercase tracking-wider hover:text-terra transition-colors duration-150"
          >
            <CaretDown
              size={12}
              aria-hidden="true"
              style={{ transform: showAdvanced ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 150ms' }}
            />
            {showAdvanced ? 'Fewer advanced options' : 'Advanced options'}
          </button>

          {/* ── Advanced group ────────────────────────── */}
          {showAdvanced && (
            <div className="mt-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label htmlFor="bike-gender" className={labelClass}>Gender</label>
                  <select
                    id="bike-gender"
                    value={f.gender}
                    onChange={e => onFilterChange('gender', e.target.value)}
                    disabled={isLoading}
                    className={`${fieldClass} appearance-none`}
                  >
                    <option value="">Any</option>
                    {GENDERS.map(g => <option key={g} value={g}>{g}</option>)}
                  </select>
                </div>

                <div>
                  <label htmlFor="bike-frame-material" className={labelClass}>Frame material</label>
                  <select
                    id="bike-frame-material"
                    value={f.frame_material}
                    onChange={e => onFilterChange('frame_material', e.target.value)}
                    disabled={isLoading}
                    className={`${fieldClass} appearance-none`}
                  >
                    <option value="">Any</option>
                    {FRAME_MATERIALS.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>

                <div>
                  <label htmlFor="bike-brake-type" className={labelClass}>Brake type</label>
                  <select
                    id="bike-brake-type"
                    value={f.brake_type}
                    onChange={e => onFilterChange('brake_type', e.target.value)}
                    disabled={isLoading}
                    className={`${fieldClass} appearance-none`}
                  >
                    <option value="">Any</option>
                    {BRAKE_TYPES.map(b => <option key={b} value={b}>{b}</option>)}
                  </select>
                </div>

                <div>
                  <label htmlFor="bike-drivetrain" className={labelClass}>Drivetrain</label>
                  <select
                    id="bike-drivetrain"
                    value={f.drivetrain}
                    onChange={e => onFilterChange('drivetrain', e.target.value)}
                    disabled={isLoading}
                    className={`${fieldClass} appearance-none`}
                  >
                    <option value="">Any</option>
                    {DRIVETRAINS.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>

                {f.is_electric === true && (
                  <div>
                    <label htmlFor="bike-battery" className={labelClass}>Battery capacity (Wh)</label>
                    <input
                      id="bike-battery"
                      type="number"
                      value={f.battery_capacity_wh}
                      onChange={e => onFilterChange('battery_capacity_wh', e.target.value)}
                      placeholder="e.g. 500"
                      min={0}
                      disabled={isLoading}
                      className={fieldClass}
                    />
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-2.5 pt-3">
                <label className="flex items-center gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={f.belt_drive === true}
                    onChange={e => onFilterChange('belt_drive', e.target.checked ? true : undefined)}
                    disabled={isLoading}
                    className="w-4 h-4 accent-terra rounded"
                  />
                  <span className="font-body text-sm text-ink">Belt drive (no chain)</span>
                </label>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Submit button */}
      <button
        type="submit"
        disabled={!hasAny || isLoading || isParsing}
        aria-label={isLoading ? 'Searching for bike recommendations' : isParsing ? 'Extracting fields from your text' : 'Find bike recommendations'}
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
            Analysing…
          </>
        ) : isParsing ? (
          <>
            <span
              className="spin w-4 h-4 rounded-full border-2 border-parchment/30 border-t-parchment"
              aria-hidden="true"
            />
            Extracting fields…
          </>
        ) : (
          <>
            Find my bike
            <ArrowRight size={17} weight="bold" aria-hidden="true" />
          </>
        )}
      </button>
    </form>
  )
}
