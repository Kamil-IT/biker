import { useEffect, useState } from 'react'
import { NO_RATING, PENDING_RATING, bikeKey } from '../ratings'
import type { Bike, CachedRatingsResponse, ExpertRating } from '../types'

interface Settled {
  forBikes: Bike[]
  ratings:  Record<string, ExpertRating>
}

interface CachedRatings {
  ratings: Record<string, ExpertRating>
  // True once the rating of every bike in the list is known (loaded or "no rating").
  settled: boolean
}

// TODO-040: expert ratings for the search results, read from the stored reviews (bike_review) only
// (POST /v1/bike/review/cached — one batch, no AI call). Runs again whenever the list
// changes. A non-OK or failed request marks every bike "no rating"; it never throws.
export default function useCachedRatings(bikes: Bike[]): CachedRatings {
  const [state, setState] = useState<Settled | null>(null)

  useEffect(() => {
    if (bikes.length === 0) return
    // StrictMode runs the effect twice in development; the discarded run must not write.
    let ignore = false
    const controller = new AbortController()

    const load = async () => {
      const ratings: Record<string, ExpertRating> = {}
      bikes.forEach(b => { ratings[bikeKey(b)] = NO_RATING })
      try {
        const res = await fetch('/v1/bike/review/cached', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ bikes: bikes.map(b => ({ company: b.brand, model: b.model })) }),
          signal:  controller.signal,
        })
        if (res.ok) {
          const data: CachedRatingsResponse = await res.json()
          if (Array.isArray(data.ratings)) {
            data.ratings.forEach((r, i) => {
              const bike = bikes[i]
              // Same order as the request; a rating of 0 is never a score.
              if (bike && r.found && typeof r.rating === 'number' && r.rating > 0) {
                ratings[bikeKey(bike)] = { state: 'loaded', rating: r.rating }
              }
            })
          }
        }
      } catch {
        // network failure or malformed JSON — every bike stays "no rating"
      }
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
