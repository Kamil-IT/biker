import { ArrowLeft } from '@phosphor-icons/react'
import type { BikeCategory, BikeDescription, EquipmentReviewResponse } from '../types'
import { PhotoGallery, DescriptionCard, ReviewSection, LoadingSkeleton, CategorySection } from './BikeDetailsShared'
import RequestDataButton from './RequestDataButton'
import { useLoadingGrace } from '../hooks/useLoadingGrace'
import { useSharedRun } from '../hooks/useSharedRun'

type LoadState = 'loading' | 'loaded' | 'error'

const CATEGORY_LABELS: Record<string, string> = {
  helmets: 'Kask',
  lights: 'Oświetlenie i elektronika',
  locks: 'Zapięcia i zabezpieczenia',
  apparel: 'Odzież, torby i akcesoria',
  parts: 'Części rowerowe',
}

function categoryLabel(slug: string): string {
  return CATEGORY_LABELS[slug] ?? slug
}

interface EquipmentDetailsViewProps {
  company: string
  model: string
  category: string | null
  categories: BikeCategory[] | null
  description: BikeDescription | null
  photos: string[]
  // Stored photos come from POST /v1/equipment/photos, a DB read of their own.
  photosState: LoadState
  state: LoadState
  error: string | null
  review: EquipmentReviewResponse | null
  reviewState: LoadState
  onBack: () => void
  onRetry: () => void
  // On-demand details search behind the Opis / Komponenty button — one run fills both.
  onSearchDetails: () => Promise<void>
  // On-demand photo search behind the gallery's button.
  onSearchPhotos: () => Promise<void>
}

export default function EquipmentDetailsView({
  company,
  model,
  category,
  categories,
  description,
  photos,
  photosState,
  state,
  error,
  review,
  reviewState,
  onBack,
  onRetry,
  onSearchDetails,
  onSearchPhotos,
}: EquipmentDetailsViewProps) {
  // Each section: loading state for the first 5 s, then its data if any arrived, otherwise a
  // "Poproś o dane" button (also after an empty or failed read). No /v1/bike/missing counter.
  const detailsGrace = useLoadingGrace(state === 'loading')
  const photosGrace = useLoadingGrace(photosState === 'loading')
  const hasPhotos = photos.length > 0
  const hasDescription = !!description && (
    !!description.text?.trim() || description.segments.some(seg => seg.text.trim())
  )
  const hasComponents = !!categories && categories.some(c => c.subcategories.some(s => s.elements.length > 0))
  // One search fills both halves, so the button runs it whenever either is missing. The Opis
  // and Komponenty buttons share ONE run: a click while it is in flight joins it, the other
  // button watches the same promise.
  const { run: detailsRun, trigger: runDetails } = useSharedRun(onSearchDetails)
  const searchDetails = !(hasDescription && hasComponents) ? runDetails : undefined

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
        aria-label="Wróć do szczegółów roweru"
      >
        <ArrowLeft size={12} weight="bold" aria-hidden="true" />
        Wróć
      </button>

      {/* Equipment header */}
      <div className="mb-8">
        {category && (
          <span className="font-mono text-[11px] text-terra uppercase tracking-widest block mb-2">
            {categoryLabel(category)}
          </span>
        )}
        <h1 className="font-display font-bold text-charcoal leading-none text-[44px] sm:text-[56px]">
          {company || model}
        </h1>
        {company && (
          <p className="font-display font-bold text-terra leading-tight mt-0.5 text-[22px] sm:text-[28px]">
            {model}
          </p>
        )}

        {/* Photo gallery */}
        {hasPhotos ? (
          <PhotoGallery photos={photos} />
        ) : photosGrace ? (
          <div className="mt-4 w-full aspect-[16/9] shimmer rounded-xl" aria-hidden="true" />
        ) : (
          <RequestDataButton
            title="Zdjęcia"
            company={company}
            model={model}
            onRequested={onSearchPhotos}
            pendingLabel="Szukam zdjęć…"
            emptyLabel="Nie znaleziono zdjęć"
          />
        )}

        {/* Description */}
        {hasDescription ? (
          <DescriptionCard description={description} state="loaded" />
        ) : detailsGrace ? (
          <DescriptionCard description={null} state="loading" />
        ) : (
          <RequestDataButton
            title="Opis"
            company={company}
            model={model}
            onRequested={searchDetails}
            watch={detailsRun}
            pendingLabel="Szukam danych wyposażenia…"
            emptyLabel="Nie znaleziono danych"
          />
        )}

        {/* Expert review — source/forum links only, never offers */}
        <ReviewSection review={review} state={reviewState} />
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
            company={company}
            model={model}
            onRequested={searchDetails}
            watch={detailsRun}
            pendingLabel="Szukam danych wyposażenia…"
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
              <CategorySection key={cat.category} category={cat} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
