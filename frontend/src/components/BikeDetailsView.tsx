import { useState } from 'react'
import { ArrowLeft } from '@phosphor-icons/react'
import type { Bike, BikeCategory, BikeDescription, BikeReviewResponse, BikeOffer, BikeOfferResponse, UsedBikeResponse } from '../types'
import { PhotoGallery, DescriptionCard, ReviewSection, LoadingSkeleton, CategorySection } from './BikeDetailsShared'

type ReviewState = 'loading' | 'loaded' | 'error'

interface BikeDetailsViewProps {
  bike: Bike
  categories: BikeCategory[] | null
  description: BikeDescription | null
  photos: string[]
  state: 'loading' | 'loaded' | 'error'
  error: string | null
  review: BikeReviewResponse | null
  reviewState: ReviewState
  offers: BikeOfferResponse | null
  offerState: 'loading' | 'loaded' | 'error'
  usedBikes: UsedBikeResponse | null
  usedBikeState: 'loading' | 'loaded' | 'error'
  ceneoOffers: BikeOfferResponse | null
  ceneoState: 'loading' | 'loaded' | 'error'
  decathlonOffers: BikeOfferResponse | null
  decathlonState: 'loading' | 'loaded' | 'error'
  onBack: () => void
  onRetry: () => void
  onAccessorySelect: (accessory: string) => void
}

