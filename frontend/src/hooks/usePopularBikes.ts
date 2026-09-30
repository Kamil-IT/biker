import { useEffect, useState } from 'react'
import { NO_RATING, PENDING_RATING, bikeKey } from '../ratings'
import type { BikeReviewResponse, ExpertRating, PopularBike, PopularBikesResponse } from '../types'

interface PopularBikes {
  bikes:   PopularBike[]
  ratings: Record<string, ExpertRating>
}

// Home-page "Najpopularniejsze rowery" (TODO-034). Fetches GET /v1/bike/popular once on
// mount and keeps the list for the app's lifetime, so coming back from the details view
// does not refetch. Then asks POST /v1/bike/review for each bike separately — all at
// once, each settling its own entry as it returns, so one slow (uncached) review holds
// up only its own card. A failed list fetch leaves `bikes` empty, which simply hides
// the section — there is no error UI for it.
export default function usePopularBikes(): PopularBikes {
  const [bikes, setBikes]     = useState<PopularBike[]>([])
  const [ratings, setRatings] = useState<Record<string, ExpertRating>>({})

  useEffect(() => {
    // StrictMode runs the effect twice in development (mount → cleanup → mount). The
    // first run's fetches must not write into state after its cleanup, or two review
    // calls per bike would race for the same entry — and its list fetch is aborted in
    // the cleanup, so the discarded run never fans out into three review calls of its own.
    let ignore = false
    const controller = new AbortController()
    const { signal } = controller

    const fetchRating = async (bike: PopularBike) => {
      let next = NO_RATING
      try {
        const res = await fetch('/v1/bike/review', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ company: bike.brand, model: bike.model }),
          signal,
        })
        if (res.ok) {
          const data: BikeReviewResponse = await res.json()
          // A rating of 0 is the backend's "no review found" placeholder, not a score.
          if (typeof data.rating === 'number' && data.rating > 0) {
            next = { state: 'loaded', rating: data.rating }
          }
        }
      } catch {
        // network failure or malformed JSON — shown as "Brak oceny"
      }
      if (!ignore) setRatings(prev => ({ ...prev, [bikeKey(bike)]: next }))
    }

    const load = async () => {
      let list: PopularBike[] = []
      try {
        const res = await fetch('/v1/bike/popular', { signal })
        if (res.ok) {
          const data: PopularBikesResponse = await res.json()
          if (Array.isArray(data.bikes)) list = data.bikes
        }
      } catch {
        // backend unreachable — no section
      }
      if (ignore) return
      setBikes(list)
      setRatings(Object.fromEntries(list.map(bike => [bikeKey(bike), PENDING_RATING])))
      list.forEach(bike => fetchRating(bike))
    }

    load()
    return () => {
      ignore = true
      controller.abort()
    }
  }, [])

  return { bikes, ratings }
}
