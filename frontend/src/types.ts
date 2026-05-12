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

export interface BikeDetailsResponse {
  company: string
  model: string
  description: string
  components: BikeCategory[]
}

export interface BikeReviewResponse {
  score: number
  explanation: string
  ref: string[]
}
