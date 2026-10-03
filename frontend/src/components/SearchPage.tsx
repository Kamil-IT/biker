import type { RefObject } from 'react'
import SearchInput from './SearchInput'
import ResultCard from './ResultCard'
import LoadingCard from './LoadingCard'
import PopularBikesSection from './PopularBikesSection'
import SortSelect from './SortSelect'
import { bikePath } from '../hooks/useRoute'
import { PENDING_RATING, bikeKey } from '../ratings'
import type { SortOrder } from '../sortBikes'
import type { Bike, ExpertRating, PopularBike, SearchFilters, SearchPayload } from '../types'

export type SearchState = 'idle' | 'loading' | 'results' | 'error'

// Search has no fixed result count (TODO-025), so the skeleton count is neutral.
const LOADING_CARDS = 3

interface SearchPageProps {
  // "/" shows the popular bikes under the form, /search?… the results of its search.
  showResults: boolean
  state: SearchState
  errorMsg: string | null
  noMatchMsg: string | null
  query: string
  onQueryChange: (value: string) => void
  filters: SearchFilters
  onFilterChange: <K extends keyof SearchFilters>(key: K, val: SearchFilters[K]) => void
  showFilters: boolean
  onShowFiltersChange: (v: boolean) => void
  isParsing: boolean
  onSubmit: (payload: SearchPayload) => void
  popularBikes: PopularBike[]
  popularRatings: Record<string, ExpertRating>
  bikes: Bike[]
  // The "Sortuj" select above the results (TODO-040 sorting, rules in sortBikes.ts).
  sortOrder: SortOrder
  onSortChange: (order: SortOrder) => void
  ratings: Record<string, ExpertRating>
  submittedQuery: string
  resultsRef: RefObject<HTMLElement | null>
  onReset: () => void
  onSelectBike: (bike: Bike) => void
}

export default function SearchPage({
  showResults, state, errorMsg, noMatchMsg,
  query, onQueryChange, filters, onFilterChange, showFilters, onShowFiltersChange, isParsing, onSubmit,
  popularBikes, popularRatings, bikes, sortOrder, onSortChange, ratings, submittedQuery, resultsRef, onReset,
  onSelectBike,
}: SearchPageProps) {
  // A /search address opened by link or F5 renders before its search has started.
  const loading = state === 'loading' || state === 'idle'

  return (
    <>
      {/* Hero / Search */}
      <section
        className="max-w-2xl mx-auto px-4 sm:px-6 pt-14 pb-10 md:pt-20 md:pb-14"
        aria-labelledby="hero-heading"
      >
        <div className="mb-9">
          <h1
            id="hero-heading"
            className="font-display font-bold leading-[0.92] tracking-tight text-charcoal text-[52px] sm:text-[68px] md:text-[80px] mb-4"
          >
            Znajdź swój<br />
            <span className="text-terra">idealny rower.</span>
          </h1>
          <p className="font-body text-ink text-base md:text-[17px] leading-relaxed max-w-sm">
            Opisz, czego szukasz, a znajdziemy dla Ciebie najlepsze rowery.
          </p>
        </div>

        {noMatchMsg && (
          <div
            role="alert"
            className="mb-4 px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink"
          >
            <strong className="font-medium text-terra">Nie znaleziono: </strong>
            {noMatchMsg}
          </div>
        )}

        <SearchInput
          value={query}
          onChange={onQueryChange}
          filters={filters}
          onFilterChange={onFilterChange}
          showFilters={showFilters}
          onShowFiltersChange={onShowFiltersChange}
          isParsing={isParsing}
          onSubmit={onSubmit}
          isLoading={showResults && state === 'loading'}
        />

        {showResults && state === 'error' && (
          <div
            role="alert"
            className="mt-4 px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink"
          >
            <strong className="font-medium text-terra">Błąd: </strong>
            {errorMsg}
          </div>
        )}
      </section>

      {/* Popular bikes — home page only */}
      {!showResults && popularBikes.length > 0 && (
        <PopularBikesSection bikes={popularBikes} ratings={popularRatings} onSelect={onSelectBike} />
      )}

      {/* Results */}
      {showResults && state !== 'error' && (
        <section
          ref={resultsRef}
          className="max-w-[68rem] mx-auto px-4 sm:px-6 pb-20"
          aria-label="Rekomendowane rowery"
          aria-live="polite"
          aria-busy={loading}
        >
          <div className="border-t border-border pt-8">

            {/* Status row */}
            <div className="flex items-center justify-between mb-6 min-h-[28px]">
              {loading ? (
                <div className="flex items-center gap-2.5">
                  <span
                    className="spin w-3.5 h-3.5 rounded-full border-2 border-terra/25 border-t-terra shrink-0"
                    aria-hidden="true"
                  />
                  <span className="font-mono text-[11px] text-muted uppercase tracking-wider">
                    Szukamy Twojego idealnego roweru…
                  </span>
                </div>
              ) : (
                <div>
                  <span className="font-mono text-[11px] text-muted uppercase tracking-wider block mb-0.5">
                    Wyniki dla
                  </span>
                  <p className="font-body text-charcoal text-sm font-medium leading-snug">
                    "{submittedQuery}"
                  </p>
                </div>
              )}

              {state === 'results' && (
                <button
                  onClick={onReset}
                  aria-label="Rozpocznij nowe wyszukiwanie"
                  className="
                    px-2 py-2 -mr-1 shrink-0
                    font-mono text-[11px] text-terra uppercase tracking-wider
                    hover:text-terra-dark
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40 focus-visible:rounded
                    transition-colors duration-150
                  "
                >
                  Nowe wyszukiwanie
                </button>
              )}
            </div>

            {/* Sort — pointless for a single bike */}
            {state === 'results' && bikes.length > 1 && (
              <SortSelect value={sortOrder} onChange={onSortChange} />
            )}

            {/* Card list */}
            <div className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(17.5rem,1fr))]">
              {loading &&
                Array.from({ length: LOADING_CARDS }).map((_, i) => (
                  <LoadingCard key={i} delay={i * 90} />
                ))
              }
              {state === 'results' && bikes.length === 0 && (
                <div
                  role="alert"
                  className="col-span-full px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink"
                >
                  <strong className="font-medium text-terra">Nie znaleziono: </strong>
                  Żaden rower nie pasuje do tego wyszukiwania. Spróbuj innych słów lub mniejszej liczby filtrów.
                </div>
              )}
              {state === 'results' &&
                bikes.map((bike, i) => (
                  <ResultCard
                    key={`${bike.brand}-${bike.model}`}
                    bike={bike}
                    rank={i + 1}
                    isTop={false}
                    expertRating={ratings[bikeKey(bike)] ?? PENDING_RATING}
                    animationDelay={Math.min(i, 8) * 65}
                    onSelect={onSelectBike}
                    href={bike.id != null ? bikePath(bike.id) : undefined}
                  />
                ))
              }
            </div>
          </div>
        </section>
      )}
    </>
  )
}
