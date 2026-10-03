import { useRef, useState } from 'react'
import { ApiError, errorMessage, postJson } from '../api'
import type {
  BikeCategory, BikeDescription, EquipmentDetailsResponse, EquipmentItemResponse, EquipmentPhotosResponse,
  EquipmentReviewResponse, EquipmentSearchPayload,
} from '../types'

type LoadState = 'loading' | 'loaded' | 'error'

// What /equipment/{id} shows: the item, and the bike it was opened from when known (the
// address of the history entry it came from) — the details search's context bike.
interface Opened {
  id: number
  fromBikeId: number | null
}

const hasDetails = (data: EquipmentDetailsResponse) =>
  !!data.description?.text?.trim() || !!data.description?.segments.some(s => s.text.trim()) ||
  data.components.some(c => c.subcategories.some(s => s.elements.length > 0))

// State and calls of the equipment view (/equipment/{id}). Opening it reads the item (name,
// category, the first bike linking it), its stored details and photos — fast DB reads. While
// the item has no details stored (description NULL) the details search runs AUTOMATICALLY,
// on every entry; it ends with a description either way (the searcher stores "Opis
// niedostępny dla tego produktu." when it finds nothing), so it never runs twice for one item.
// A failed run stores nothing: the next entry, or the button, tries again. The photo search
// and the review stay behind their buttons. Answers for another item are dropped.
export function useEquipment() {
  const openedRef = useRef<Opened | null>(null)
  const [opened, setOpened]           = useState<Opened | null>(null)
  const [item, setItem]               = useState<EquipmentItemResponse | null>(null)
  const [lookup, setLookup]           = useState<'loading' | 'loaded' | 'missing' | 'error'>('loading')
  const [category, setCategory]       = useState<string | null>(null)
  const [categories, setCategories]   = useState<BikeCategory[] | null>(null)
  const [description, setDescription] = useState<BikeDescription | null>(null)
  const [state, setState]             = useState<LoadState>('loading')
  const [error, setError]             = useState<string | null>(null)
  const [photos, setPhotos]           = useState<string[]>([])
  const [photosState, setPhotosState] = useState<LoadState>('loading')
  const [review, setReview]           = useState<EquipmentReviewResponse | null>(null)
  // The details search in flight: both the Opis and Specyfikacja slots watch it (one run).
  const runRef = useRef<Promise<void> | null>(null)
  const [detailsRun, setDetailsRun]   = useState<Promise<void> | null>(null)
  const failedRef = useRef(false)

  const isCurrent = (it: Opened) => openedRef.current === it

  const searchBody = (it: Opened): EquipmentSearchPayload =>
    it.fromBikeId != null ? { equipment_id: it.id, bike_id: it.fromBikeId } : { equipment_id: it.id }

  const showDetails = (data: EquipmentDetailsResponse) => {
    setCategories(data.components)
    setDescription(data.description ?? null)
    setCategory(data.category || null)
    setState('loaded')
  }

  // The details search; a call while one is running joins it. Throws on failure (502 / 503 /
  // the subscription limit) so the slots become clickable again.
  const searchDetails = (): Promise<void> => {
    const it = openedRef.current
    if (!it) return Promise.resolve()
    if (runRef.current) return runRef.current
    const run = (async () => {
      try {
        const data = await postJson<EquipmentDetailsResponse>('/v1/equipment/details/search', searchBody(it))
        if (isCurrent(it)) showDetails(data)
      } catch (err) {
        if (isCurrent(it)) failedRef.current = true
        throw err
      }
    })()
    failedRef.current = false
    runRef.current = run
    setDetailsRun(run)
    const clear = () => {
      if (runRef.current !== run) return
      runRef.current = null
      setDetailsRun(null)
    }
    run.then(clear, clear)
    return run
  }

  const fetchItem = async (it: Opened) => {
    try {
      const data = await postJson<EquipmentItemResponse>('/v1/equipment/by-id', { equipment_id: it.id })
      if (!isCurrent(it)) return
      setItem(data)
      setCategory(prev => prev ?? (data.category || null))
      setLookup('loaded')
    } catch (err) {
      if (isCurrent(it)) setLookup(err instanceof ApiError && err.status === 404 ? 'missing' : 'error')
    }
  }

  const fetchDetails = async (it: Opened) => {
    setState('loading')
    setError(null)
    try {
      const data = await postJson<EquipmentDetailsResponse>('/v1/equipment/details', { equipment_id: it.id })
      if (!isCurrent(it)) return
      showDetails(data)
      // Nothing stored yet (an unknown id answers empty too, but has no bike to search with:
      // its search fails with 404 and the page shows "Nie znaleziono wyposażenia" anyway).
      if (!hasDetails(data)) searchDetails().catch(() => {})
    } catch (err) {
      if (!isCurrent(it)) return
      setError(errorMessage(err))
      setState('error')
    }
  }

  const fetchPhotos = async (it: Opened) => {
    try {
      const data = await postJson<EquipmentPhotosResponse>('/v1/equipment/photos', { equipment_id: it.id })
      if (!isCurrent(it)) return
      setPhotos(data.photos ?? [])
      setPhotosState('loaded')
    } catch {
      if (isCurrent(it)) setPhotosState('error')
    }
  }

  const open = (id: number, fromBikeId: number | null) => {
    const it = { id, fromBikeId }
    openedRef.current = it
    runRef.current = null
    failedRef.current = false
    setOpened(it)
    setDetailsRun(null)
    setItem(null)
    setLookup('loading')
    setCategory(null)
    setCategories(null)
    setDescription(null)
    setPhotos([])
    setPhotosState('loading')
    setReview(null)
    fetchItem(it)
    fetchDetails(it)
    fetchPhotos(it)
  }

  // Every entry of /equipment/{id}. The item already shown stays as it is (Back from the bike
  // and Forward again cost nothing) — unless its details search or a read failed, then it is
  // read and searched again.
  const enter = (id: number, fromBikeId: number | null) => {
    const cur = openedRef.current
    const intact = cur?.id === id && !failedRef.current && lookup !== 'error' && state !== 'error'
    if (!intact) open(id, fromBikeId)
  }

  // The gallery's button; the searcher writes photos only for an item that has none.
  const searchPhotos = async () => {
    const it = openedRef.current
    if (!it) return
    const data = await postJson<EquipmentPhotosResponse>('/v1/equipment/photos/search', searchBody(it))
    if (!isCurrent(it)) return
    setPhotos(data.photos ?? [])
    setPhotosState('loaded')
  }

  // The review's button (POST /v1/equipment/review — the Anthropic API, generic cache).
  const requestReview = async () => {
    const it = openedRef.current
    if (!it || !item) return
    const data = await postJson<EquipmentReviewResponse>('/v1/equipment/review', { company: '', model: item.name })
    if (isCurrent(it)) setReview(data)
  }

  const retry = () => { if (openedRef.current) open(openedRef.current.id, openedRef.current.fromBikeId) }

  const reset = () => {
    openedRef.current = null
    runRef.current = null
    setOpened(null)
    setDetailsRun(null)
  }

  return {
    opened, item, lookup, category, categories, description, state, error, photos, photosState, review, detailsRun,
    enter, retry, reset, searchDetails, searchPhotos, requestReview,
  }
}