export default function BikeDetailsView({
  bike,
  categories,
  description,
  photos,
  state,
  error,
  review,
  reviewState,
  offers,
  offerState,
  usedBikes,
  usedBikeState,
  ceneoOffers,
  ceneoState,
  decathlonOffers,
  decathlonState,
  onBack,
  onRetry,
  onAccessorySelect,
}: BikeDetailsViewProps) {
  const { brand, model, accessories, match_score } = bike
  const scoreDisplay = match_score === 10 ? '10' : match_score.toFixed(1)

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 pt-8 pb-20">

      {/* Back navigation */}
      <button
        onClick={onBack}
        className="
          -ml-1 flex items-center gap-1.5 px-1 py-2 mb-8
          font-mono text-[11px] text-terra uppercase tracking-wider
          hover:text-terra-dark
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40 focus-visible:rounded
          transition-colors duration-150
        "
        aria-label="Back to search results"
      >
        <ArrowLeft size={12} weight="bold" aria-hidden="true" />
        Back to results
      </button>

      {/* Bike header */}
      <div className="mb-8">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="min-w-0">
            <h1 className="font-display font-bold text-charcoal leading-none text-[44px] sm:text-[56px]">
              {brand}
            </h1>
            <p className="font-display font-bold text-terra leading-tight mt-0.5 text-[22px] sm:text-[28px]">
              {model}
            </p>
          </div>
          <div className="shrink-0 text-right mt-1">
            <p className="font-mono text-[10px] text-muted uppercase tracking-widest mb-0.5">
              Match
            </p>
            <div
              className="font-display font-bold text-charcoal leading-none tabular-nums text-[36px]"
              aria-label={`Match score ${match_score} out of 10`}
            >
              {scoreDisplay}
            </div>
            <p className="font-mono text-[11px] text-muted">/ 10</p>
          </div>
        </div>

        {/* Photo gallery */}
        {state === 'loading' && photos.length === 0 && (
          <div className="mt-4 w-full aspect-[16/9] shimmer rounded-xl" aria-hidden="true" />
        )}
        {state !== 'loading' && <PhotoGallery photos={photos} />}

        {/* Equipment links — each accessory opens its equipment details page */}
        {accessories.filter(Boolean).length > 0 && (
          <div className="mt-3">
            <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mb-1.5">
              Equipment
            </span>
            <ul className="flex flex-wrap gap-x-2 gap-y-1.5" aria-label="Equipment — open details">
              {accessories.filter(Boolean).map((acc, i) => (
                <li key={`${acc}-${i}`}>
                  <button
                    type="button"
                    onClick={() => onAccessorySelect(acc)}
                    className="
                      group inline-flex items-center gap-1 px-2.5 py-1
                      rounded-full bg-parchment border border-border
                      hover:border-terra hover:bg-sand
                      focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40
                      transition-colors duration-150
                    "
                    aria-label={`View equipment details for ${acc}`}
                  >
                    <span className="
                      font-mono text-[11px] text-terra group-hover:text-terra-dark
                      underline decoration-dotted decoration-terra/50 underline-offset-[3px]
                      group-hover:decoration-solid group-hover:decoration-terra-dark
                      transition-colors duration-150
                    ">
                      {acc}
                    </span>
                    <span
                      aria-hidden="true"
                      className="text-[10px] leading-none text-terra group-hover:text-terra-dark transition-colors duration-150"
                    >
                      ↗
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Description */}
        <DescriptionCard description={description} state={state} />

        {/* Offers — all sources pooled, split by is_new (Used on top, New below) */}
        <MergedOffersSection
          offers={offers}
          offerState={offerState}
          ceneoOffers={ceneoOffers}
          ceneoState={ceneoState}
          decathlonOffers={decathlonOffers}
          decathlonState={decathlonState}
          usedBikes={usedBikes}
          usedBikeState={usedBikeState}
        />

        {/* Review */}
        <ReviewSection review={review} state={reviewState} />
      </div>

      {/* Divider */}
      <div className="border-t border-border pt-8">

        {/* Loading */}
        {state === 'loading' && <LoadingSkeleton />}

        {/* Error */}
        {state === 'error' && (
          <div role="alert" className="px-4 py-4 bg-parchment border border-terra/30 rounded-xl">
            <p className="font-body text-sm text-ink">
              <strong className="font-medium text-terra">Could not load specifications. </strong>
              {error}
            </p>
            <button
              onClick={onRetry}
              className="
                mt-3 font-mono text-[11px] text-terra uppercase tracking-wider
                hover:text-terra-dark
                focus-visible:outline-none focus-visible:underline
                transition-colors duration-150
              "
            >
              Try again
            </button>
          </div>
        )}

        {/* Loaded */}
        {state === 'loaded' && categories && (
          <div
            className="space-y-8"
            style={{ opacity: 0, animation: 'slideUp 350ms ease-out forwards' }}
          >
            {categories.map(cat => (
              <CategorySection key={cat.category} category={cat} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Offers (all sources merged, split by is_new) ───── */

type OfferState = 'loading' | 'loaded' | 'error'

// Parse a free-text price ("3 499 zł") into a number for sorting; unparseable sorts last.
function priceValue(p: string): number {
  const n = Number((p ?? '').replace(/[^\d]/g, ''))
  return Number.isFinite(n) && n > 0 ? n : Infinity
}

interface MergedOffersSectionProps {
  offers: BikeOfferResponse | null
  offerState: OfferState
  ceneoOffers: BikeOfferResponse | null
  ceneoState: OfferState
  decathlonOffers: BikeOfferResponse | null
  decathlonState: OfferState
  usedBikes: UsedBikeResponse | null
  usedBikeState: OfferState
}

function MergedOffersSection({
  offers,
  offerState,
  ceneoOffers,
  ceneoState,
  decathlonOffers,
  decathlonState,
  usedBikes,
  usedBikeState,
}: MergedOffersSectionProps) {
  // Pool every offer from all four sources, then split purely on the is_new flag.
  const allOffers: BikeOffer[] = [
    ...(offers?.offers ?? []),
    ...(ceneoOffers?.offers ?? []),
    ...(decathlonOffers?.offers ?? []),
    ...(usedBikes?.offers ?? []),
  ]

  const byPrice = (a: BikeOffer, b: BikeOffer) => priceValue(a.price) - priceValue(b.price)
  const usedList = allOffers.filter(o => o.is_new === false).sort(byPrice)
  const newList = allOffers.filter(o => o.is_new === true).sort(byPrice)

  // A late source can still add rows to either category, so both cards show their
  // skeleton until every source has settled.
  const anyLoading =
    offerState === 'loading' ||
    ceneoState === 'loading' ||
    decathlonState === 'loading' ||
    usedBikeState === 'loading'

  if (!anyLoading && usedList.length === 0 && newList.length === 0) return null

  return (
    <div className="mt-5 bg-card rounded-2xl border border-border overflow-hidden">
      <div className="px-5 py-4 md:px-6 md:py-5 border-b border-border">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          Offers
        </span>
      </div>
      <div className="p-4 md:p-5 space-y-4">
        <OfferCategoryCard title="Used" list={usedList} loading={anyLoading} />
        <OfferCategoryCard title="New" list={newList} loading={anyLoading} />
      </div>
    </div>
  )
}

function OfferCategoryCard({ title, list, loading }: { title: string; list: BikeOffer[]; loading: boolean }) {
  // Hide an empty category once everything has loaded; while loading, show the skeleton.
  if (!loading && list.length === 0) return null

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <div className="px-5 py-3 md:px-6 border-b border-border">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          {title}
        </span>
      </div>
      {loading ? (
        <div className="px-5 py-4 md:px-6 md:py-5 space-y-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="flex items-center justify-between gap-4">
              <div className="space-y-1.5 flex-1">
                <div className="shimmer h-2.5 w-16 rounded" style={{ animationDelay: `${i * 40}ms` }} />
                <div className="shimmer h-3.5 w-40 rounded" style={{ animationDelay: `${i * 40 + 20}ms` }} />
                <div className="shimmer h-2.5 w-20 rounded" style={{ animationDelay: `${i * 40 + 30}ms` }} />
              </div>
              <div className="shimmer h-4 w-20 rounded" style={{ animationDelay: `${i * 40 + 40}ms` }} />
            </div>
          ))}
        </div>
      ) : (
        <div className="divide-y divide-border">
          {list.map((offer, i) => (
            <OfferRow key={i} offer={offer} />
          ))}
        </div>
      )}
    </div>
  )
}

function OfferImageGallery({ photos }: { photos: string[] }) {
  const [idx, setIdx] = useState(0)
  if (!photos.length) return null

  const visible = photos.slice(idx, idx + 4)
  const canPrev = idx > 0
  const canNext = idx + 4 < photos.length

  const prev = (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation()
    setIdx(i => Math.max(0, i - 1))
  }
  const next = (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation()
    setIdx(i => Math.min(photos.length - 1, i + 1))
  }

  return (
    <div className="shrink-0 flex items-center gap-1">
      <button
        onClick={prev}
        disabled={!canPrev}
        className="font-mono text-[13px] text-terra disabled:opacity-20 hover:text-terra-dark transition-colors leading-none px-0.5"
        aria-label="Previous image"
      >
        ‹
      </button>
      <div className="flex gap-1">
        {visible.map((src, i) => (
          <img
            key={idx + i}
            src={src}
            alt=""
            className={`w-9 h-9 object-cover rounded-sm border transition-all ${
              i === 0 ? 'border-terra ring-1 ring-terra' : 'border-border opacity-75'
            }`}
          />
        ))}
      </div>
      <button
        onClick={next}
        disabled={!canNext}
        className="font-mono text-[13px] text-terra disabled:opacity-20 hover:text-terra-dark transition-colors leading-none px-0.5"
        aria-label="Next image"
      >
        ›
      </button>
    </div>
  )
}

function OfferRow({ offer }: { offer: BikeOffer }) {
  return (
    <a
      href={offer.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-4 px-5 py-4 md:px-6 group hover:bg-sand transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40"
    >
      <div className="flex-1 min-w-0">
        <p className="font-mono text-[10px] text-muted mb-0.5">{offer.source}</p>
        <p className="font-display font-bold text-charcoal text-[14px] leading-tight truncate">
          {offer.brand} {offer.model}
        </p>
        {offer.city && (
          <p className="font-mono text-[10px] text-muted mt-0.5">{offer.city}</p>
        )}
      </div>
      <OfferImageGallery photos={offer.photos} />
      <div className="shrink-0 flex items-center gap-2">
        <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded-full border leading-4 ${
          offer.is_new
            ? 'text-green-700 border-green-300 bg-green-50'
            : 'text-muted border-border bg-sand'
        }`}>
          {offer.is_new ? 'New' : 'Used'}
        </span>
        <span className="font-display font-bold text-terra tabular-nums text-[15px]">
          {offer.price}
        </span>
      </div>
      <span className="shrink-0 font-mono text-[13px] text-terra group-hover:text-terra-dark transition-colors duration-150" aria-hidden="true">
        →
      </span>
    </a>
  )
}
