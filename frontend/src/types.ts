export interface Bike {
  brand: string
  model: string
  accessories: string[]
  match_score: number
  explanation: string
}

export interface SpecItem {
  key: string
  value: string
}

export interface ComponentElement {
  name: string
  description: string
  specs: SpecItem[]
}

export interface BikeSubcategory {
  subcategory: string
  elements: ComponentElement[]
}

export interface BikeCategory {
  category: string
  subcategories: BikeSubcategory[]
}

export interface DescriptionCitation {
  url: string
  title: string
  cited_text: string
}

export interface TextSegment {
  text: string
  citations: DescriptionCitation[]
}

export interface BikeDescription {
  text: string
  segments: TextSegment[]
  citations: DescriptionCitation[]
}

export interface BikeDetailsResponse {
  company: string
  model: string
  description: BikeDescription
  components: BikeCategory[]
  photos: string[]
}

export interface BikeReviewResponse {
  score: number
  explanation: string
  ref: string[]
  rating: number         // 0–10 aggregate across curated review sources
  sources_used: number   // count of sources that contributed to the rating
}

export interface BikeOffer {
  brand: string
  model: string
  price: string
  is_new: boolean
  url: string
  photos: string[]
  source: string
  city?: string
}

// Returned by POST /v1/bike/allegro (DB read of the stored allegro.pl rows) / /v1/bike/allegro/search
// (on-demand Allegro searcher, TODO-033), and by POST /v1/bike/decathlon (DB read) / /v1/bike/decathlon/search
// (on-demand Decathlon searcher, TODO-032).
export interface BikeOfferResponse {
  offers: BikeOffer[]
  info: string
}

// Returned by both POST /v1/bike/used/olx (DB read) and POST /v1/bike/used/search (on-demand OLX searcher, TODO-031).
export interface UsedBikeResponse {
  offers: BikeOffer[]
  info: string
}

export interface EquipmentDetailsResponse {
  company: string
  model: string
  category: string
  description: BikeDescription
  components: BikeCategory[]
  photos: string[]
}

export interface EquipmentReviewResponse {
  score: number
  explanation: string
  ref: string[]
}

export interface EquipmentDetailsPayload {
  company?: string
  model: string
  category?: string
}

export interface EquipmentReviewPayload {
  company?: string
  model: string
}

export interface SearchPayload {
  search?:              string
  brand?:               string
  model?:               string
  year?:                number
  wheel_size?:          string
  is_electric?:         boolean
  bike_type?:           string
  frame_size?:          string
}

// Form state for the search filters panel. Text/number inputs and
// dropdowns are kept as strings; toggles are tri-state booleans.
export interface SearchFilters {
  brand:               string
  model:               string
  year:                string
  wheel_size:          string
  bike_type:           string
  frame_size:          string
  is_electric:         boolean | undefined
}

export const EMPTY_FILTERS: SearchFilters = {
  brand:               '',
  model:               '',
  year:                '',
  wheel_size:          '',
  bike_type:           '',
  frame_size:          '',
  is_electric:         undefined,
}

// Bike-details sections a user can ask us to fill in (POST /v1/bike/missing, TODO-026/027).
export const MissingType = {
  Photos:      'photos',
  Description: 'description',
  Components:  'components',
  Review:      'review',
  OffersNew:   'offers_new',
  OffersUsed:  'offers_used',
} as const
export type MissingType = typeof MissingType[keyof typeof MissingType]

export interface MissingDataRequest {
  company:      string
  model:        string
  missing_type: MissingType
}

export interface MissingDataResponse {
  bike_id:      number | null
  missing_type: MissingType
  counter:      number
}

export interface ParseResponse {
  brand?:          string
  model?:          string
  year?:           number
  wheel_size?:     string
  is_electric?:    boolean
}

// Returned by GET /v1/bike/popular (TODO-034): the curated home-page list, already in
// display order. `description` is the first one or two sentences of the stored overview
// ("" when the bike has no details row) — the card shows it in the explanation slot.
export interface PopularBike {
  brand:       string
  model:       string
  description: string
}

export interface PopularBikesResponse {
  bikes: PopularBike[]
}

// Expert rating of one popular bike, from its own POST /v1/bike/review call. 'error'
// covers a failed call and a `rating` of 0 alike — both read "Brak oceny" on the card —
// so `rating` is a number only in the 'loaded' state.
export interface ExpertRating {
  state:  'pending' | 'loaded' | 'error'
  rating: number | null
}
