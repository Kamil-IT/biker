import { useRef, useState, type RefObject } from 'react'
import { postJson } from '../api'
import type {
  Bike, BikeCategory, BikeDescription, EquipmentDetailsPayload, EquipmentDetailsResponse,
  EquipmentPhotosResponse, EquipmentReviewResponse, EquipmentSearchPayload, EquipmentSelection,
} from '../types'

type LoadState = 'loading' | 'loaded' | 'error'

// Sets `equipment_id` on every element of that name — only in this bike's tree, which is the
// one the search ran for — so going back and re-entering reads the stored data by id.
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

// State and calls of the equipment view (TODO-042). Opening it reads the stored details and
// photos from the DB — two fast reads, no AI; an empty answer is "no data", not an error.
// The paid searcher runs happen only through `searchDetails` / `searchPhotos` (the
// "Poproś o dane" buttons): they throw on failure so the button becomes clickable again,
// write their answer into the state WITHOUT flipping it to 'loading', and drop it when the
// user has opened another item (or reset) in the meantime — it is stored in the DB anyway.
export function useEquipment(
  selectedBikeRef: RefObject<Bike | null>,
  setBikeCategories: (update: (prev: BikeCategory[] | null) => BikeCategory[] | null) => void,
) {
  const itemRef = useRef<EquipmentSelection | null>(null)
  const [item, setItem]               = useState<EquipmentSelection | null>(null)
  const [category, setCategory]       = useState<string | null>(null)
  const [categories, setCategories]   = useState<BikeCategory[] | null>(null)
  const [description, setDescription] = useState<BikeDescription | null>(null)
  const [photos, setPhotos]           = useState<string[]>([])
  const [state, setState]             = useState<LoadState>('loading')
  const [photosState, setPhotosState] = useState<LoadState>('loading')
  const [error, setError]             = useState<string | null>(null)
  const [review, setReview]           = useState<EquipmentReviewResponse | null>(null)
  const [reviewState, setReviewState] = useState<LoadState>('loading')

  const isCurrent = (sel: EquipmentSelection) => itemRef.current === sel

  // After a successful search: remember the id on the bike's matching elements, unless
  // another bike is open by now.
  const linkToBike = (sel: EquipmentSelection, id: number | null) => {
    if (id == null) return
    const bike = selectedBikeRef.current
    if (!bike || bike.brand !== sel.bikeCompany || bike.model !== sel.bikeModel) return
    setBikeCategories(prev => linkElements(prev, sel.name, id))
  }

  // By id when the element carries one, else by name (company '' + model = element name).
  const readBody = (sel: EquipmentSelection): EquipmentDetailsPayload =>
    sel.equipmentId != null
      ? { company: '', model: sel.name, equipment_id: sel.equipmentId }
      : { company: '', model: sel.name }

  const searchBody = (sel: EquipmentSelection): EquipmentSearchPayload => ({
    bike_company: sel.bikeCompany,
    bike_model:   sel.bikeModel,
    element_name: sel.name,
    ...(category ? { category } : {}),
  })

  const fetchDetails = async (sel: EquipmentSelection) => {
    setState('loading')
    setError(null)
    setCategories(null)
    setDescription(null)
    setCategory(null)
    try {
      const data = await postJson<EquipmentDetailsResponse>('/v1/equipment/details', readBody(sel))
      if (!isCurrent(sel)) return
      setCategories(data.components)
      setDescription(data.description ?? null)
      setCategory(data.category || null)
      setState('loaded')
    } catch (err) {
      if (!isCurrent(sel)) return
      setError(err instanceof Error ? err.message : 'Coś poszło nie tak. Spróbuj ponownie.')
      setState('error')
    }
  }

  const fetchPhotos = async (sel: EquipmentSelection) => {
    setPhotosState('loading')
    setPhotos([])
    try {
      const data = await postJson<EquipmentPhotosResponse>('/v1/equipment/photos', readBody(sel))
      if (!isCurrent(sel)) return
      setPhotos(data.photos ?? [])
      setPhotosState('loaded')
    } catch {
      if (isCurrent(sel)) setPhotosState('error')
    }
  }

  // Unchanged behaviour: the review is fetched automatically (SDK + generic cache, no button).
  const fetchReview = async (sel: EquipmentSelection) => {
    setReviewState('loading')
    setReview(null)
    try {
      const data = await postJson<EquipmentReviewResponse>('/v1/equipment/review', { company: '', model: sel.name })
      if (!isCurrent(sel)) return
      setReview(data)
      setReviewState('loaded')
    } catch {
      if (isCurrent(sel)) setReviewState('error')
    }
  }

  const open = (sel: EquipmentSelection) => {
    itemRef.current = sel
    setItem(sel)
    fetchDetails(sel)
    fetchPhotos(sel)
    fetchReview(sel)
  }

  const retry = () => { if (itemRef.current) fetchDetails(itemRef.current) }

  // The Opis / Komponenty button: one run fills both sections. An empty answer leaves both
  // buttons on screen, which then read "Nie znaleziono danych".
  const searchDetails = async () => {
    const sel = itemRef.current
    if (!sel) return
    const data = await postJson<EquipmentDetailsResponse>('/v1/equipment/details/search', searchBody(sel))
    if (!isCurrent(sel)) return
    setCategories(data.components)
    setDescription(data.description ?? null)
    setCategory(data.category || null)
    setState('loaded')
    linkToBike(sel, data.equipment_id)
  }

  // The gallery's button; the searcher writes photos only for equipment that has none.
  const searchPhotos = async () => {
    const sel = itemRef.current
    if (!sel) return
    const data = await postJson<EquipmentPhotosResponse>('/v1/equipment/photos/search', searchBody(sel))
    if (!isCurrent(sel)) return
    setPhotos(data.photos ?? [])
    setPhotosState('loaded')
    linkToBike(sel, data.equipment_id)
  }

  const reset = () => {
    itemRef.current = null
    setItem(null)
    setCategory(null)
    setCategories(null)
    setDescription(null)
    setPhotos([])
    setState('loading')
    setPhotosState('loading')
    setError(null)
    setReview(null)
    setReviewState('loading')
  }

  return {
    item, category, categories, description, photos, state, photosState, error, review, reviewState,
    open, retry, searchDetails, searchPhotos, reset,
  }
}
