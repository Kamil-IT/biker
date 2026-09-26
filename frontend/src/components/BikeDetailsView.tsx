import { useEffect, useState } from 'react'
import { ArrowLeft } from '@phosphor-icons/react'
import type { Bike, BikeCategory, BikeDescription, BikeReviewResponse, BikeOffer, BikeOfferResponse, UsedBikeResponse } from '../types'
import { MissingType } from '../types'
import { PhotoGallery, DescriptionCard, ReviewSection, LoadingSkeleton, CategorySection } from './BikeDetailsShared'
import RequestDataButton from './RequestDataButton'

// How long a section shows its loading state before the "Request data" button
// takes its place (TODO-027). The request itself keeps running.
const REQUEST_BUTTON_DELAY_MS = 5000

// True while `loading` has been on for less than `ms`. Restarts whenever
// `loading` turns on again (e.g. a details retry).
function useLoadingGrace(loading: boolean, ms = REQUEST_BUTTON_DELAY_MS): boolean {
  const [elapsed, setElapsed] = useState(false)
  const [prevLoading, setPrevLoading] = useState(loading)
  if (loading !== prevLoading) {
    setPrevLoading(loading)
    if (loading) setElapsed(false)
  }
  useEffect(() => {
    if (!loading) return
    const t = setTimeout(() => setElapsed(true), ms)
    return () => clearTimeout(t)
  }, [loading, ms])
  return loading && !elapsed
}

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
  onEquipmentSelect: (name: string) => void
  // On-demand OLX search behind the Used card's "Request data" button (TODO-031).
  onSearchUsed: () => Promise<void>
  // On-demand Decathlon search behind the New card's "Request data" button (TODO-032).
  onSearchNew: () => Promise<void>
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
  onEquipmentSelect,
  onSearchUsed,
  onSearchNew,
}: BikeDetailsViewProps) {
  const { brand, model, accessories, match_score } = bike
  const scoreDisplay = match_score === 10 ? '10' : match_score.toFixed(1)

  // Each section: loading state for the first 5 s, then its data if any arrived,
  // otherwise a "Request data" button (also after an empty or failed response).
  const detailsGrace = useLoadingGrace(state === 'loading')
  const reviewGrace = useLoadingGrace(reviewState === 'loading')
  const hasPhotos = photos.length > 0
  const hasDescription = !!description && (
    !!description.text?.trim() || description.segments.some(seg => seg.text.trim())
  )
  const hasComponents = !!categories && categories.length > 0
  const hasReview = !!review && (review.ref.some(Boolean) || review.sources_used > 0)

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
        aria-label="Wróć do wyników wyszukiwania"
      >
        <ArrowLeft size={12} weight="bold" aria-hidden="true" />
        Wróć do wyników
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
              Dopasowanie
            </p>
            <div
              className="font-display font-bold text-charcoal leading-none tabular-nums text-[36px]"
              aria-label={`Dopasowanie ${match_score} na 10`}
            >
              {scoreDisplay}
            </div>
            <p className="font-mono text-[11px] text-muted">/ 10</p>
          </div>
        </div>

        {/* Photo gallery */}
        {hasPhotos ? (
          <PhotoGallery photos={photos} />
        ) : detailsGrace ? (
          <div className="mt-4 w-full aspect-[16/9] shimmer rounded-xl" aria-hidden="true" />
        ) : (
          <RequestDataButton title="Zdjęcia" company={brand} model={model} missingType={MissingType.Photos} />
        )}

        {/* Accessories */}
        {accessories.filter(Boolean).length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Najważniejsze cechy">
            {accessories.filter(Boolean).map((acc, i) => (
              <li key={`${acc}-${i}`}>
                <span className="font-mono text-[10px] text-ink px-2 py-0.5 bg-sand rounded-full border border-border inline-block leading-5">
                  {acc}
                </span>
              </li>
            ))}
          </ul>
        )}

        {/* Description */}
        {hasDescription ? (
          <DescriptionCard description={description} state="loaded" />
        ) : detailsGrace ? (
          <DescriptionCard description={null} state="loading" />
        ) : (
          <RequestDataButton title="Opis" company={brand} model={model} missingType={MissingType.Description} />
        )}

        {/* Offers — all sources pooled, split by is_new (Used on top, New below) */}
        <MergedOffersSection
          company={brand}
          model={model}
          offers={offers}
          offerState={offerState}
          ceneoOffers={ceneoOffers}
          ceneoState={ceneoState}
          decathlonOffers={decathlonOffers}
          decathlonState={decathlonState}
          usedBikes={usedBikes}
          usedBikeState={usedBikeState}
          onSearchUsed={onSearchUsed}
          onSearchNew={onSearchNew}
        />

        {/* Review */}
        {hasReview ? (
          <ReviewSection review={review} state="loaded" />
        ) : reviewGrace ? (
          <ReviewSection review={null} state="loading" />
        ) : (
          <RequestDataButton title="Recenzja ekspertów" company={brand} model={model} missingType={MissingType.Review} />
        )}
      </div>

      {/* Divider */}
      <div className="border-t border-border pt-8">

        {/* Loading */}
        {detailsGrace && !hasComponents && <LoadingSkeleton />}

        {/* Error */}
        {state === 'error' && (
          <div role="alert" className="px-4 py-4 bg-parchment border border-terra/30 rounded-xl">
            <p className="font-body text-sm text-ink">
              <strong className="font-medium text-terra">Nie udało się wczytać specyfikacji. </strong>
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
              Spróbuj ponownie
            </button>
          </div>
        )}

        {/* No components yet (still loading after 5 s, empty, or error) */}
        {!detailsGrace && !hasComponents && (
          <RequestDataButton
            title="Specyfikacja"
            spacing="mt-0"
            company={brand}
            model={model}
            missingType={MissingType.Components}
          />
        )}

        {/* Loaded */}
        {hasComponents && (
          <div
            className="space-y-8"
            style={{ opacity: 0, animation: 'slideUp 350ms ease-out forwards' }}
          >
            {categories!.map(cat => (
              <CategorySection key={cat.category} category={cat} onElementSelect={onEquipmentSelect} />
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
  company: string
  model: string
  offers: BikeOfferResponse | null
  offerState: OfferState
  ceneoOffers: BikeOfferResponse | null
  ceneoState: OfferState
  decathlonOffers: BikeOfferResponse | null
  decathlonState: OfferState
  usedBikes: UsedBikeResponse | null
  usedBikeState: OfferState
  onSearchUsed: () => Promise<void>
  onSearchNew: () => Promise<void>
}

function MergedOffersSection({
  company,
  model,
  offers,
  offerState,
  ceneoOffers,
  ceneoState,
  decathlonOffers,
  decathlonState,
  usedBikes,
  usedBikeState,
  onSearchUsed,
  onSearchNew,
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
  // skeleton for the first 5 s while any source is loading; after that each card
  // shows whatever rows it has, or its own "Request data" button (TODO-027). In both
  // cards that button also runs an on-demand search: OLX in the Used card (TODO-031),
  // Decathlon in the New card (TODO-032); the rows it returns land in `usedBikes` /
  // `decathlonOffers` and take the button's place. The New card offers the Decathlon
  // search only while no decathlon.pl row is stored: an outlet row (`is_new: false`)
  // sits in the Used card, and re-searching would cost a paid run per click for nothing.
  const hasDecathlonRows = (decathlonOffers?.offers.length ?? 0) > 0
  const anyLoading =
    offerState === 'loading' ||
    ceneoState === 'loading' ||
    decathlonState === 'loading' ||
    usedBikeState === 'loading'
  const grace = useLoadingGrace(anyLoading)

  return (
    <div className="mt-5 bg-card rounded-2xl border border-border overflow-hidden">
      <div className="px-5 py-4 md:px-6 md:py-5 border-b border-border">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          Oferty
        </span>
      </div>
      <div className="p-4 md:p-5 space-y-4">
        <OfferCategoryCard
          title="Używane"
          list={usedList}
          loading={grace}
          company={company}
          model={model}
          missingType={MissingType.OffersUsed}
          onRequested={onSearchUsed}
          pendingLabel="Szukam na OLX…"
        />
        <OfferCategoryCard
          title="Nowe"
          list={newList}
          loading={grace}
          company={company}
          model={model}
          missingType={MissingType.OffersNew}
          onRequested={hasDecathlonRows ? undefined : onSearchNew}
          pendingLabel={hasDecathlonRows ? undefined : 'Szukam na Decathlon…'}
        />
      </div>
    </div>
  )
}

interface OfferCategoryCardProps {
  title: string
  list: BikeOffer[]
  loading: boolean
  company: string
  model: string
  missingType: MissingType
  // Used: OLX (TODO-031), New: Decathlon (TODO-032) — the search the button runs after the click + its label.
  onRequested?: () => Promise<void>
  pendingLabel?: string
}

function OfferCategoryCard({
  title,
  list,
  loading,
  company,
  model,
  missingType,
  onRequested,
  pendingLabel,
}: OfferCategoryCardProps) {
  // Skeleton during the loading grace period; afterwards the rows, or a
  // "Request data" button while the category is still empty.
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
      ) : list.length > 0 ? (
        <div className="divide-y divide-border">
          {list.map((offer, i) => (
            <OfferRow key={i} offer={offer} />
          ))}
        </div>
      ) : (
        <RequestDataButton
          variant="inline"
          company={company}
          model={model}
          missingType={missingType}
          onRequested={onRequested}
          pendingLabel={pendingLabel}
        />
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
        aria-label="Poprzednie zdjęcie"
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
        aria-label="Następne zdjęcie"
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
          {offer.is_new ? 'Nowy' : 'Używany'}
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
