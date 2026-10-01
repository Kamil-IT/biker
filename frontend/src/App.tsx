import { useMemo, useRef, useState } from 'react'
import SearchInput from './components/SearchInput'
import ResultCard from './components/ResultCard'
import LoadingCard from './components/LoadingCard'
import BikeDetailsView from './components/BikeDetailsView'
import EquipmentDetailsView from './components/EquipmentDetailsView'
import PopularBikesSection from './components/PopularBikesSection'
import TopTabs from './components/TopTabs'
import FitComingSoonPage from './components/FitComingSoonPage'
import ContactPage from './components/ContactPage'
import useRoute, { ROUTES, type Route } from './hooks/useRoute'
import usePopularBikes from './hooks/usePopularBikes'
import useCachedRatings from './hooks/useCachedRatings'
import { useEquipment } from './hooks/useEquipment'
import { postJson } from './api'
import { PENDING_RATING, bikeKey } from './ratings'
import type { Bike, BikeCategory, BikeDescription, BikeDetailsResponse, BikePhotosResponse, BikeReviewResponse, BikeOfferResponse, UsedBikeResponse, ComponentElement, SearchPayload, ParseResponse, SearchFilters } from './types'
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
  // TODO-041: top tabs. The search flow stays mounted in App, so leaving for another
  // tab and coming back keeps the results.
  const [route, navigate] = useRoute()

  // Search state
  const [appState, setAppState]             = useState<AppState>('idle')
  const [query, setQuery]                   = useState('')
  const [filters, setFilters]               = useState<SearchFilters>(EMPTY_FILTERS)
  const [bikes, setBikes]                   = useState<Bike[]>([])
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [errorMsg, setErrorMsg]             = useState<string | null>(null)
  const resultsRef                          = useRef<HTMLElement>(null)
  const [showFilters, setShowFilters]       = useState(false)
  const [isParsing, setIsParsing]           = useState(false)
  const [noMatchMsg, setNoMatchMsg]         = useState<string | null>(null)
  // The free text that the filters currently shown were parsed from. A submit whose
  // text differs from it re-runs /v1/bike/parse on a cleared filter panel, so a brand
  // or model left over from the previous text never rides along with a new search.
  const parsedQueryRef                      = useRef('')

  const updateFilter = <K extends keyof SearchFilters>(key: K, val: SearchFilters[K]) =>
    setFilters(prev => ({ ...prev, [key]: val }))

  // Home-page "Najpopularniejsze rowery" (TODO-034): fetched once for the app's
  // lifetime — coming back from the details view does not refetch.
  const { bikes: popularBikes, ratings: popularRatings } = usePopularBikes()
  // TODO-040: expert ratings of the search results (stored reviews only). Until every
  // rating has settled the backend order is kept so cards do not jump; then rated bikes
  // go first, best first, and "no rating" bikes last (stable sort = backend order in ties).
  const { ratings: resultRatings, settled: ratingsSettled } = useCachedRatings(bikes)
  const sortedBikes = useMemo(() => {
    if (!ratingsSettled) return bikes
    const value = (b: Bike) => resultRatings[bikeKey(b)]?.rating ?? -1
    return [...bikes].sort((a, b) => value(b) - value(a))
  }, [bikes, resultRatings, ratingsSettled])

  // Details state
  const [view, setView]                         = useState<AppView>('search')
  const [selectedBike, setSelectedBike]         = useState<Bike | null>(null)
  // Mirrors selectedBike for the slow on-demand searches (OLX, Decathlon, Allegro): a
  // result that lands after the user has opened another bike must not overwrite that
  // bike's card (TODO-031 / TODO-032 / TODO-033).
  const selectedBikeRef                         = useRef<Bike | null>(null)
  const [detailsState, setDetailsState]         = useState<DetailsState>('loading')
  const [bikeCategories, setBikeCategories]     = useState<BikeCategory[] | null>(null)
  const [bikeDescription, setBikeDescription]   = useState<BikeDescription | null>(null)
  // Photos are their own DB read (POST /v1/bike/photos), independent of the details request.
  const [bikePhotos, setBikePhotos]             = useState<BikePhotosResponse | null>(null)
  const [photosState, setPhotosState]           = useState<OfferState>('loading')
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

  // Equipment view (entered by clicking a component name in the bike's spec tree, TODO-042):
  // stored details + photos are DB reads on open, the searches run only on a button click.
  const equipment = useEquipment(selectedBikeRef, setBikeCategories)

  /* ── Handlers ─────────────────────────────────────── */

  const handleSearch = async (payload: SearchPayload) => {
    const hasStructured = Object.entries(payload).some(([k, v]) => k !== 'search' && v !== undefined)

    setNoMatchMsg(null)

    const searchText  = payload.search?.trim() ?? ''
    const textChanged = !!searchText && searchText !== parsedQueryRef.current
    if (!searchText) parsedQueryRef.current = ''

    // Parse the free text into structured fields when it is all we have, and also
    // whenever the text changed since the filters were filled — then the stale
    // filters go first, so the new text alone decides them.
    if (searchText && (textChanged || !hasStructured)) {
      // The panel — and with it the payload SearchInput built from it — is cleared, so
      // a parse that extracts nothing falls through to a text-only search.
      if (textChanged) {
        setFilters(EMPTY_FILTERS)
        payload = { search: payload.search }
      }
      parsedQueryRef.current = searchText
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

  // Stored offers of one marketplace, read when the details view opens. All three
  // (/v1/bike/allegro, /v1/bike/used/olx, /v1/bike/decathlon) are fast DB reads of the
  // rows the searcher wrote — no AI call (TODO-031 / TODO-032 / TODO-033) — and differ
  // only in path and state pair, hence one reader. The stored photos (/v1/bike/photos)
  // are read the same way. An answer (or failure) that lands after another bike was
  // opened is dropped, like the on-demand searches' — it would show the previous bike's
  // rows or flip the new bike's section to the button.
  const fetchStoredOffers = async <T,>(
    path: string,
    bike: Bike,
    setData: (data: T | null) => void,
    setState: (state: OfferState) => void,
  ) => {
    setState('loading')
    setData(null)
    try {
      const res = await fetch(path, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ company: bike.brand, model: bike.model }),
      })
      if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
      const data = await res.json() as T
      if (selectedBikeRef.current !== bike) return
      setData(data)
      setState('loaded')
    } catch {
      if (selectedBikeRef.current !== bike) return
      setState('error')
    }
  }

  // On-demand searches behind the offer cards' "Poproś o dane" buttons — three of
  // them: OLX in the Used card (TODO-031), Decathlon (TODO-032) and Allegro (TODO-033)
  // together in the New card. The card's state is deliberately not set to 'loading':
  // the button shows its own spinner, and 'loading' would restart the 5 s skeleton
  // grace in the offers section. Throws on failure (with the backend's `detail`) so
  // the button can return to clickable. A search can take minutes; if another bike is
  // open by then the result is dropped — it is stored in the DB anyway and shows when
  // this bike is opened again.
  const postOnDemandSearch = async <T,>(path: string, bike: Bike): Promise<T | null> => {
    const data = await postJson<T>(path, { company: bike.brand, model: bike.model })
    return selectedBikeRef.current === bike ? data : null
  }

  const searchUsedBikes = async (bike: Bike) => {
    const data = await postOnDemandSearch<UsedBikeResponse>('/v1/bike/used/search', bike)
    if (!data) return
    setUsedBikes(data)
    setUsedBikeState('loaded')
  }

  // For a non-Decathlon brand the backend answers at once with no offers (no searcher run).
  // Resolves to whether any offer came back — searchNew needs that to tell "no offers"
  // from "the search never ran".
  const searchDecathlon = async (bike: Bike): Promise<boolean> => {
    const data = await postOnDemandSearch<BikeOfferResponse>('/v1/bike/decathlon/search', bike)
    if (!data) return false
    setDecathlonOffers(data)
    setDecathlonState('loaded')
    return data.offers.length > 0
  }

  // Allegro listings can be used (`is_new: false`) — the returned rows land in
  // whichever card their flag says, through the same `offers` state the DB read fills.
  const searchAllegro = async (bike: Bike): Promise<boolean> => {
    const data = await postOnDemandSearch<BikeOfferResponse>('/v1/bike/allegro/search', bike)
    if (!data) return false
    setOffers(data)
    setOfferState('loaded')
    return data.offers.length > 0
  }

  // The New card's button runs Decathlon and Allegro at the same time (TODO-033). Each
  // search sets its own state the moment it returns, so rows from either source
  // replace the button as they arrive rather than after both finish. Rejects — the
  // button becomes clickable again, with the first failure's error — whenever a search
  // failed and no search brought rows: both failed, or one failed (e.g. 503 busy) while
  // the other came back empty (for a non-Decathlon brand Decathlon is always instantly
  // empty, so an Allegro failure must not read as "no offers"). A failure next to real
  // rows from the other source is swallowed — those rows are on screen.
  const searchNew = async (bike: Bike) => {
    const results = await Promise.allSettled([searchDecathlon(bike), searchAllegro(bike)])
    const failures = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected')
    const gotRows = results.some(r => r.status === 'fulfilled' && r.value)
    if (failures.length > 0 && !gotRows) throw failures[0].reason
  }

  // The gallery's "Poproś o dane" button. The searcher only writes photos for a bike
  // that has none, so the answer is the full gallery in display order.
  const searchPhotos = async (bike: Bike) => {
    const data = await postOnDemandSearch<BikePhotosResponse>('/v1/bike/photos/search', bike)
    if (!data) return
    setBikePhotos(data)
    setPhotosState('loaded')
  }

  // The Review section's "Poproś o dane" button (TODO-037): the searcher runs the review
  // prompt and stores the result. An empty answer (no `ref`, `sources_used` 0) keeps the
  // button on screen, which then reads "Nie znaleziono recenzji".
  const searchReview = async (bike: Bike) => {
    const data = await postOnDemandSearch<BikeReviewResponse>('/v1/bike/review/search', bike)
    if (!data) return
    setReview(data)
    setReviewState('loaded')
  }

  // The Opis / Komponenty "Poproś o dane" button (TODO-041): one searcher run fills both
  // sections. POST /v1/bike/details answers an empty response (no description, no
  // components) when nothing is stored; that stays the "no data" state, so the button
  // then reads "Nie znaleziono danych".
  const searchDetails = async (bike: Bike) => {
    const data = await postOnDemandSearch<BikeDetailsResponse>('/v1/bike/details/search', bike)
    if (!data) return
    setBikeCategories(data.components)
    setBikeDescription(data.description ?? null)
    setDetailsState('loaded')
  }

  const handleEquipmentSelect = (element: ComponentElement) => {
    const bike = selectedBikeRef.current
    if (!bike) return
    equipment.open({
      name:        element.name,
      equipmentId: element.equipment_id ?? null,
      bikeCompany: bike.brand,
      bikeModel:   bike.model,
    })
    setView('equipment')
    window.scrollTo({ top: 0, behavior: 'smooth' })
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
    fetchStoredOffers<BikeOfferResponse>('/v1/bike/allegro', bike, setOffers, setOfferState)
    fetchStoredOffers<UsedBikeResponse>('/v1/bike/used/olx', bike, setUsedBikes, setUsedBikeState)
    fetchStoredOffers<BikeOfferResponse>('/v1/bike/decathlon', bike, setDecathlonOffers, setDecathlonState)
    fetchStoredOffers<BikePhotosResponse>('/v1/bike/photos', bike, setBikePhotos, setPhotosState)
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
    parsedQueryRef.current = ''
    setShowFilters(false)
    setIsParsing(false)
    setView('search')
    setSelectedBike(null)
    selectedBikeRef.current = null
    setBikeCategories(null)
    setBikeDescription(null)
    setBikePhotos(null)
    setPhotosState('loading')
    setDetailsState('loading')
    setDetailsError(null)
    setReviewState('loading')
    setReview(null)
    setOfferState('loading')
    setOffers(null)
    setUsedBikeState('loading')
    setUsedBikes(null)
    equipment.reset()
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const showResults = appState === 'loading' || appState === 'results'

  // "Szukanie rowerów" from the details or equipment view goes back to the result list;
  // from another tab it only switches the tab, the search state is kept.
  const handleNavigate = (to: Route) => {
    if (to === ROUTES.search && route === ROUTES.search && view !== 'search') {
      handleBackToResults()
      return
    }
    navigate(to)
  }

  const handleWordmark = () => {
    navigate(ROUTES.search)
    handleReset()
  }

  /* ── Render ───────────────────────────────────────── */

  return (
    <div className="min-h-screen bg-sand font-body flex flex-col">

      {/* ── Header ───────────────────────────────────── */}
      <header className="sticky top-0 z-20 bg-sand/90 backdrop-blur-sm border-b border-border">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button
            onClick={handleWordmark}
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
        <div className="max-w-2xl mx-auto px-4 sm:px-6">
          <TopTabs active={route} onNavigate={handleNavigate} />
        </div>
      </header>

      <main className="flex-1">

        {route === ROUTES.fit && <FitComingSoonPage onNavigate={navigate} />}
        {route === ROUTES.contact && <ContactPage />}

        {/* ── Search view ──────────────────────────────── */}
        {route === ROUTES.search && view === 'search' && (
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

            {/* Popular bikes — home page only: gone while a search runs or shows results */}
            {!showResults && popularBikes.length > 0 && (
              <PopularBikesSection
                bikes={popularBikes}
                ratings={popularRatings}
                onSelect={handleBikeSelect}
              />
            )}

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
                      sortedBikes.map((bike, i) => (
                        <ResultCard
                          key={`${bike.brand}-${bike.model}`}
                          bike={bike}
                          rank={i + 1}
                          isTop={false}
                          expertRating={resultRatings[bikeKey(bike)] ?? PENDING_RATING}
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
        {route === ROUTES.search && view === 'details' && selectedBike && (
          <BikeDetailsView
            bike={selectedBike}
            categories={bikeCategories}
            description={bikeDescription}
            photos={bikePhotos?.photos ?? []}
            photosState={photosState}
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
            onSearchNew={() => searchNew(selectedBike)}
            onSearchPhotos={() => searchPhotos(selectedBike)}
            onSearchReview={() => searchReview(selectedBike)}
            onSearchDetails={() => searchDetails(selectedBike)}
          />
        )}

        {/* ── Equipment details view ───────────────────── */}
        {route === ROUTES.search && view === 'equipment' && equipment.item && (
          <EquipmentDetailsView
            company=""
            model={equipment.item.name}
            category={equipment.category}
            categories={equipment.categories}
            description={equipment.description}
            photos={equipment.photos}
            photosState={equipment.photosState}
            state={equipment.state}
            error={equipment.error}
            review={equipment.review}
            reviewState={equipment.reviewState}
            onBack={handleBackFromEquipment}
            onRetry={equipment.retry}
            onSearchDetails={equipment.searchDetails}
            onSearchPhotos={equipment.searchPhotos}
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
