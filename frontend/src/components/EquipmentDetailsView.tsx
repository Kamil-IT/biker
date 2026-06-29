import { ArrowLeft } from '@phosphor-icons/react'
import type { BikeCategory, BikeDescription, EquipmentReviewResponse } from '../types'
import { PhotoGallery, DescriptionCard, ReviewSection, LoadingSkeleton, CategorySection } from './BikeDetailsShared'

type LoadState = 'loading' | 'loaded' | 'error'

const CATEGORY_LABELS: Record<string, string> = {
  helmets: 'Helmet',
  lights: 'Lights & electronics',
  locks: 'Locks & security',
  apparel: 'Apparel, bags & accessories',
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
  state: LoadState
  error: string | null
  review: EquipmentReviewResponse | null
  reviewState: LoadState
  onBack: () => void
  onRetry: () => void
}

export default function EquipmentDetailsView({
  company,
  model,
  category,
  categories,
  description,
  photos,
  state,
  error,
  review,
  reviewState,
  onBack,
  onRetry,
}: EquipmentDetailsViewProps) {
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
        aria-label="Back to bike details"
      >
        <ArrowLeft size={12} weight="bold" aria-hidden="true" />
        Back
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
        {state === 'loading' && photos.length === 0 && (
          <div className="mt-4 w-full aspect-[16/9] shimmer rounded-xl" aria-hidden="true" />
        )}
        {state !== 'loading' && <PhotoGallery photos={photos} />}

        {/* Description */}
        <DescriptionCard description={description} state={state} />

        {/* Expert review — source/forum links only, never offers */}
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
        {state === 'loaded' && categories && categories.length > 0 && (
          <div
            className="space-y-8"
            style={{ opacity: 0, animation: 'slideUp 350ms ease-out forwards' }}
          >
            {categories.map(cat => (
              <CategorySection key={cat.category} category={cat} />
            ))}
          </div>
        )}

        {/* Loaded but empty */}
        {state === 'loaded' && (!categories || categories.length === 0) && (
          <p className="font-body text-sm text-muted italic">
            No detailed specifications were found for this item.
          </p>
        )}
      </div>
    </div>
  )
}
