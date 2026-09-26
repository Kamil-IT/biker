import { useRef, useState } from 'react'
import SearchInput from './components/SearchInput'
import ResultCard from './components/ResultCard'
import LoadingCard from './components/LoadingCard'
import BikeDetailsView from './components/BikeDetailsView'
import EquipmentDetailsView from './components/EquipmentDetailsView'
import type { Bike, BikeCategory, BikeDescription, BikeDetailsResponse, BikeReviewResponse, BikeOfferResponse, UsedBikeResponse, EquipmentDetailsResponse, EquipmentReviewResponse, SearchPayload, ParseResponse, SearchFilters } from './types'
import { EMPTY_FILTERS } from './types'

type AppState     = 'idle' | 'loading' | 'results' | 'error'
type AppView      = 'search' | 'details' | 'equipment'
type DetailsState = 'loading' | 'loaded' | 'error'
type ReviewState  = 'loading' | 'loaded' | 'error'
type OfferState   = 'loading' | 'loaded' | 'error'
type UsedBikeState = 'loading' | 'loaded' | 'error'

// Search has no fixed result count (TODO-025), so the skeleton count is neutral.
const LOADING_CARDS = 3

interface SearchResponse {
  search: string
  bikes: Bike[]
}

// Shown when /v1/bike/parse answers 400. The backend's detail string is English,
// so the UI shows its own Polish message instead.
const NO_MATCH_MSG = 'Nie mamy tego roweru w naszej bazie'

