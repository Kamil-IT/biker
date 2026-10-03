import { useEffect, useMemo, useRef, useState } from 'react'
import SearchPage, { type SearchState } from './components/SearchPage'
import BikeDetailsView from './components/BikeDetailsView'
import EquipmentDetailsView from './components/EquipmentDetailsView'
import TopTabs, { type Tab } from './components/TopTabs'
import FitComingSoonPage from './components/FitComingSoonPage'
import ContactPage from './components/ContactPage'
import NotFoundPage from './components/NotFoundPage'
import useRoute, { PATHS, bikePath, equipmentPath, searchPath, type Route } from './hooks/useRoute'
import usePopularBikes from './hooks/usePopularBikes'
import useCachedRatings from './hooks/useCachedRatings'
import { useBikeDetails } from './hooks/useBikeDetails'
import { useEquipment } from './hooks/useEquipment'
import { errorMessage, postJson } from './api'
import { bikeKey } from './ratings'
import { payloadToFilters, payloadToQuery, queryToPayload } from './searchQuery'
import type { Bike, ComponentElement, EquipmentResolveResponse, ParseResponse, SearchFilters, SearchPayload } from './types'
import { EMPTY_FILTERS } from './types'

interface SearchResponse {
  search: string
  bikes: Bike[]
}

// Shown when /v1/bike/parse answers 400. The backend's detail string is English,
// so the UI shows its own Polish message instead.
const NO_MATCH_MSG = 'Nie mamy tego roweru w naszej bazie'

const TAB_OF: Record<Route['name'], Tab> = {
  home: 'search', search: 'search', bike: 'search', equipment: 'search', fit: 'fit', contact: 'contact',
}

// The parents the "Wróć" buttons go back to: a search address (or home) for a bike, a bike for equipment.
const isSearchUrl = (url: string) => url === PATHS.home || url.startsWith('/search?')
const bikeIdOf = (url: string | null): number | null => {
  const m = url ? /^\/bike\/(\d+)$/.exec(url) : null
  return m ? Number(m[1]) : null
}

function PageLoading() {
  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 pt-14 pb-20 flex items-center gap-2.5" aria-busy="true">
      <span className="spin w-3.5 h-3.5 rounded-full border-2 border-terra/25 border-t-terra shrink-0" aria-hidden="true" />
      <span className="font-mono text-[11px] text-muted uppercase tracking-wider">Wczytuję…</span>
    </div>
  )
}

