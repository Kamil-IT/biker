import { useRef, useState } from 'react'
import { ArrowLeft } from '@phosphor-icons/react'
import type { Bike, BikeCategory, BikeDescription, ComponentElement, BikeReviewResponse, BikeOfferResponse, UsedBikeResponse } from '../types'
import { MissingType } from '../types'
import { PhotoGallery, DescriptionCard, ReviewSection, LoadingSkeleton, CategorySection } from './BikeDetailsShared'
import RequestDataButton from './RequestDataButton'
import MergedOffersSection from './OffersSection'
import { useLoadingGrace } from '../hooks/useLoadingGrace'

type ReviewState = 'loading' | 'loaded' | 'error'

interface BikeDetailsViewProps {
  bike: Bike
  categories: BikeCategory[] | null
  description: BikeDescription | null
  // Stored photos from POST /v1/bike/photos — a DB read of their own, independent of
  // the details request.
  photos: string[]
  photosState: 'loading' | 'loaded' | 'error'
  state: 'loading' | 'loaded' | 'error'
  error: string | null
  review: BikeReviewResponse | null
  reviewState: ReviewState
  offers: BikeOfferResponse | null
  offerState: 'loading' | 'loaded' | 'error'
  usedBikes: UsedBikeResponse | null
  usedBikeState: 'loading' | 'loaded' | 'error'
  decathlonOffers: BikeOfferResponse | null
  decathlonState: 'loading' | 'loaded' | 'error'
  // Stored centrumrowerowe.pl offers — a DB read only, no search behind them.
  centrumOffers: BikeOfferResponse | null
  centrumState: 'loading' | 'loaded' | 'error'
  // "Wróć do wyników" when there is a result list to go back to, else "Wróć".
  backLabel: string
  onBack: () => void
  onRetry: () => void
  onEquipmentSelect: (element: ComponentElement) => void
  // On-demand OLX search behind the Used card's "Request data" button (TODO-031).
  onSearchUsed: () => Promise<void>
  // On-demand Allegro and Decathlon searches, one button each in the New card
  // (TODO-032 / TODO-033); each resolves to the search's `info`.
  onSearchAllegro: () => Promise<string>
  onSearchDecathlon: () => Promise<string>
  // On-demand photo search behind the gallery's "Request data" button.
  onSearchPhotos: () => Promise<void>
  // On-demand review search behind the Review section's "Request data" button (TODO-037).
  onSearchReview: () => Promise<void>
  // Description + component tree come from one on-demand search (TODO-041).
  onSearchDetails: () => Promise<void>
}

export default function BikeDetailsView({
  bike,
  categories,
  description,
  photos,
  photosState,
  state,
  error,
  review,
  reviewState,
  offers,
  offerState,
  usedBikes,
  usedBikeState,
  decathlonOffers,
  decathlonState,
  centrumOffers,
  centrumState,
  backLabel,
  onBack,
  onRetry,
  onEquipmentSelect,
  onSearchUsed,
  onSearchAllegro,
  onSearchDecathlon,
  onSearchPhotos,
  onSearchReview,
  onSearchDetails,
}: BikeDetailsViewProps) {
  const { brand, model, accessories } = bike
  // Each section: loading state for the first 5 s, then its data if any arrived,
  // otherwise a "Request data" button (also after an empty or failed response).
  const detailsGrace = useLoadingGrace(state === 'loading')
  const reviewGrace = useLoadingGrace(reviewState === 'loading')
  const photosGrace = useLoadingGrace(photosState === 'loading')
  const hasPhotos = photos.length > 0
  const hasDescription = !!description && (
    !!description.text?.trim() || description.segments.some(seg => seg.text.trim())
  )
  const hasComponents = !!categories && categories.some(c => c.subcategories.some(s => s.elements.length > 0))
  // One search fills both halves, so the button runs it whenever either is missing; the
  // backend refuses to search when the stored details are complete (description AND components).
  // The Opis and Specyfikacja buttons share ONE run: a click while it is in flight joins it,
  // and the other button watches the same promise (spinner, no second request).
  const detailsRunRef = useRef<Promise<void> | null>(null)
  const [detailsRun, setDetailsRun] = useState<Promise<void> | null>(null)
  const runDetails = () => {
    if (detailsRunRef.current) return detailsRunRef.current
    const run = onSearchDetails()
    detailsRunRef.current = run
    setDetailsRun(run)
    const clear = () => { detailsRunRef.current = null; setDetailsRun(null) }
    run.then(clear, clear)
    return run
  }
  const searchDetails = !(hasDescription && hasComponents) ? runDetails : undefined
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
      >
        <ArrowLeft size={12} weight="bold" aria-hidden="true" />
        {backLabel}
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
        </div>

        {/* Photo gallery */}
        {hasPhotos ? (
          <PhotoGallery photos={photos} />
        ) : photosGrace ? (
          <div className="mt-4 w-full aspect-[16/9] shimmer rounded-xl" aria-hidden="true" />
        ) : (
          <RequestDataButton
            title="Zdjęcia"
            company={brand}
            model={model}
            missingType={MissingType.Photos}
            onRequested={onSearchPhotos}
            pendingLabel="Szukam zdjęć…"
            emptyLabel="Nie znaleziono zdjęć"
          />
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
          <RequestDataButton
            title="Opis"
            company={brand}
            model={model}
            missingType={MissingType.Description}
            onRequested={searchDetails}
            watch={detailsRun}
            pendingLabel="Szukam danych roweru…"
            emptyLabel="Nie znaleziono danych"
          />
        )}

        {/* Offers — all sources pooled, split by is_new (Used on top, New below) */}
        <MergedOffersSection
          company={brand}
          model={model}
          offers={offers}
          offerState={offerState}
          decathlonOffers={decathlonOffers}
          decathlonState={decathlonState}
          centrumOffers={centrumOffers}
          centrumState={centrumState}
          usedBikes={usedBikes}
          usedBikeState={usedBikeState}
          onSearchUsed={onSearchUsed}
          onSearchAllegro={onSearchAllegro}
          onSearchDecathlon={onSearchDecathlon}
        />

        {/* Review */}
        {hasReview ? (
          <ReviewSection review={review} state="loaded" />
        ) : reviewGrace ? (
          <ReviewSection review={null} state="loading" />
        ) : (
          <RequestDataButton
            title="Recenzja ekspertów"
            company={brand}
            model={model}
            missingType={MissingType.Review}
            onRequested={onSearchReview}
            pendingLabel="Szukam recenzji…"
            emptyLabel="Nie znaleziono recenzji"
          />
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
            onRequested={searchDetails}
            watch={detailsRun}
            pendingLabel="Szukam danych roweru…"
            emptyLabel="Nie znaleziono danych"
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
