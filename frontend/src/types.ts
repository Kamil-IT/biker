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

export interface BikeOfferResponse {
  offers: BikeOffer[]
  info: string
}

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
  has_suspension?:      boolean
  is_kids?:             boolean
  bike_type?:           string
  price_max?:           number
  frame_size?:          string
  rider_height_cm?:     number
  gender?:              string
  frame_material?:      string
  brake_type?:          string
  drivetrain?:          string
  belt_drive?:          boolean
  battery_capacity_wh?: number
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
  rider_height_cm:     string
  price_max:           string
  gender:              string
  frame_material:      string
  brake_type:          string
  drivetrain:          string
  battery_capacity_wh: string
  is_electric:         boolean | undefined
  has_suspension:      boolean | undefined
  is_kids:             boolean | undefined
  belt_drive:          boolean | undefined
}

export const EMPTY_FILTERS: SearchFilters = {
  brand:               '',
  model:               '',
  year:                '',
  wheel_size:          '',
  bike_type:           '',
  frame_size:          '',
  rider_height_cm:     '',
  price_max:           '',
  gender:              '',
  frame_material:      '',
  brake_type:          '',
  drivetrain:          '',
  battery_capacity_wh: '',
  is_electric:         undefined,
  has_suspension:      undefined,
  is_kids:             undefined,
  belt_drive:          undefined,
}

export interface ParseResponse {
  brand?:          string
  model?:          string
  year?:           number
  wheel_size?:     string
  is_electric?:    boolean
  has_suspension?: boolean
  is_kids?:        boolean
}
