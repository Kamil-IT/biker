import { useRef, useState } from 'react'
import { ApiError, errorMessage, postJson } from '../api'
import type {
  Bike, BikeCategory, BikeDescription, BikeDetailsResponse, BikeOfferResponse, BikePhotosResponse,
  BikeReviewResponse, UsedBikeResponse,
} from '../types'

type LoadState = 'loading' | 'loaded' | 'error'

// A /bike/{id} address opened without the bike in memory (link, new tab, F5): the
// POST /v1/bike/by-id lookup. 'missing' = 404, the "Nie znaleziono roweru" page.
export interface BikeLookup {
  id: number
  state: 'loading' | 'missing' | 'error'
  error?: string
}

// Sets `equipment_id` on every element of that name in the bike's tree, so a second click on
// it opens /equipment/{id} without asking the backend again.
function linkElements(categories: BikeCategory[] | null, name: string, id: number): BikeCategory[] | null {
  if (!categories) return categories
  return categories.map(cat => ({
    ...cat,
    subcategories: cat.subcategories.map(sub => ({
      ...sub,
      elements: sub.elements.map(el => (el.name === name ? { ...el, equipment_id: id } : el)),
    })),
  }))
}

// State and calls of the bike details view (moved out of App.tsx). Opening a bike starts the
// fast DB reads: details, review, the four stored-offer sources and the photos. The paid
// searcher runs happen only through the search* actions behind the "Poproś o dane" buttons.
export function useBikeDetails() {
  const [bike, setBike]                         = useState<Bike | null>(null)
  // Mirrors `bike` for the slow searches and reads: a result that lands after another bike
  // was opened must not overwrite that bike's sections (TODO-031 / TODO-032 / TODO-033).
  const bikeRef                                 = useRef<Bike | null>(null)
  const lookupRef                               = useRef<number | null>(null)
  const [lookup, setLookup]                     = useState<BikeLookup | null>(null)
  const [detailsState, setDetailsState]         = useState<LoadState>('loading')
  const [categories, setCategories]             = useState<BikeCategory[] | null>(null)
  const [description, setDescription]          = useState<BikeDescription | null>(null)
  const [detailsError, setDetailsError]         = useState<string | null>(null)
  // Photos are their own DB read (POST /v1/bike/photos), independent of the details request.
  const [photos, setPhotos]                     = useState<BikePhotosResponse | null>(null)
  const [photosState, setPhotosState]           = useState<LoadState>('loading')
  const [reviewState, setReviewState]           = useState<LoadState>('loading')
  const [review, setReview]                     = useState<BikeReviewResponse | null>(null)
  const [offerState, setOfferState]             = useState<LoadState>('loading')
  const [offers, setOffers]                     = useState<BikeOfferResponse | null>(null)
  const [decathlonState, setDecathlonState]     = useState<LoadState>('loading')
  const [decathlonOffers, setDecathlonOffers]   = useState<BikeOfferResponse | null>(null)
  // centrumrowerowe.pl offers: stored by the discovery enrichment, read only — no search.
  const [centrumState, setCentrumState]         = useState<LoadState>('loading')
  const [centrumOffers, setCentrumOffers]       = useState<BikeOfferResponse | null>(null)
  const [usedBikeState, setUsedBikeState]       = useState<LoadState>('loading')
  const [usedBikes, setUsedBikes]               = useState<UsedBikeResponse | null>(null)

  const body = (b: Bike) => ({ company: b.brand, model: b.model })

  const fetchDetails = async (b: Bike) => {
    setDetailsState('loading')
    setDetailsError(null)
    setCategories(null)
    setDescription(null)
    try {
      const data = await postJson<BikeDetailsResponse>('/v1/bike/details', body(b))
      if (bikeRef.current !== b) return
      setCategories(data.components)
      setDescription(data.description ?? null)
      setDetailsState('loaded')
    } catch (err) {
      if (bikeRef.current !== b) return
      setDetailsError(errorMessage(err))
      setDetailsState('error')
    }
  }

  // Stored data of one source, read when the details view opens: the review, the four
  // offer sources (/v1/bike/allegro, /used/olx, /decathlon, /centrumrowerowe) and the photos
  // are fast DB reads — no AI call — that differ only in path and state pair, hence one
  // reader. An answer that lands after another bike was opened is dropped.
  const fetchStored = async <T,>(
    path: string,
    b: Bike,
    setData: (data: T | null) => void,
    setState: (state: LoadState) => void,
  ) => {
    setState('loading')
    setData(null)
    try {
      const data = await postJson<T>(path, body(b))
      if (bikeRef.current !== b) return
      setData(data)
      setState('loaded')
    } catch {
      if (bikeRef.current === b) setState('error')
    }
  }

  // Opens a bike already known (a result card, the popular list or the by-id lookup below).
  const open = (b: Bike) => {
    setBike(b)
    bikeRef.current = b
    lookupRef.current = null
    setLookup(null)
    fetchDetails(b)
    fetchStored<BikeReviewResponse>('/v1/bike/review', b, setReview, setReviewState)
    fetchStored<BikeOfferResponse>('/v1/bike/allegro', b, setOffers, setOfferState)
    fetchStored<UsedBikeResponse>('/v1/bike/used/olx', b, setUsedBikes, setUsedBikeState)
    fetchStored<BikeOfferResponse>('/v1/bike/decathlon', b, setDecathlonOffers, setDecathlonState)
    fetchStored<BikeOfferResponse>('/v1/bike/centrumrowerowe', b, setCentrumOffers, setCentrumState)
    fetchStored<BikePhotosResponse>('/v1/bike/photos', b, setPhotos, setPhotosState)
  }

  // /bike/{id} opened by address: the bike comes from POST /v1/bike/by-id, then opens as usual.
  const openById = async (id: number) => {
    lookupRef.current = id
    setLookup({ id, state: 'loading' })
    try {
      const b = await postJson<Bike>('/v1/bike/by-id', { bike_id: id })
      if (lookupRef.current === id) open(b)
    } catch (err) {
      if (lookupRef.current !== id) return
      const missing = err instanceof ApiError && err.status === 404
      setLookup({ id, state: missing ? 'missing' : 'error', error: errorMessage(err) })
    }
  }

  // On-demand searches behind the "Poproś o dane" buttons. A section's state is deliberately
  // not set to 'loading': the button shows its own spinner, and 'loading' would restart the
  // 5 s skeleton grace. Throws on failure (with the backend's `detail`) so the button becomes
  // clickable again. A search can take minutes; if another bike is open by then the result
  // is dropped — it is stored in the DB anyway and shows when this bike is opened again.
  const postOnDemandSearch = async <T,>(path: string, b: Bike): Promise<T | null> => {
    const data = await postJson<T>(path, body(b))
    return bikeRef.current === b ? data : null
  }

  const searchUsed = async (b: Bike) => {
    const data = await postOnDemandSearch<UsedBikeResponse>('/v1/bike/used/search', b)
    if (!data) return
    setUsedBikes(data)
    setUsedBikeState('loaded')
  }

  // For a non-Decathlon brand the backend answers at once with no offers and a Polish `info`
  // naming the house brands. Both New-card searches resolve to their `info`, which the button
  // shows next to its "nothing found" label.
  const searchDecathlon = async (b: Bike): Promise<string> => {
    const data = await postOnDemandSearch<BikeOfferResponse>('/v1/bike/decathlon/search', b)
    if (!data) return ''
    setDecathlonOffers(data)
    setDecathlonState('loaded')
    return data.info
  }

  // Allegro listings can be used (`is_new: false`) — the rows land in whichever card their
  // flag says, through the same `offers` state the DB read fills.
  const searchAllegro = async (b: Bike): Promise<string> => {
    const data = await postOnDemandSearch<BikeOfferResponse>('/v1/bike/allegro/search', b)
    if (!data) return ''
    setOffers(data)
    setOfferState('loaded')
    return data.info
  }

  // The searcher only writes photos for a bike that has none: the answer is the full gallery.
  const searchPhotos = async (b: Bike) => {
    const data = await postOnDemandSearch<BikePhotosResponse>('/v1/bike/photos/search', b)
    if (!data) return
    setPhotos(data)
    setPhotosState('loaded')
  }

  // An empty answer (no `ref`, `sources_used` 0) keeps the button, then "Nie znaleziono recenzji".
  const searchReview = async (b: Bike) => {
    const data = await postOnDemandSearch<BikeReviewResponse>('/v1/bike/review/search', b)
    if (!data) return
    setReview(data)
    setReviewState('loaded')
  }

  // One searcher run fills both the Opis and Komponenty sections (TODO-041); an empty answer
  // stays the "no data" state, so the button then reads "Nie znaleziono danych".
  const searchDetails = async (b: Bike) => {
    const data = await postOnDemandSearch<BikeDetailsResponse>('/v1/bike/details/search', b)
    if (!data) return
    setCategories(data.components)
    setDescription(data.description ?? null)
    setDetailsState('loaded')
  }

  // An element resolved to its equipment row (POST /v1/equipment/resolve) — only on the open bike.
  const linkElement = (b: Bike, name: string, equipmentId: number) => {
    if (bikeRef.current === b) setCategories(prev => linkElements(prev, name, equipmentId))
  }

  const reset = () => {
    setBike(null)
    bikeRef.current = null
    lookupRef.current = null
    setLookup(null)
  }

  return {
    bike, bikeRef, lookup, open, openById, reset, linkElement,
    // The BikeDetailsView props of the open bike's sections.
    view: {
      categories, description, state: detailsState, error: detailsError, photos: photos?.photos ?? [], photosState,
      review, reviewState, offers, offerState, usedBikes, usedBikeState, decathlonOffers, decathlonState,
      centrumOffers, centrumState,
    },
    retryDetails: () => { if (bikeRef.current) fetchDetails(bikeRef.current) },
    searchUsed, searchDecathlon, searchAllegro, searchPhotos, searchReview, searchDetails,
  }
}
