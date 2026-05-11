import { ArrowRight, MagnifyingGlass } from '@phosphor-icons/react'

interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (query: string) => void
  isLoading: boolean
}

export default function SearchInput({ value, onChange, onSubmit, isLoading }: SearchInputProps) {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (trimmed && !isLoading) onSubmit(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSubmit(e as unknown as React.FormEvent)
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      {/* Input row */}
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

      {/* Submit button */}
      <button
        type="submit"
        disabled={!value.trim() || isLoading}
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