export default function App() {
  // Search state
  const [appState, setAppState]             = useState<AppState>('idle')
  const [query, setQuery]                   = useState('')
  const [filters, setFilters]               = useState<SearchFilters>(EMPTY_FILTERS)
  const [bikes, setBikes]                   = useState<Bike[]>([])
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [errorMsg, setErrorMsg]             = useState<string | null>(null)
  const resultsRef                          = useRef<HTMLElement>(null)
  const [showFilters, setShowFilters]       = useState(false)
  const [showAdvanced, setShowAdvanced]     = useState(false)
  const [isParsing, setIsParsing]           = useState(false)
  const [noMatchMsg, setNoMatchMsg]         = useState<string | null>(null)

  const updateFilter = <K extends keyof SearchFilters>(key: K, val: SearchFilters[K]) =>
    setFilters(prev => ({ ...prev, [key]: val }))

  // Details state
  const [view, setView]                         = useState<AppView>('search')
  const [selectedBike, setSelectedBike]         = useState<Bike | null>(null)
  // Mirrors selectedBike for the slow on-demand searches (OLX, Decathlon): a result
  // that lands after the user has opened another bike must not overwrite that
  // bike's card (TODO-031 / TODO-032).
  const selectedBikeRef                         = useRef<Bike | null>(null)
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
  const [decathlonState, setDecathlonState] = useState<OfferState>('loading')
  const [decathlonOffers, setDecathlonOffers] = useState<BikeOfferResponse | null>(null)

  // Used bikes (OLX) state
  const [usedBikeState, setUsedBikeState]   = useState<UsedBikeState>('loading')
  const [usedBikes, setUsedBikes]           = useState<UsedBikeResponse | null>(null)

  // Equipment details state (entered by clicking a bike's accessory chip)
  const [equipItem, setEquipItem]               = useState<{ company: string; model: string } | null>(null)
  const [equipCategory, setEquipCategory]       = useState<string | null>(null)
  const [equipCategories, setEquipCategories]   = useState<BikeCategory[] | null>(null)
  const [equipDescription, setEquipDescription] = useState<BikeDescription | null>(null)
  const [equipPhotos, setEquipPhotos]           = useState<string[]>([])
  const [equipState, setEquipState]             = useState<DetailsState>('loading')
  const [equipError, setEquipError]             = useState<string | null>(null)
  const [equipReview, setEquipReview]           = useState<EquipmentReviewResponse | null>(null)
  const [equipReviewState, setEquipReviewState] = useState<ReviewState>('loading')

  /* ── Handlers ─────────────────────────────────────── */

  const handleSearch = async (payload: SearchPayload) => {
    const hasStructured = Object.entries(payload).some(([k, v]) => k !== 'search' && v !== undefined)

    setNoMatchMsg(null)

    // If only free text provided, parse it into structured fields first
    if (payload.search && !hasStructured) {
      setIsParsing(true)
      try {
        const res = await fetch('/v1/bike/parse', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ text: payload.search }),
        })
        // 400 = the backend recognised no bike attribute in the text. Warn and
        // stop here rather than running a search that has nothing to go on.
        if (res.status === 400) {
          setNoMatchMsg(NO_MATCH_MSG)
          setIsParsing(false)
          return
        }
        if (res.ok) {
          const parsed: ParseResponse = await res.json()
          const anyExtracted = !!(
            parsed.brand || parsed.model || (parsed.year != null) ||
            parsed.wheel_size || (parsed.is_electric != null)
          )
          if (anyExtracted) {
            setFilters(prev => ({
              ...prev,
              ...(parsed.brand          ? { brand: parsed.brand }                : {}),
              ...(parsed.model          ? { model: parsed.model }                : {}),
              ...(parsed.year != null   ? { year: String(parsed.year) }          : {}),
              ...(parsed.wheel_size     ? { wheel_size: parsed.wheel_size }       : {}),
              ...(parsed.is_electric != null    ? { is_electric: parsed.is_electric }       : {}),
            }))
            setShowFilters(true)
            setIsParsing(false)
            return  // let user review populated fields, then submit again
          }
        }
      } catch {
        // parse failed — fall through to normal search
      }
      setIsParsing(false)
    }

    setAppState('loading')
    setErrorMsg(null)

    try {
      // payload already contains only the populated fields (built in SearchInput)
      const body: SearchPayload = { ...payload }

      const res = await fetch('/v1/bike/search', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Błąd serwera ${res.status}`)
      }

      const data: SearchResponse = await res.json()
      setBikes(data.bikes)
      setSubmittedQuery(data.search)
      setAppState('results')

      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 80)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Coś poszło nie tak. Spróbuj ponownie.')
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
        throw new Error((data as { detail?: string }).detail ?? `Błąd serwera ${res.status}`)
      }

      const data: BikeDetailsResponse = await res.json()
      setBikeCategories(data.components)
      setBikeDescription(data.description ?? null)
      setBikePhotos(data.photos ?? [])
      setDetailsState('loaded')
    } catch (err) {
      setDetailsError(err instanceof Error ? err.message : 'Coś poszło nie tak. Spróbuj ponownie.')
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
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
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
      const res = await fetch('/v1/bike/allegro', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
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
      const res = await fetch('/v1/bike/used/olx', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
      const data: UsedBikeResponse = await res.json()
      setUsedBikes(data)
      setUsedBikeState('loaded')
    } catch {
      setUsedBikeState('error')
    }
  }

  // On-demand searches behind the offer cards' "Poproś o dane" buttons: OLX in the
  // Used card (TODO-031), Decathlon in the New card (TODO-032). The card's state is
  // deliberately not set to 'loading': the button shows its own spinner, and 'loading'
  // would restart the 5 s skeleton grace in the offers section. Throws on failure
  // (with the backend's `detail`) so the button can return to clickable. A search can
  // take minutes; if another bike is open by then the result is dropped — it is stored
  // in the DB anyway and shows when this bike is opened again.
  const postOnDemandSearch = async <T,>(path: string, bike: Bike): Promise<T | null> => {
    const res = await fetch(path, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ company: bike.brand, model: bike.model }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error((data as { detail?: string }).detail ?? `Błąd serwera ${res.status}`)
    }
    const data: T = await res.json()
    return selectedBikeRef.current === bike ? data : null
  }

  const searchUsedBikes = async (bike: Bike) => {
    const data = await postOnDemandSearch<UsedBikeResponse>('/v1/bike/used/search', bike)
    if (!data) return
    setUsedBikes(data)
    setUsedBikeState('loaded')
  }

  // For a non-Decathlon brand the backend answers at once with no offers (no searcher run).
  const searchDecathlon = async (bike: Bike) => {
    const data = await postOnDemandSearch<BikeOfferResponse>('/v1/bike/decathlon/search', bike)
    if (!data) return
    setDecathlonOffers(data)
    setDecathlonState('loaded')
  }

  const fetchDecathlon = async (bike: Bike) => {
    setDecathlonState('loading')
    setDecathlonOffers(null)
    try {
      const res = await fetch('/v1/bike/decathlon', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
      const data: BikeOfferResponse = await res.json()
      setDecathlonOffers(data)
      setDecathlonState('loaded')
    } catch {
      setDecathlonState('error')
    }
  }

  const fetchEquipmentDetails = async (company: string, model: string) => {
    setEquipState('loading')
    setEquipError(null)
    setEquipCategories(null)
    setEquipDescription(null)
    setEquipPhotos([])
    setEquipCategory(null)
    try {
      const res = await fetch('/v1/equipment/details', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company, model }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Błąd serwera ${res.status}`)
      }
      const data: EquipmentDetailsResponse = await res.json()
      setEquipCategories(data.components)
      setEquipDescription(data.description ?? null)
      setEquipPhotos(data.photos ?? [])
      setEquipCategory(data.category ?? null)
      setEquipState('loaded')
    } catch (err) {
      setEquipError(err instanceof Error ? err.message : 'Coś poszło nie tak. Spróbuj ponownie.')
      setEquipState('error')
    }
  }

  const fetchEquipmentReview = async (company: string, model: string) => {
    setEquipReviewState('loading')
    setEquipReview(null)
    try {
      const res = await fetch('/v1/equipment/review', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company, model }),
      })
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
      const data: EquipmentReviewResponse = await res.json()
      setEquipReview(data)
      setEquipReviewState('loaded')
    } catch {
      setEquipReviewState('error')
    }
  }

  const handleEquipmentSelect = (name: string) => {
    const item = { company: '', model: name }
    setEquipItem(item)
    setView('equipment')
    window.scrollTo({ top: 0, behavior: 'smooth' })
    fetchEquipmentDetails(item.company, item.model)
    fetchEquipmentReview(item.company, item.model)
  }

  const handleBackFromEquipment = () => {
    setView('details')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleBikeSelect = (bike: Bike) => {
    setSelectedBike(bike)
    selectedBikeRef.current = bike
    setView('details')
    window.scrollTo({ top: 0, behavior: 'smooth' })
    fetchDetails(bike)
    fetchReview(bike)
    fetchOffer(bike)
    fetchUsedBikes(bike)
    fetchDecathlon(bike)
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
    setFilters(EMPTY_FILTERS)
    setShowFilters(false)
    setShowAdvanced(false)
    setIsParsing(false)
    setView('search')
    setSelectedBike(null)
    selectedBikeRef.current = null
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
    setEquipItem(null)
    setEquipCategory(null)
    setEquipCategories(null)
    setEquipDescription(null)
    setEquipPhotos([])
    setEquipState('loading')
    setEquipError(null)
    setEquipReview(null)
    setEquipReviewState('loading')
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
            aria-label="Biker — wróć na stronę główną"
          >
            BIKER
          </button>
          <span
            className="font-mono text-[11px] text-muted uppercase tracking-widest hidden sm:block select-none"
            aria-hidden="true"
          >
            Wyszukiwarka rowerów AI
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
                onChange={setQuery}
                filters={filters}
                onFilterChange={updateFilter}
                showFilters={showFilters}
                onShowFiltersChange={setShowFilters}
                showAdvanced={showAdvanced}
                onShowAdvancedChange={setShowAdvanced}
                isParsing={isParsing}
                onSubmit={handleSearch}
                isLoading={appState === 'loading'}
              />

              {appState === 'error' && (
                <div
                  role="alert"
                  className="mt-4 px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink"
                >
                  <strong className="font-medium text-terra">Błąd: </strong>
                  {errorMsg}
                </div>
              )}
            </section>

            {/* Results */}
            {showResults && (
              <section
                ref={resultsRef}
                className="max-w-2xl mx-auto px-4 sm:px-6 pb-20"
                aria-label="Rekomendowane rowery"
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

                    {appState === 'results' && (
                      <button
                        onClick={handleReset}
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

                  {/* Card list */}
                  <div className="space-y-4">
                    {appState === 'loading' &&
                      Array.from({ length: LOADING_CARDS }).map((_, i) => (
                        <LoadingCard key={i} delay={i * 90} />
                      ))
                    }
                    {appState === 'results' && bikes.length === 0 && (
                      <div
                        role="alert"
                        className="px-4 py-3 bg-parchment border border-terra/30 rounded-xl font-body text-sm text-ink"
                      >
                        <strong className="font-medium text-terra">Nie znaleziono: </strong>
                        Żaden rower nie pasuje do tego wyszukiwania. Spróbuj innych słów lub mniejszej liczby filtrów.
                      </div>
                    )}
                    {appState === 'results' &&
                      bikes.map((bike, i) => (
                        <ResultCard
                          key={`${bike.brand}-${bike.model}`}
                          bike={bike}
                          rank={i + 1}
                          isTop={i === 0}
                          animationDelay={Math.min(i, 8) * 65}
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
            decathlonOffers={decathlonOffers}
            decathlonState={decathlonState}
            onBack={handleBackToResults}
            onRetry={() => fetchDetails(selectedBike)}
            onEquipmentSelect={handleEquipmentSelect}
            onSearchUsed={() => searchUsedBikes(selectedBike)}
            onSearchNew={() => searchDecathlon(selectedBike)}
          />
        )}

        {/* ── Equipment details view ───────────────────── */}
        {view === 'equipment' && equipItem && (
          <EquipmentDetailsView
            company={equipItem.company}
            model={equipItem.model}
            category={equipCategory}
            categories={equipCategories}
            description={equipDescription}
            photos={equipPhotos}
            state={equipState}
            error={equipError}
            review={equipReview}
            reviewState={equipReviewState}
            onBack={handleBackFromEquipment}
            onRetry={() => fetchEquipmentDetails(equipItem.company, equipItem.model)}
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
            Napędzane przez Claude
          </span>
        </div>
      </footer>
    </div>
  )
}
