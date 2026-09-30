import ResultCard from './ResultCard'
import { PENDING_RATING, bikeKey } from '../ratings'
import type { Bike, ExpertRating, PopularBike } from '../types'

interface PopularBikesSectionProps {
  bikes:    PopularBike[]
  ratings:  Record<string, ExpertRating>
  onSelect: (bike: Bike) => void
}

// Home-page "Najpopularniejsze rowery" (TODO-034): the same container and status row
// as the results section, one ResultCard per bike in its popular look — the expert
// rating in the numeral slot, the description in the explanation slot, no "Najlepsze
// dopasowanie" badge. A click hands `handleBikeSelect` a regular Bike, so the details
// view opens exactly as it does for a search result.
export default function PopularBikesSection({ bikes, ratings, onSelect }: PopularBikesSectionProps) {
  return (
    <section
      className="max-w-2xl mx-auto px-4 sm:px-6 pb-20"
      aria-label="Najpopularniejsze rowery"
    >
      <div className="border-t border-border pt-8">

        {/* Status row */}
        <div className="flex items-center justify-between mb-6 min-h-[28px]">
          <span className="font-mono text-[11px] text-muted uppercase tracking-wider">
            Najpopularniejsze rowery
          </span>
        </div>

        {/* Card list */}
        <div className="space-y-4">
          {bikes.map((bike, i) => {
            const key    = bikeKey(bike)
            const rating = ratings[key] ?? PENDING_RATING
            return (
              <ResultCard
                key={key}
                bike={{
                  brand:       bike.brand,
                  model:       bike.model,
                  accessories: [],
                  explanation: bike.description,
                }}
                rank={i + 1}
                isTop={false}
                animationDelay={Math.min(i, 8) * 65}
                expertRating={rating}
                onSelect={onSelect}
              />
            )
          })}
        </div>
      </div>
    </section>
  )
}
