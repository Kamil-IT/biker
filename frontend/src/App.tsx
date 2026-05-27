import { useRef, useState } from 'react'
import SearchInput from './components/SearchInput'
import ResultCard from './components/ResultCard'
import LoadingCard from './components/LoadingCard'
import BikeDetailsView from './components/BikeDetailsView'
import type { Bike, BikeCategory, BikeDescription, BikeDetailsResponse, BikeReviewResponse, BikeOfferResponse, UsedBikeResponse } from './types'

type AppState     = 'idle' | 'loading' | 'results' | 'error'
type AppView      = 'search' | 'details'
type DetailsState = 'loading' | 'loaded' | 'error'
type ReviewState  = 'loading' | 'loaded' | 'error'
type OfferState   = 'loading' | 'loaded' | 'error'
type UsedBikeState = 'loading' | 'loaded' | 'error'

interface SearchResponse {
  search: string
  bikes: Bike[]
}

export default function App() {
  // Search state
  const [appState, setAppState]             = useState<AppState>('idle')
  const [query, setQuery]                   = useState('')
  const [bikes, setBikes]                   = useState<Bike[]>([])
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [errorMsg, setErrorMsg]             = useState<string | null>(null)
  const resultsRef                          = useRef<HTMLElement>(null)

  // Details state
  const [view, setView]                         = useState<AppView>('search')
  const [selectedBike, setSelectedBike]         = useState<Bike | null>(null)
  const [detailsState, setDetailsState]         = useState<DetailsState>('loading')
  const [bikeCategories, setBikeCategories]     = useState<BikeCategory[] | null>(null)
  const [bikeDescription, setBikeDescription]   = useState<BikeDescription | null>(null)
  const [bikePhotos, setBikePhotos]             = useState<string[]>([])
  const [detailsError, setDetailsError]         = useState<string | null>(null)

  // Review state
  const [reviewState, setReviewState]       = useState<ReviewState>('loading')
  const [review, setReview]                 = useState<BikeReviewResponse | null>(null)

  // Offer state
  const [offerState, setOfferState]         = useState<OfferState>('loading')
  const [offers, setOffers]                 = useState<BikeOfferResponse | null>(null)

  // Used bikes (OLX) state
  const [usedBikeState, setUsedBikeState]   = useState<UsedBikeState>('loading')
  const [usedBikes, setUsedBikes]           = useState<UsedBikeResponse | null>(null)

  /* ── Handlers ─────────────────────────────────────── */

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

  const fetchDetails = async (bike: Bike) => {
    setDetailsState('loading')
    setDetailsError(null)
    setBikeCategories(null)
    setBikeDescription(null)
    setBikePhotos([])

    try {
      const res = await fetch('/v1/bike/details', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Server error ${res.status}`)
      }

      const data: BikeDetailsResponse = await res.json()
      setBikeCategories(data.components)
      setBikeDescription(data.description ?? null)
      setBikePhotos(data.photos ?? [])
      setDetailsState('loaded')
    } catch (err) {
      setDetailsError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setDetailsState('error')
    }
  }

  const fetchReview = async (bike: Bike) => {
    setReviewState('loading')
    setReview(null)
    try {
      const res = await fetch('/v1/bike/review', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data: BikeReviewResponse = await res.json()
      setReview(data)
      setReviewState('loaded')
    } catch {
      setReviewState('error')
    }
  }

  const fetchOffer = async (bike: Bike) => {
    setOfferState('loading')
    setOffers(null)
    try {
      const res = await fetch('/v1/bike/offer', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data: BikeOfferResponse = await res.json()
      setOffers(data)
      setOfferState('loaded')
    } catch {
      setOfferState('error')
    }
  }

  const fetchUsedBikes = async (bike: Bike) => {
    setUsedBikeState('loading')
    setUsedBikes(null)
    try {
      const res = await fetch('/v1/bike/used', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data: UsedBikeResponse = await res.json()
      setUsedBikes(data)
      setUsedBikeState('loaded')
    } catch {
      setUsedBikeState('error')
    }
  }

  const handleBikeSelect = (bike: Bike) => {
    setSelectedBike(bike)
    setView('details')
    window.scrollTo({ top: 0, behavior: 'smooth' })
    fetchDetails(bike)
    fetchReview(bike)
    fetchOffer(bike)
    fetchUsedBikes(bike)
  }

  const handleBackToResults = () => {
    setView('search')
    setTimeout(() => {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 80)
  }

  const handleReset = () => {
    setAppState('idle')
    setBikes([])
    setErrorMsg(null)
    setQuery('')
    setView('search')
    setSelectedBike(null)
    setBikeCategories(null)
    setBikeDescription(null)
    setBikePhotos([])
    setDetailsState('loading')
    setDetailsError(null)
    setReviewState('loading')
    setReview(null)
    setOfferState('loading')
    setOffers(null)
    setUsedBikeState('loading')
    setUsedBikes(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const showResults = appState === 'loading' || appState === 'results'

  /* ── Render ───────────────────────────────────────── */

  return (
    <div className="min-h-screen bg-sand font-body flex flex-col">

      {/* ── Header ───────────────────────────────────── */}
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

      <main className="flex-1">

        {/* ── Search view ──────────────────────────────── */}
        {view === 'search' && (
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

            {/* Results */}
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
                          onSelect={handleBikeSelect}
                        />
                      ))
                    }
                  </div>
                </div>
              </section>
            )}
          </>
        )}

        {/* ── Details view ─────────────────────────────── */}
        {view === 'details' && selectedBike && (
          <BikeDetailsView
            bike={selectedBike}
            categories={bikeCategories}
            description={bikeDescription}
            photos={bikePhotos}
            state={detailsState}
            error={detailsError}
            review={review}
            reviewState={reviewState}
            offers={offers}
            offerState={offerState}
            usedBikes={usedBikes}
            usedBikeState={usedBikeState}
            onBack={handleBackToResults}
            onRetry={() => fetchDetails(selectedBike)}
          />
        )}
      </main>

      {/* ── Footer ───────────────────────────────────── */}
      <footer className="border-t border-border">
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
