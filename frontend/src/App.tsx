import { useRef, useState } from 'react'
import SearchInput from './components/SearchInput'
import ResultCard, { type Bike } from './components/ResultCard'
import LoadingCard from './components/LoadingCard'

type AppState = 'idle' | 'loading' | 'results' | 'error'

interface SearchResponse {
  search: string
  bikes: Bike[]
}

export default function App() {
  const [appState, setAppState]             = useState<AppState>('idle')
  const [query, setQuery]                   = useState('')
  const [bikes, setBikes]                   = useState<Bike[]>([])
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [errorMsg, setErrorMsg]             = useState<string | null>(null)
  const resultsRef                          = useRef<HTMLElement>(null)

  const handleSearch = async (searchQuery: string) => {
    setAppState('loading')
    setErrorMsg(null)
    setSubmittedQuery(searchQuery)

    try {
      const res = await fetch('/v1/bike/search', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ search: searchQuery }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Server error ${res.status}`)
      }

      const data: SearchResponse = await res.json()
      setBikes(data.bikes)
      setAppState('results')

      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 80)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setAppState('error')
    }
  }

  const handleReset = () => {
    setAppState('idle')
    setBikes([])
    setErrorMsg(null)
    setQuery('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const showResults = appState === 'loading' || appState === 'results'

  return (
    <div className="min-h-screen bg-sand font-body flex flex-col">
      {/* ── Header ─────────────────────────────────────── */}
      <header className="sticky top-0 z-20 bg-sand/90 backdrop-blur-sm border-b border-border">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button
            onClick={handleReset}
            className="
              -ml-1 px-1 py-2
              font-display font-bold text-xl tracking-[0.18em] text-charcoal
              hover:text-terra focus-visible:text-terra
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 rounded
              transition-colors duration-150
            "
            aria-label="Biker — return to home"
          >
            BIKER
          </button>
          <span
            className="font-mono text-[11px] text-muted uppercase tracking-widest hidden sm:block select-none"
            aria-hidden="true"
          >
            AI Bike Finder
          </span>
        </div>
      </header>

      <main>
        {/* ── Hero / Search ───────────────────────────── */}
        <section className="max-w-2xl mx-auto px-4 sm:px-6 pt-14 pb-10 md:pt-20 md:pb-14" aria-labelledby="hero-heading">
          <div className="mb-9">
            <h1 id="hero-heading" className="font-display font-bold leading-[0.92] tracking-tight text-charcoal text-[52px] sm:text-[68px] md:text-[80px] mb-4">
              Find your<br />
              <span className="text-terra">perfect ride.</span>
            </h1>
            <p className="font-body text-ink text-base md:text-[17px] leading-relaxed max-w-sm">
              Describe what you're looking for and we'll find the best bikes for you.
            </p>
          </div>

          <SearchInput
            value={query}
            onChange={setQuery}
            onSubmit={handleSearch}
            isLoading={appState === 'loading'}
          />

          {appState === 'error' && (
            <div
              role="alert"
              className="mt-4 px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink"
            >
              <strong className="font-medium text-terra">Error: </strong>
              {errorMsg}
            </div>
          )}
        </section>

        {/* ── Results ─────────────────────────────────── */}
        {showResults && (
          <section
            ref={resultsRef}
            className="max-w-2xl mx-auto px-4 sm:px-6 pb-20"
            aria-label="Bike recommendations"
            aria-live="polite"
            aria-busy={appState === 'loading'}
          >
            <div className="border-t border-border pt-8">

              {/* Status row */}
              <div className="flex items-center justify-between mb-6 min-h-[28px]">
                {appState === 'loading' ? (
                  <div className="flex items-center gap-2.5">
                    <span
                      className="spin w-3.5 h-3.5 rounded-full border-2 border-terra/25 border-t-terra shrink-0"
                      aria-hidden="true"
                    />
                    <span className="font-mono text-[11px] text-muted uppercase tracking-wider">
                      Searching for your perfect bike…
                    </span>
                  </div>
                ) : (
                  <div>
                    <span className="font-mono text-[11px] text-muted uppercase tracking-wider block mb-0.5">
                      Results for
                    </span>
                    <p className="font-body text-charcoal text-sm font-medium leading-snug">
                      "{submittedQuery}"
                    </p>
                  </div>
                )}

                {appState === 'results' && (
                  <button
                    onClick={handleReset}
                    aria-label="Start a new search"
                    className="
                      px-2 py-2 -mr-1 shrink-0
                      font-mono text-[11px] text-terra uppercase tracking-wider
                      hover:text-terra-dark
                      focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40 focus-visible:rounded
                      transition-colors duration-150
                    "
                  >
                    New search
                  </button>
                )}
              </div>

              {/* Card list */}
              <div className="space-y-4">
                {appState === 'loading' &&
                  Array.from({ length: 5 }).map((_, i) => (
                    <LoadingCard key={i} delay={i * 90} />
                  ))
                }
                {appState === 'results' &&
                  bikes.map((bike, i) => (
                    <ResultCard
                      key={`${bike.brand}-${bike.model}`}
                      bike={bike}
                      rank={i + 1}
                      isTop={i === 0}
                      animationDelay={i * 65}
                    />
                  ))
                }
              </div>
            </div>
          </section>
        )}
      </main>

      {/* ── Footer ──────────────────────────────────── */}
      <footer className="border-t border-border mt-auto">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 flex items-center justify-between">
          <span className="font-mono text-[11px] text-muted uppercase tracking-wider">
            Biker © {new Date().getFullYear()}
          </span>
          <span className="font-mono text-[11px] text-muted uppercase tracking-wider hidden sm:block">
            Powered by Claude
          </span>
        </div>
      </footer>
    </div>
  )
}
