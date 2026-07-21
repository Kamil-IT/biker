import { useState } from 'react'
import type { BikeCategory, BikeSubcategory, ComponentElement, BikeDescription, DescriptionCitation } from '../types'
import { CitationChips } from './CitationChips'

export type LoadState = 'loading' | 'loaded' | 'error'

/* ── Photo gallery ──────────────────────────────────── */

export function PhotoGallery({ photos }: { photos: string[] }) {
  const [activeIdx, setActiveIdx] = useState(0)
  if (!photos.length) return null

  return (
    <div className="mt-4">
      <div className="w-full aspect-[16/9] bg-parchment rounded-xl border border-border overflow-hidden">
        <img
          key={activeIdx}
          src={photos[activeIdx]}
          alt=""
          className="w-full h-full object-cover"
          style={{ animation: 'slideUp 200ms ease-out' }}
          onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
        />
      </div>
      {photos.length > 1 && (
        <div className="flex gap-2 mt-2 overflow-x-auto pb-1">
          {photos.map((src, i) => (
            <button
              key={i}
              onClick={() => setActiveIdx(i)}
              className={`shrink-0 w-14 h-14 rounded-lg border overflow-hidden transition-all duration-150 ${
                i === activeIdx
                  ? 'border-terra ring-1 ring-terra opacity-100'
                  : 'border-border opacity-60 hover:opacity-100'
              }`}
              aria-label={`Photo ${i + 1}`}
            >
              <img
                src={src}
                alt=""
                className="w-full h-full object-cover"
                onError={e => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none' }}
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Description ────────────────────────────────────── */

export function DescriptionCard({ description, state }: { description: BikeDescription | null; state: LoadState }) {
  if (state === 'loading') {
    return (
      <div className="mt-5 bg-card rounded-2xl border border-border px-5 py-4 md:px-6 md:py-5">
        <div className="shimmer h-3 w-16 rounded mb-3" />
        <div className="space-y-2">
          <div className="shimmer h-3 w-full rounded" />
          <div className="shimmer h-3 w-5/6 rounded" />
          <div className="shimmer h-3 w-4/6 rounded" />
          <div className="shimmer h-3 w-3/4 rounded" />
        </div>
      </div>
    )
  }

  if (!description) return null

  // Aggregate all segment citations into one deduplicated source row shown
  // below the overview (Google AI Overview style).
  const seen = new Set<string>()
  const allCitations: DescriptionCitation[] = []
  for (const seg of description.segments) {
    for (const c of seg.citations) {
      if (c.url && !seen.has(c.url)) {
        seen.add(c.url)
        allCitations.push(c)
      }
    }
  }

  return (
    <div className="mt-5 bg-card rounded-2xl border-l-2 border border-terra/40 px-5 py-4 md:px-6 md:py-5">
      <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mb-2">
        Overview
      </span>

      <p className="font-body text-ink text-[13px] leading-relaxed">
        {description.segments.map((seg, i) => (
          <span key={i}>{seg.text}</span>
        ))}
      </p>

      {allCitations.length > 0 && (
        <>
          <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mt-4 mb-1">
            Sources
          </span>
          <CitationChips citations={allCitations} />
        </>
      )}
    </div>
  )
}

/* ── Expert review ──────────────────────────────────── */

// Structural type — works for both BikeReviewResponse and EquipmentReviewResponse.
// `rating` / `sources_used` are only present on bike reviews (TODO-014).
interface ReviewLike {
  score: number
  explanation: string
  ref: string[]
  rating?: number
  sources_used?: number
}

export function ReviewSection({ review, state }: { review: ReviewLike | null; state: LoadState }) {
  if (state === 'loading') {
    return (
      <div className="mt-5 bg-card rounded-2xl border border-border px-5 py-4 md:px-6 md:py-5">
        <div className="flex items-center justify-between mb-3">
          <div className="shimmer h-3 w-24 rounded" />
          <div className="shimmer h-5 w-10 rounded" />
        </div>
        <div className="space-y-2">
          <div className="shimmer h-3 w-full rounded" />
          <div className="shimmer h-3 w-5/6 rounded" />
          <div className="shimmer h-3 w-4/6 rounded" />
        </div>
      </div>
    )
  }

  if (state === 'error' || !review) return null

  const clean = review.explanation.replace(/<\/?cite[^>]*>/g, '')
  const refs = review.ref.filter(Boolean)

  const hasRating = typeof review.rating === 'number' && (review.sources_used ?? 0) > 0
  const ratingPct = hasRating ? Math.max(0, Math.min(100, (review.rating! / 10) * 100)) : 0

  // 0–10 → 1–5 filled stars. Prefer the aggregate rating; equipment reviews
  // have no `rating`, so they fall back to the headline score.
  const starBasis = hasRating ? review.rating! : review.score
  const filledStars = Math.max(1, Math.min(5, Math.round(starBasis / 2)))

  return (
    <div className="mt-5 bg-card rounded-2xl border border-border px-5 py-4 md:px-6 md:py-5">
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          Expert review
        </span>
        <div className="flex items-baseline gap-1">
          <span
            className="font-display font-bold text-charcoal tabular-nums leading-none text-[22px]"
            aria-label={`Review score ${review.score} out of 10`}
          >
            {review.score}
          </span>
          <span className="font-mono text-[11px] text-muted">/10</span>
        </div>
      </div>

      {hasRating && (
        <div className="mb-4 bg-sand rounded-xl border border-border px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
              Aggregate rating
            </span>
            <div className="flex items-baseline gap-1">
              <span
                className="font-display font-bold text-terra tabular-nums leading-none text-[18px]"
                aria-label={`Aggregate rating ${review.rating} out of 10`}
              >
                {review.rating!.toFixed(1)}
              </span>
              <span className="font-mono text-[11px] text-muted">/10</span>
            </div>
          </div>
          <div className="h-1.5 w-full bg-parchment rounded-full overflow-hidden" role="presentation">
            <div
              className="h-full bg-terra rounded-full transition-[width] duration-500 ease-out"
              style={{ width: `${ratingPct}%` }}
            />
          </div>
          <p className="font-mono text-[10px] text-muted mt-2">
            Rating from {review.sources_used} {review.sources_used === 1 ? 'source' : 'sources'}
          </p>
        </div>
      )}

      <p className="font-body italic text-ink text-[13px] leading-relaxed">
        {clean}
      </p>
      {refs.length > 0 && (
        <>
          <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mt-4 mb-2">
            Sources
          </span>
          <div className="bg-sand rounded-xl border border-border divide-y divide-border overflow-hidden">
            {refs.map((url, i) => (
              <SourceRow key={url || i} url={url} filledStars={filledStars} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// One source per row: stars | domain | "Read review →".
// Stars are decorative — derived from the aggregate rating when the backend
// supplied one (bike reviews), otherwise from the headline score (equipment
// reviews, which carry no `rating`).
function SourceRow({ url, filledStars }: { url: string; filledStars: number }) {
  let host: string
  try { host = new URL(url).hostname.replace(/^www\./, '') } catch { host = url }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
      className="flex items-center gap-3 px-4 py-3 group hover:bg-parchment transition-colors duration-150 focus-visible:outline-none focus-visible:bg-parchment"
    >
      <span
        className="shrink-0 font-mono text-[11px] text-terra tracking-tight"
        aria-label={`${filledStars} out of 5 stars`}
      >
        {'★'.repeat(filledStars)}
        <span className="text-terra/30">{'★'.repeat(5 - filledStars)}</span>
      </span>
      <span className="min-w-0 flex-1 font-mono text-[11px] text-charcoal group-hover:text-terra truncate transition-colors duration-150">
        {host}
      </span>
      <span className="shrink-0 font-mono text-[11px] text-terra group-hover:text-terra-dark whitespace-nowrap transition-colors duration-150">
        Read review <span aria-hidden="true">→</span>
      </span>
    </a>
  )
}

/* ── Loading skeleton ───────────────────────────────── */

export function LoadingSkeleton() {
  return (
    <div className="space-y-8" aria-label="Loading specifications" role="status">
      {[0, 1, 2].map(i => (
        <div key={i}>
          {/* Category header */}
          <div className="flex items-center gap-3 mb-4">
            <div
              className="shimmer w-1 h-5 rounded-full"
              style={{ animationDelay: `${i * 60}ms` }}
            />
            <div
              className="shimmer h-5 w-28 rounded"
              style={{ animationDelay: `${i * 60 + 25}ms` }}
            />
          </div>
          {/* Category card */}
          <div className="bg-card rounded-2xl border border-border divide-y divide-border">
            {[0, 1].map(j => (
              <div key={j} className="px-5 py-4 md:px-6 md:py-5 space-y-3">
                <div
                  className="shimmer h-3 w-20 rounded"
                  style={{ animationDelay: `${i * 60 + j * 40 + 50}ms` }}
                />
                <div
                  className="shimmer h-4 w-44 rounded"
                  style={{ animationDelay: `${i * 60 + j * 40 + 80}ms` }}
                />
                {[0, 1, 2].map(k => (
                  <div key={k} className="flex gap-8">
                    <div
                      className="shimmer h-3 w-28 rounded"
                      style={{ animationDelay: `${i * 60 + j * 40 + k * 25 + 110}ms` }}
                    />
                    <div
                      className="shimmer h-3 w-16 rounded"
                      style={{ animationDelay: `${i * 60 + j * 40 + k * 25 + 125}ms` }}
                    />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ))}
      <p className="sr-only" aria-live="polite">Fetching live specifications…</p>
    </div>
  )
}

/* ── Category / subcategory / element ──────────────── */

// When `onElementSelect` is provided (bike details view), each component
// element name renders as a link that opens its equipment page. When omitted
// (equipment view) the names stay as plain text.
export function CategorySection({
  category,
  onElementSelect,
}: {
  category: BikeCategory
  onElementSelect?: (name: string) => void
}) {
  return (
    <section aria-labelledby={`cat-${category.category}`}>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-1 h-5 bg-terra rounded-full shrink-0" aria-hidden="true" />
        <h2
          id={`cat-${category.category}`}
          className="font-display font-bold text-charcoal text-[17px] uppercase tracking-widest leading-none"
        >
          {category.category}
        </h2>
      </div>

      <div className="bg-card rounded-2xl border border-border divide-y divide-border overflow-hidden">
        {category.subcategories.map((sub, i) => (
          <SubcategorySection key={`${sub.subcategory}-${i}`} sub={sub} onElementSelect={onElementSelect} />
        ))}
      </div>
    </section>
  )
}

function SubcategorySection({
  sub,
  onElementSelect,
}: {
  sub: BikeSubcategory
  onElementSelect?: (name: string) => void
}) {
  return (
    <div className="px-5 py-4 md:px-6 md:py-5">
      <h3 className="font-mono text-[10px] text-muted uppercase tracking-widest mb-3">
        {sub.subcategory}
      </h3>
      <div className="space-y-5">
        {sub.elements.map((el, i) => (
          <ElementItem key={`${el.name}-${i}`} element={el} onElementSelect={onElementSelect} />
        ))}
      </div>
    </div>
  )
}

function ElementItem({
  element,
  onElementSelect,
}: {
  element: ComponentElement
  onElementSelect?: (name: string) => void
}) {
  const { name, description, specs } = element
  const linkable = !!onElementSelect && !!name
  return (
    <div>
      {linkable ? (
        <button
          type="button"
          onClick={() => onElementSelect!(name)}
          className="group inline-flex items-baseline gap-1 text-left max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40 focus-visible:rounded"
          aria-label={`View equipment details for ${name}`}
        >
          <span className="
            font-display font-bold text-[15px] md:text-[16px] leading-tight
            text-terra group-hover:text-terra-dark
            underline decoration-dotted decoration-terra/50 underline-offset-[3px]
            group-hover:decoration-solid group-hover:decoration-terra-dark
            transition-colors duration-150
          ">
            {name}
          </span>
          <span
            aria-hidden="true"
            className="shrink-0 text-[10px] leading-none text-terra group-hover:text-terra-dark transition-colors duration-150"
          >
            ↗
          </span>
        </button>
      ) : (
        <p className="font-display font-bold text-charcoal text-[15px] md:text-[16px] leading-tight">
          {name}
        </p>
      )}
      {description && (
        <p className="font-body italic text-ink text-[13px] leading-relaxed mt-0.5">
          {description}
        </p>
      )}
      {specs.length > 0 && (
        <dl className="mt-2 space-y-0.5">
          {specs.map(({ key, value }, i) => (
            <div key={`${key}-${i}`} className="flex items-baseline gap-3">
              <dt className="font-mono text-[11px] text-muted min-w-[120px] shrink-0">
                {key}
              </dt>
              <dd className="font-mono text-[11px] text-charcoal">
                {value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
