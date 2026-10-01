import { useEffect, useState } from 'react'
import { NO_RATING, PENDING_RATING, bikeKey } from '../ratings'
import type { Bike, BikeReviewResponse, ExpertRating } from '../types'

interface Settled {
  forBikes: Bike[]
  ratings:  Record<string, ExpertRating>
}

interface CachedRatings {
  ratings: Record<string, ExpertRating>
  // True once the rating of every bike in the list is known (loaded or "no rating").
  settled: boolean
}

// TODO-040: expert ratings for the search results, read from the stored reviews (bike_review) only.
// One POST /v1/bike/review per bike (a DB read, no AI call), all at once; the ratings are
// published together when the last one returns, so the list is sorted once. Runs again
// whenever the list changes. A non-OK or failed call marks that bike "no rating"; it never throws.
export default function useCachedRatings(bikes: Bike[]): CachedRatings {
  const [state, setState] = useState<Settled | null>(null)

  useEffect(() => {
    if (bikes.length === 0) return
    // StrictMode runs the effect twice in development; the discarded run must not write.
    let ignore = false
    const controller = new AbortController()

    const fetchRating = async (bike: Bike): Promise<ExpertRating> => {
      try {
        const res = await fetch('/v1/bike/review', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ company: bike.brand, model: bike.model }),
          signal:  controller.signal,
        })
        if (res.ok) {
          const data: BikeReviewResponse = await res.json()
          // A rating of 0 / no sources is the backend's empty review, not a score.
          if (typeof data.rating === 'number' && data.rating > 0 && data.sources_used >= 1) {
            return { state: 'loaded', rating: data.rating }
          }
        }
      } catch {
        // network failure or malformed JSON — "no rating"
      }
      return NO_RATING
    }

    const load = async () => {
      const results = await Promise.all(bikes.map(fetchRating))
      const ratings: Record<string, ExpertRating> = {}
      bikes.forEach((b, i) => { ratings[bikeKey(b)] = results[i] })
      if (!ignore) setState({ forBikes: bikes, ratings })
    }

    load()
    return () => {
      ignore = true
      controller.abort()
    }
  }, [bikes])

  const current = state && state.forBikes === bikes
  if (bikes.length === 0) return { ratings: {}, settled: true }
  if (!current) {
    return {
      ratings: Object.fromEntries(bikes.map(b => [bikeKey(b), PENDING_RATING])),
      settled: false,
    }
  }
  return { ratings: state.ratings, settled: true }
}
