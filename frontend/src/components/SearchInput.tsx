import { useState } from 'react'
import { ArrowRight, CaretDown, MagnifyingGlass } from '@phosphor-icons/react'
import type { SearchPayload } from '../types'

interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  brand: string
  onBrandChange: (v: string) => void
  model: string
  onModelChange: (v: string) => void
  year: string
  onYearChange: (v: string) => void
  wheelSize: string
  onWheelSizeChange: (v: string) => void
  isElectric: boolean | undefined
  onIsElectricChange: (v: boolean | undefined) => void
  hasSuspension: boolean | undefined
  onHasSuspensionChange: (v: boolean | undefined) => void
  isKids: boolean | undefined
  onIsKidsChange: (v: boolean | undefined) => void
  onSubmit: (payload: SearchPayload) => void
  isLoading: boolean
}

const fieldClass =
  'w-full px-3 py-2.5 bg-parchment text-charcoal border border-border rounded-xl font-body text-sm placeholder:text-muted focus:outline-none focus:border-terra focus:ring-2 focus:ring-terra/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200'

const labelClass = 'block font-mono text-[10px] text-muted uppercase tracking-wider mb-1'

export default function SearchInput({
  value, onChange,
  brand, onBrandChange,
  model, onModelChange,
  year, onYearChange,
  wheelSize, onWheelSizeChange,
  isElectric, onIsElectricChange,
  hasSuspension, onHasSuspensionChange,
  isKids, onIsKidsChange,
  onSubmit, isLoading,
}: SearchInputProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  const hasAny = !!(
    value.trim() || brand.trim() || model.trim() || year.trim() ||
    wheelSize || isElectric !== undefined || hasSuspension !== undefined || isKids !== undefined
  )

  const buildPayload = (): SearchPayload => {
    const p: SearchPayload = {}
    if (value.trim())                p.search          = value.trim()
    if (brand.trim())                p.brand           = brand.trim()
    if (model.trim())                p.model           = model.trim()
    if (year.trim())                 p.year            = parseInt(year, 10)
    if (wheelSize)                   p.wheel_size      = wheelSize
    if (isElectric !== undefined)    p.is_electric     = isElectric
    if (hasSuspension !== undefined) p.has_suspension  = hasSuspension
    if (isKids !== undefined)        p.is_kids         = isKids
    return p
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!hasAny || isLoading) return
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

      {/* Advanced toggle */}
      <button
        type="button"
        onClick={() => setShowAdvanced(p => !p)}
        className="mt-2 flex items-center gap-1.5 font-mono text-[11px] text-muted uppercase tracking-wider hover:text-terra transition-colors duration-150"
      >
        <CaretDown
          size={12}
          aria-hidden="true"
          style={{ transform: showAdvanced ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 150ms' }}
        />
        {showAdvanced ? 'Fewer options' : 'More options'}
      </button>

      {/* Advanced fields */}
      {showAdvanced && (
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label htmlFor="bike-brand" className={labelClass}>Brand</label>
            <input
              id="bike-brand"
              type="text"
              value={brand}
              onChange={e => onBrandChange(e.target.value)}
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
              value={model}
              onChange={e => onModelChange(e.target.value)}
              placeholder="e.g. Marlin 7, Diverge"
              disabled={isLoading}
              autoComplete="off"
              className={fieldClass}
            />
          </div>

          <div>
            <label htmlFor="bike-year" className={labelClass}>Year</label>
            <input
              id="bike-year"
              type="number"
              value={year}
              onChange={e => onYearChange(e.target.value)}
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
              value={wheelSize}
              onChange={e => onWheelSizeChange(e.target.value)}
              disabled={isLoading}
              className={`${fieldClass} appearance-none`}
            >
              <option value="">Any</option>
              <option value='26"'>26"</option>
              <option value='27.5"'>27.5"</option>
              <option value='29"'>29"</option>
              <option value="700c">700c</option>
              <option value="650b">650b</option>
            </select>
          </div>

          <div className="sm:col-span-2 flex flex-col gap-2.5 pt-0.5">
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isElectric === true}
                onChange={e => onIsElectricChange(e.target.checked ? true : undefined)}
                disabled={isLoading}
                className="w-4 h-4 accent-terra rounded"
              />
              <span className="font-body text-sm text-ink">Electric bike (e-bike) only</span>
            </label>
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={hasSuspension === true}
                onChange={e => onHasSuspensionChange(e.target.checked ? true : undefined)}
                disabled={isLoading}
                className="w-4 h-4 accent-terra rounded"
              />
              <span className="font-body text-sm text-ink">Has suspension (front or full)</span>
            </label>
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isKids === true}
                onChange={e => onIsKidsChange(e.target.checked ? true : undefined)}
                disabled={isLoading}
                className="w-4 h-4 accent-terra rounded"
              />
              <span className="font-body text-sm text-ink">Kids bike</span>
            </label>
          </div>
        </div>
      )}

      {/* Submit button */}
      <button
        type="submit"
        disabled={!hasAny || isLoading}
        aria-label={isLoading ? 'Searching for bike recommendations' : 'Find bike recommendations'}
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
