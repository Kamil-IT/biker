import PartsSearchInput from './PartsSearchInput'
import PartCard from './PartCard'
import LoadingCard from './LoadingCard'
import SortSelect from './SortSelect'
import AiSearchCard from './AiSearchCard'
import type { PartsSearch } from '../hooks/usePartsSearch'
import { PART_SORT_OPTIONS } from '../sortParts'
import type { PartResult } from '../types'

const LOADING_CARDS = 3  // the catalogue search has no fixed result count
const AI_LOADING_CARDS = 4

const plural = (n: number) => (n === 1 ? 'część' : 'części')

interface PartsSearchPageProps {
  // "/parts" is the start page (the form only), "/parts?…" the results of its search.
  showResults: boolean
  // The form, results and AI search state and handlers (hooks/usePartsSearch.ts).
  search: PartsSearch
  onSelectPart: (part: PartResult) => void
}

function Alert({ title, children, className = '' }: { title: string; children: string; className?: string }) {
  return (
    <div role="alert" className={`px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink ${className}`}>
      <strong className="font-medium text-terra">{title} </strong>
      {children}
    </div>
  )
}

// The "Wyszukiwanie części" tab (TODO-046; mockup docs/mockups/wyszukiwanie-czesci/). The
// catalogue search answers from the DB; under an EMPTY list only, the "Szukaj więcej z AI"
// card offers the paid web search, which adds what it finds to the catalogue.
export default function PartsSearchPage({ showResults, search, onSelectPart }: PartsSearchPageProps) {
  const {
    state, errorMsg, noMatchMsg, query, setQuery, filters, updateFilter, showFilters, setShowFilters, isParsing,
    handleSearch, parts, label, source, aiTried, aiState, aiError, searchAi, sortOrder, setSortOrder, resultsRef,
  } = search
  // An address opened by link or F5 renders before its search has started.
  const loading = state === 'loading' || state === 'idle'
  const aiRunning = aiState === 'running'
  const found = parts.length

  const heading = aiRunning ? 'Szukamy w sieci'
    : found > 0 ? `Znaleźliśmy ${found} ${plural(found)}`
    : 'Nie znaleźliśmy żadnej części'
  const newCount = parts.filter(p => p.is_new).length
  const line = aiRunning ? 'Znalezione części dopiszemy do katalogu — to potrwa do ok. 40 s.'
    : found > 0 && source === 'ai'
      ? `W sieci, dla „${label}”.${newCount === found ? ' Dodaliśmy je do katalogu.' : newCount > 0 ? ' Nowe dopisaliśmy do katalogu.' : ''}`
    : found > 0 ? `W katalogu, dla „${label}”.`
    : aiTried ? `Ani w katalogu, ani w sieci, dla „${label}”.`
    : `W katalogu nie ma nic dla „${label}”.`

  return (
    <>
      <section className="max-w-2xl mx-auto px-4 sm:px-6 pt-14 pb-10 md:pt-20 md:pb-14" aria-labelledby="parts-hero-heading">
        <div className="mb-9">
          <h1
            id="parts-hero-heading"
            className="font-display font-bold leading-[0.92] tracking-tight text-charcoal text-[52px] sm:text-[68px] md:text-[80px] mb-4"
          >
            Znajdź<br />
            <span className="text-terra">właściwą część.</span>
          </h1>
          <p className="font-body text-ink text-base md:text-[17px] leading-relaxed max-w-md">
            Opisz część albo wybierz jej typ i markę. Jeśli nie mamy jej w katalogu, możemy poszukać w sieci.
          </p>
        </div>

        {noMatchMsg && <Alert title="Nie znaleziono:" className="mb-4">{noMatchMsg}</Alert>}

        <PartsSearchInput
          value={query}
          onChange={setQuery}
          filters={filters}
          onFilterChange={updateFilter}
          showFilters={showFilters}
          onShowFiltersChange={setShowFilters}
          isParsing={isParsing}
          onSubmit={handleSearch}
          isLoading={showResults && state === 'loading'}
        />

        {showResults && state === 'error' && errorMsg && <Alert title="Błąd:" className="mt-4">{errorMsg}</Alert>}
      </section>

      {showResults && state !== 'error' && (
        <section
          ref={resultsRef}
          className="max-w-[68rem] mx-auto px-4 sm:px-6 pb-20"
          aria-labelledby="parts-results-heading"
          aria-live="polite"
          aria-busy={loading || aiRunning}
        >
          <div className="border-t border-border pt-8">
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 mb-5 min-h-[28px]">
              {loading ? (
                <div className="flex items-center gap-2.5">
                  <span className="spin w-3.5 h-3.5 rounded-full border-2 border-terra/25 border-t-terra shrink-0" aria-hidden="true" />
                  <span id="parts-results-heading" className="font-mono text-[11px] text-muted uppercase tracking-wider">
                    Szukamy części w katalogu…
                  </span>
                </div>
              ) : (
                <div>
                  <h2 id="parts-results-heading" className="font-display font-bold text-[1.6rem] leading-[1.1] text-charcoal">
                    {heading}
                  </h2>
                  <p className="mt-1 font-body text-[15px] text-ink max-w-[38rem]">{line}</p>
                </div>
              )}
              {state === 'results' && (
                <button
                  onClick={() => search.reset(true)}
                  aria-label="Rozpocznij nowe wyszukiwanie części"
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

            {state === 'results' && found > 1 && (
              <SortSelect value={sortOrder} onChange={setSortOrder} options={PART_SORT_OPTIONS} />
            )}

            {(loading || found > 0 || aiRunning) && (
              <ul className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(17.5rem,1fr))] m-0 p-0 list-none">
                {loading && Array.from({ length: LOADING_CARDS }).map((_, i) => (
                  <li key={i}><LoadingCard delay={i * 90} plate={false} /></li>
                ))}
                {state === 'results' && parts.map((part, i) => (
                  <li key={part.id}>
                    <PartCard part={part} animationDelay={Math.min(i, 8) * 65} onSelect={onSelectPart} />
                  </li>
                ))}
                {state === 'results' && aiRunning && Array.from({ length: AI_LOADING_CARDS }).map((_, i) => (
                  <li key={`ai-${i}`}><LoadingCard delay={i * 90} plate={false} /></li>
                ))}
              </ul>
            )}

            {/* Only under an empty list — never under results. */}
            {state === 'results' && found === 0 && (
              <div className={aiRunning ? 'mt-6' : ''}>
                {aiState === 'error' && aiError && <Alert title="Błąd:" className="mb-4">{aiError}</Alert>}
                <AiSearchCard running={aiRunning} onSearch={searchAi} />
              </div>
            )}
          </div>
        </section>
      )}
    </>
  )
}
