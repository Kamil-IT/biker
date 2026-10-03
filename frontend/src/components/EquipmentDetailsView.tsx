import { ArrowLeft } from '@phosphor-icons/react'
import type { BikeCategory, BikeDescription, EquipmentReviewResponse } from '../types'
import { PhotoGallery, DescriptionCard, ReviewSection, LoadingSkeleton, CategorySection } from './BikeDetailsShared'
import RequestDataButton from './RequestDataButton'
import { useLoadingGrace } from '../hooks/useLoadingGrace'

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
  name: string
  category: string | null
  categories: BikeCategory[] | null
  description: BikeDescription | null
  photos: string[]
  // Stored photos come from POST /v1/equipment/photos, a DB read of their own.
  photosState: LoadState
  state: LoadState
  error: string | null
  // Null until the review button was clicked (the review is no longer fetched on open).
  review: EquipmentReviewResponse | null
  onRequestReview: () => Promise<void>
  // "Wróć do roweru" when the view has a bike to go back to, else "Wróć".
  backLabel: string
  onBack: () => void
  onRetry: () => void
  // The details search: started automatically while nothing is stored; `detailsRun` is the
  // run in flight (both slots watch it), `onSearchDetails` starts or joins one (after a failure).
  detailsRun: Promise<void> | null
  onSearchDetails: () => Promise<void>
  // On-demand photo search behind the gallery's button.
  onSearchPhotos: () => Promise<void>
}

// The slot of a section the details search has nothing for (the description is stored).
function NoDataNote({ title, text }: { title: string; text: string }) {
  return (
    <div className="bg-card rounded-2xl border border-dashed border-border px-5 py-4 md:px-6 md:py-5">
      <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mb-2">{title}</span>
      <p className="font-body italic text-ink text-[13px] leading-relaxed">{text}</p>
    </div>
  )
}

export default function EquipmentDetailsView({
  name,
  category,
  categories,
  description,
  photos,
  photosState,
  state,
  error,
  review,
  onRequestReview,
  backLabel,
  onBack,
  onRetry,
  detailsRun,
  onSearchDetails,
  onSearchPhotos,
}: EquipmentDetailsViewProps) {
  // Each section: loading state for the first 5 s, then its data if any arrived. The details
  // search runs by itself while nothing is stored, so the Opis / Specyfikacja slots show it
  // running; after a failed run they are a "Poproś o dane" button. No /v1/bike/missing counter.
  const detailsGrace = useLoadingGrace(state === 'loading')
  const photosGrace = useLoadingGrace(photosState === 'loading')
  const hasPhotos = photos.length > 0
  const hasDescription = !!description && (
    !!description.text?.trim() || description.segments.some(seg => seg.text.trim())
  )
  const hasComponents = !!categories && categories.some(c => c.subcategories.some(s => s.elements.length > 0))
  const hasReview = !!review && review.ref.some(Boolean)

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

      {/* Equipment header */}
      <div className="mb-8">
        {category && (
          <span className="font-mono text-[11px] text-terra uppercase tracking-widest block mb-2">
            {categoryLabel(category)}
          </span>
        )}
        <h1 className="font-display font-bold text-charcoal leading-none text-[44px] sm:text-[56px]">
          {name}
        </h1>

        {/* Photo gallery */}
        {hasPhotos ? (
          <PhotoGallery photos={photos} />
        ) : photosGrace ? (
          <div className="mt-4 w-full aspect-[16/9] shimmer rounded-xl" aria-hidden="true" />
        ) : (
          <RequestDataButton
            title="Zdjęcia"
            company=""
            model={name}
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
            company=""
            model={name}
            onRequested={onSearchDetails}
            watch={detailsRun}
            pendingLabel="Szukam danych wyposażenia…"
            emptyLabel="Nie znaleziono danych"
          />
        )}

        {/* Expert review — source/forum links only, never offers; asked for by its button */}
        {hasReview ? (
          <ReviewSection review={review} state="loaded" />
        ) : (
          <RequestDataButton
            title="Recenzja ekspertów"
            company=""
            model={name}
            onRequested={onRequestReview}
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

        {/* No components: the search found a description only (or nothing — the stored
            "Opis niedostępny…" placeholder), or no details are stored yet (search running / failed) */}
        {!detailsGrace && !hasComponents && state !== 'error' && (hasDescription ? (
          <NoDataNote title="Specyfikacja" text="Brak specyfikacji dla tego produktu." />
        ) : (
          <RequestDataButton
            title="Specyfikacja"
            spacing="mt-0"
            company=""
            model={name}
            onRequested={onSearchDetails}
            watch={detailsRun}
            pendingLabel="Szukam danych wyposażenia…"
            emptyLabel="Nie znaleziono danych"
          />
        ))}

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