export default function App() {
  // Every view has its own address (useRoute); the state below is kept in memory across
  // them, so Back from a bike shows the same results without a request.
  const { route, from, navigate, goBack } = useRoute()

  // Search state
  const [searchState, setSearchState]       = useState<SearchState>('idle')
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
  // The canonical query of the results in memory (or in flight): a /search address with it
  // shows them again without a request. `lastSearchUrl` is where "Szukanie rowerów" leads.
  const searchKeyRef                        = useRef<string | null>(null)
  const [lastSearchUrl, setLastSearchUrl]   = useState<string | null>(null)

  const updateFilter = <K extends keyof SearchFilters>(key: K, val: SearchFilters[K]) =>
    setFilters(prev => ({ ...prev, [key]: val }))

  // Home-page "Najpopularniejsze rowery" (TODO-034): fetched once for the app's lifetime.
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

  const details = useBikeDetails()
  // Equipment view (/equipment/{id}, entered from a component name in a bike's spec tree).
  const equipment = useEquipment()

  /* ── Search ───────────────────────────────────────── */

  // The form as a search address fills it (its text counts as already parsed), or empty.
  const fillForm = (payload: SearchPayload) => {
    const f = payloadToFilters(payload)
    setQuery(payload.search ?? '')
    setFilters(f)
    setShowFilters(Object.entries(f).some(([, v]) => v !== '' && v !== undefined))
    setNoMatchMsg(null)
    parsedQueryRef.current = payload.search ?? ''
  }
  const clearForm = () => fillForm({})

  // Runs a search. From the form it is a new history entry (/search?…); opened by address
  // (link, F5, Back to a search not in memory) it runs for the address as it stands.
  const runSearch = async (input: SearchPayload, fromForm: boolean) => {
    // Through the address form, so the request and the address always agree.
    const payload = queryToPayload(payloadToQuery(input))
    const key = payloadToQuery(payload)
    searchKeyRef.current = key
    setLastSearchUrl(searchPath(key))
    if (fromForm) navigate(searchPath(key))
    setSearchState('loading')
    setErrorMsg(null)
    try {
      const data = await postJson<SearchResponse>('/v1/bike/search', payload)
      if (searchKeyRef.current !== key) return
      setBikes(data.bikes)
      setSubmittedQuery(data.search)
      setSearchState('results')
      if (fromForm) {
        setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
      }
    } catch (err) {
      if (searchKeyRef.current !== key) return
      setErrorMsg(errorMessage(err))
      setSearchState('error')
    }
  }

  const handleSearch = async (payload: SearchPayload) => {
    const hasStructured = Object.entries(payload).some(([k, v]) => k !== 'search' && v !== undefined)

    setNoMatchMsg(null)

    const searchText  = payload.search?.trim() ?? ''
    const textChanged = !!searchText && searchText !== parsedQueryRef.current
    if (!searchText) parsedQueryRef.current = ''

    // Parse the free text into structured fields when it is all we have, and also
    // whenever the text changed since the filters were filled — then the stale
    // filters go first, so the new text alone decides them. The address changes only
    // when a search runs, not for the parse.
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

    runSearch(payload, true)
  }

  /* ── Address → view ───────────────────────────────── */

  // The address decides what is shown; this loads what the new address needs. A bike or
  // equipment item already in memory is shown as it is (Back / Forward cost no request).
  useEffect(() => {
    switch (route.name) {
      case 'home':
        // "/" is the home page: the popular bikes and an empty form. The last search stays
        // in memory, so Forward shows it again. (The address is the external system this
        // effect syncs from — Back/Forward change it outside React.)
        // eslint-disable-next-line react-hooks/set-state-in-effect
        clearForm()
        break
      case 'search': {
        // Opened by address the search runs at once — no parse step — and fills the form.
        const payload = queryToPayload(route.query)
        fillForm(payload)
        if (route.query !== searchKeyRef.current || searchState === 'error') runSearch(payload, false)
        break
      }
      case 'bike':
        if (route.id != null && details.bikeRef.current?.id !== route.id) details.openById(route.id)
        break
      case 'equipment':
        if (route.id != null) equipment.enter(route.id, bikeIdOf(from))
        break
    }
    // Runs per address only: the handlers read the state of the render the address changed in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route])

  /* ── Handlers ─────────────────────────────────────── */

  const handleBikeSelect = (bike: Bike) => {
    if (bike.id == null) return  // only when the AI-found bike's row could not be saved
    details.open(bike)
    navigate(bikePath(bike.id))
  }

  // A linkable element of the bike's spec tree → its equipment row (created empty when
  // missing — free, no AI), then /equipment/{id}; the id is remembered on the element.
  const handleEquipmentSelect = async (element: ComponentElement) => {
    const bike = details.bikeRef.current
    if (bike?.id == null) return
    let id = element.equipment_id ?? null
    if (id == null) {
      try {
        const res = await postJson<EquipmentResolveResponse>(
          '/v1/equipment/resolve', { bike_id: bike.id, element_name: element.name },
        )
        id = res.equipment_id
        details.linkElement(bike, element.name, id)
      } catch (err) {
        console.error('equipment resolve failed', err)
        return
      }
    }
    if (details.bikeRef.current === bike) navigate(equipmentPath(id))
  }

  // The wordmark and "Nowe wyszukiwanie": home, with nothing kept in memory.
  const handleReset = () => {
    setSearchState('idle')
    setBikes([])
    setErrorMsg(null)
    clearForm()
    searchKeyRef.current = null
    setLastSearchUrl(null)
    setIsParsing(false)
    details.reset()
    equipment.reset()
    navigate(PATHS.home)
  }

  /* ── Address-specific views ───────────────────────── */

  const routeId = route.name === 'bike' || route.name === 'equipment' ? route.id : null

  const shownBike  = route.name === 'bike' && details.bike?.id === routeId ? details.bike : null
  const bikeLookup = route.name === 'bike' && details.lookup?.id === routeId ? details.lookup : null
  const bikeMissing = route.name === 'bike' && (routeId == null || bikeLookup?.state === 'missing')
  // "Wróć" from a bike: the search (or home) it was opened from, else the last search, else home.
  const bikeBackTarget = from && isSearchUrl(from) ? from : (lastSearchUrl ?? PATHS.home)

  const equipmentOpen = route.name === 'equipment' && routeId != null && equipment.opened?.id === routeId
  const equipmentMissing = route.name === 'equipment' && (routeId == null || (equipmentOpen && equipment.lookup === 'missing'))
  // "Wróć" from equipment: the bike it was opened from, else the first bike containing it.
  const equipmentBackBike = bikeIdOf(from) ?? equipment.item?.bike?.id ?? null
  const equipmentBack = () => {
    if (equipmentBackBike == null) navigate(PATHS.home)
    else goBack(url => url === bikePath(equipmentBackBike), bikePath(equipmentBackBike))
  }

  const title = (() => {
    switch (route.name) {
      case 'home':      return 'Biker — Znajdź swój idealny rower'
      case 'search':    return 'Wyniki wyszukiwania — Biker'
      case 'fit':       return 'Rower na Twoją miarę — Biker'
      case 'contact':   return 'Kontakt — Biker'
      case 'bike':
        if (shownBike) return `${shownBike.brand} ${shownBike.model} — Biker`
        return bikeMissing ? 'Nie znaleziono roweru — Biker' : 'Biker'
      case 'equipment':
        if (equipmentOpen && equipment.item) return `${equipment.item.name} — Biker`
        return equipmentMissing ? 'Nie znaleziono wyposażenia — Biker' : 'Biker'
    }
  })()
  useEffect(() => { document.title = title }, [title])

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
        <div className="max-w-2xl mx-auto px-4 sm:px-6">
          <TopTabs active={TAB_OF[route.name]} searchHref={lastSearchUrl ?? PATHS.home} onNavigate={navigate} />
        </div>
      </header>

      <main className="flex-1">

        {route.name === 'fit' && <FitComingSoonPage onNavigate={navigate} />}
        {route.name === 'contact' && <ContactPage />}

        {/* ── Home (/) and results (/search?…) ─────────── */}
        {(route.name === 'home' || route.name === 'search') && (
          <SearchPage
            showResults={route.name === 'search'}
            state={searchState}
            errorMsg={errorMsg}
            noMatchMsg={noMatchMsg}
            query={query}
            onQueryChange={setQuery}
            filters={filters}
            onFilterChange={updateFilter}
            showFilters={showFilters}
            onShowFiltersChange={setShowFilters}
            isParsing={isParsing}
            onSubmit={handleSearch}
            popularBikes={popularBikes}
            popularRatings={popularRatings}
            bikes={sortedBikes}
            ratings={resultRatings}
            submittedQuery={submittedQuery}
            resultsRef={resultsRef}
            onReset={handleReset}
            onSelectBike={handleBikeSelect}
          />
        )}

        {/* ── Bike details (/bike/{id}) ─────────────────── */}
        {route.name === 'bike' && (
          shownBike ? (
            <BikeDetailsView
              key={shownBike.id ?? undefined}
              bike={shownBike}
              {...details.view}
              backLabel={bikeBackTarget.startsWith('/search?') ? 'Wróć do wyników' : 'Wróć'}
              onBack={() => goBack(isSearchUrl, bikeBackTarget)}
              onRetry={details.retryDetails}
              onEquipmentSelect={handleEquipmentSelect}
              onSearchUsed={() => details.searchUsed(shownBike)}
              onSearchAllegro={() => details.searchAllegro(shownBike)}
              onSearchDecathlon={() => details.searchDecathlon(shownBike)}
              onSearchPhotos={() => details.searchPhotos(shownBike)}
              onSearchReview={() => details.searchReview(shownBike)}
              onSearchDetails={() => details.searchDetails(shownBike)}
            />
          ) : bikeMissing ? (
            <NotFoundPage
              title="Nie znaleziono roweru"
              text="Pod tym adresem nie ma roweru w naszej bazie. Poszukaj go w wyszukiwarce."
              onNavigate={navigate}
            />
          ) : bikeLookup?.state === 'error' ? (
            <NotFoundPage
              title="Nie udało się wczytać roweru"
              text={bikeLookup.error ?? 'Spróbuj ponownie za chwilę.'}
              onRetry={() => details.openById(bikeLookup.id)}
              onNavigate={navigate}
            />
          ) : <PageLoading />
        )}

        {/* ── Equipment details (/equipment/{id}) ───────── */}
        {route.name === 'equipment' && (
          equipmentMissing ? (
            <NotFoundPage
              title="Nie znaleziono wyposażenia"
              text="Pod tym adresem nie ma wyposażenia w naszej bazie. Poszukaj roweru w wyszukiwarce."
              onNavigate={navigate}
            />
          ) : equipmentOpen && equipment.lookup === 'error' ? (
            <NotFoundPage
              title="Nie udało się wczytać wyposażenia"
              text="Spróbuj ponownie za chwilę."
              onRetry={equipment.retry}
              onNavigate={navigate}
            />
          ) : equipmentOpen && equipment.item ? (
            <EquipmentDetailsView
              key={routeId ?? undefined}
              name={equipment.item.name}
              category={equipment.category}
              categories={equipment.categories}
              description={equipment.description}
              photos={equipment.photos}
              photosState={equipment.photosState}
              state={equipment.state}
              error={equipment.error}
              review={equipment.review}
              onRequestReview={equipment.requestReview}
              backLabel={equipmentBackBike != null ? 'Wróć do roweru' : 'Wróć'}
              onBack={equipmentBack}
              onRetry={equipment.retry}
              detailsRun={equipment.detailsRun}
              onSearchDetails={equipment.searchDetails}
              onSearchPhotos={equipment.searchPhotos}
            />
          ) : <PageLoading />
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
