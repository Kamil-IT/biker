export interface Bike {
  // bike.id — the /bike/{id} address. Null only for a search result whose bike row is missing.
  id?: number | null
  brand: string
  model: string
  accessories: string[]
  explanation: string
  // null / missing = unknown; else an English value (MTB, Gravel, Road, Cyclocross, Trekking, City, ...)
  category?: string | null
  // Cover photo URL and its edge colour ("#RRGGBB"); absent/null from older backends or bikes without a photo.
  photo?: string | null
  photo_bg?: string | null
}

export interface SpecItem {
  key: string
  value: string
}

export interface ComponentElement {
  name: string
  description: string
  specs: SpecItem[]
  // TODO-042: id of the stored equipment row this element was linked to by a search;
  // null / absent until then (the equipment view then reads by name).
  equipment_id?: number | null
  /** ISSUE-016: true = a specific product; the bike details view links the name only then. */
  is_linkable: boolean
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
  short_description: string
  components: BikeCategory[]
  category?: string | null
}

// Returned by POST /v1/bike/photos (DB read of the stored photos, in display order) and
// POST /v1/bike/photos/search (on-demand photo searcher). Photos are no longer part of
// the details response.
export interface BikePhotosResponse {
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

// Returned by POST /v1/equipment/details (DB read) and POST /v1/equipment/details/search
// (on-demand equipment searcher, TODO-042). Photos come from their own call; empty
// description text and no components = no data (not an error).
export interface EquipmentDetailsResponse {
  company: string
  model: string
  category: string
  description: BikeDescription
  components: BikeCategory[]
  short_description: string
  equipment_id: number | null
}

// Returned by POST /v1/equipment/photos (DB read) and POST /v1/equipment/photos/search.
export interface EquipmentPhotosResponse {
  photos: string[]
  equipment_id: number | null
}

export interface EquipmentReviewResponse {
  score: number
  explanation: string
  ref: string[]
}

// Body of the on-demand equipment searches (/equipment/{id}): the item, and the bike the
// view was opened from when known (the search's context bike; else the backend takes the
// first bike linking the item).
export interface EquipmentSearchPayload {
  equipment_id: number
  bike_id?: number
}

// POST /v1/equipment/by-id: the item's identity and the first bike whose spec tree links
// it (the back target of a deep link).
export interface EquipmentItemResponse {
  equipment_id: number
  name: string
  category: string
  company: string
  model: string
  bike: { id: number; brand: string; model: string } | null
}

// POST /v1/equipment/resolve: the equipment row of a clicked element (created empty when missing).
export interface EquipmentResolveResponse {
  equipment_id: number
  name: string
  category: string
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

// The Kontakt tab's form (POST /v1/contact). `topic` is a slug — ContactPage.tsx owns
// the Polish labels; `website` is a honeypot a person leaves empty.
export type ContactTopic = 'missing_bike' | 'wrong_data' | 'feature_idea' | 'cooperation' | 'other'

export interface ContactMessageRequest {
  name:    string
  email:   string
  topic:   ContactTopic
  message: string
  website: string
}

export interface ContactMessageResponse {
  ok: boolean
}

export interface ParseResponse {
  brand?:          string
  model?:          string
  year?:           number
  wheel_size?:     string
  is_electric?:    boolean
  // One of the "Typ roweru" option values (Road, MTB, Gravel, Hybrid/Commuter, Touring, BMX, Folding)
  bike_type?:      string
}

// Returned by GET /v1/bike/popular (TODO-034): the curated home-page list, already in
// display order. `description` is the first one or two sentences of the stored overview
// ("" when the bike has no details row) — the card shows it in the explanation slot.
export interface PopularBike {
  id:          number | null
  brand:       string
  model:       string
  description: string
  category?:    string | null
  photo?:      string | null
  photo_bg?:   string | null
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

// "Rower na Twoją miarę" frame-size calculator (TODO-045): POST /v1/fit/frame-size. The
// bike types are a subset of the search form's, so a later match against the bike
// database needs no translation. The backend does all the maths; the page only shows it.
export const FIT_BIKE_TYPES = ['Road', 'MTB', 'Gravel', 'Touring', 'Hybrid/Commuter'] as const
export type FitBikeType = typeof FIT_BIKE_TYPES[number]

export interface FrameSizeRequest {
  height_cm: number
  inseam_cm: number
  bike_type: FitBikeType
}

// In scale order, smallest first.
export const FRAME_SIZE_LETTERS = ['XS', 'S', 'M', 'L', 'XL'] as const
export type FrameSizeLetter = typeof FRAME_SIZE_LETTERS[number]

// `size` is in `unit` (centimetres, or inches for MTB); `letters` run from the letter of
// `range_min` to the letter of `range_max`, ascending; `confidence: 'medium'` = the formula
// for this bike type is only approximate; `measurement_warning` = the inseam looks off for
// that height.
export interface FrameSizeResponse {
  bike_type:           FitBikeType
  size:                number
  unit:                'cm' | 'in'
  range_min:           number
  range_max:           number
  letter:              FrameSizeLetter
  letters:             FrameSizeLetter[]
  confidence:          'good' | 'medium'
  measurement_warning: boolean
}
