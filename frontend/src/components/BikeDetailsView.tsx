import { useState } from 'react'
import { ArrowLeft } from '@phosphor-icons/react'
import type { Bike, BikeCategory, BikeSubcategory, ComponentElement, BikeDescription, BikeReviewResponse, BikeOffer, BikeOfferResponse, UsedBikeResponse } from '../types'

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

        {/* Accessories */}
        {accessories.filter(Boolean).length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Key features">
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
        <DescriptionCard description={description} state={state} />

        {/* Offers */}
        <OffersSection offers={offers} state={offerState} title="Allegro Offers" />
        <OffersSection offers={ceneoOffers} state={ceneoState} title="Ceneo Offers" />
        <OffersSection offers={decathlonOffers} state={decathlonState} title="Decathlon Offers" />

        {/* Used bikes (OLX) */}
        <UsedBikesSection usedBikes={usedBikes} state={usedBikeState} />

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

/* ── Photo gallery ──────────────────────────────────── */

function PhotoGallery({ photos }: { photos: string[] }) {
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

function DescriptionCard({ description, state }: { description: BikeDescription | null; state: 'loading' | 'loaded' | 'error' }) {
  const [activeIdx, setActiveIdx] = useState<number | null>(null)

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

  const activeCitations = activeIdx !== null ? (description.segments[activeIdx]?.citations ?? []) : []

  return (
    <div className="mt-5 bg-card rounded-2xl border-l-2 border border-terra/40 px-5 py-4 md:px-6 md:py-5">
      <span className="font-mono text-[10px] text-muted uppercase tracking-widest block mb-2">
        Overview
      </span>

      <p className="font-body text-ink text-[13px] leading-relaxed">
        {description.segments.map((seg, i) => (
          <span key={i}>
            {seg.text}
            {seg.citations.length > 0 && (() => {
              const hosts = seg.citations.map(c => {
                try { return new URL(c.url).hostname.replace(/^www\./, '') } catch { return c.url }
              })
              return (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveIdx(activeIdx === i ? null : i)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setActiveIdx(activeIdx === i ? null : i) }}
                  className={`ml-1 font-mono text-[10px] cursor-pointer transition-colors duration-150 ${
                    activeIdx === i ? 'text-terra' : 'text-terra/60 hover:text-terra'
                  }`}
                >
                  [{hosts.join(', ')}]
                </span>
              )
            })()}
          </span>
        ))}
      </p>

      {/* Source card for the active segment */}
      {activeCitations.length > 0 && (
        <div
          className="mt-3 bg-sand rounded-xl border border-border divide-y divide-border overflow-hidden"
          style={{ animation: 'slideUp 200ms ease-out' }}
        >
          {activeCitations.map((c, i) => {
            let host: string
            try { host = new URL(c.url).hostname.replace(/^www\./, '') } catch { host = c.url }
            return (
              <a
                key={c.url || i}
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-start gap-3 px-4 py-3 group hover:bg-parchment transition-colors duration-150"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[11px] text-terra group-hover:text-terra-dark truncate">{host}</p>
                  {c.title && (
                    <p className="font-body text-[12px] text-charcoal font-medium leading-tight mt-0.5">{c.title}</p>
                  )}
                  {c.cited_text && (
                    <p className="font-body italic text-[11px] text-muted mt-1 line-clamp-2">{c.cited_text}</p>
                  )}
                </div>
                <span className="shrink-0 font-mono text-[11px] text-terra mt-0.5" aria-hidden="true">→</span>
              </a>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* ── Expert review ──────────────────────────────────── */

function ReviewSection({ review, state }: { review: BikeReviewResponse | null; state: ReviewState }) {
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
  const sourceUrl = review.ref[0] ?? null
  let sourceHost: string | null = null
  try { sourceHost = sourceUrl ? new URL(sourceUrl).hostname.replace(/^www\./, '') : null } catch { sourceHost = sourceUrl }

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
      <p className="font-body italic text-ink text-[13px] leading-relaxed">
        {clean}
      </p>
      {sourceHost && sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex items-center gap-1 font-mono text-[11px] text-terra hover:text-terra-dark transition-colors duration-150 focus-visible:outline-none focus-visible:underline"
        >
          {sourceHost}
          <span aria-hidden="true">→</span>
        </a>
      )}
    </div>
  )
}

/* ── Offers ─────────────────────────────────────────── */

function OffersSection({ offers, state, title = 'Current Offers' }: { offers: BikeOfferResponse | null; state: 'loading' | 'loaded' | 'error'; title?: string }) {
  if (state === 'loading') {
    return (
      <div className="mt-5 bg-card rounded-2xl border border-border px-5 py-4 md:px-6 md:py-5">
        <div className="shimmer h-3 w-24 rounded mb-4" />
        <div className="space-y-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="flex items-center justify-between gap-4">
              <div className="space-y-1.5 flex-1">
                <div className="shimmer h-2.5 w-16 rounded" style={{ animationDelay: `${i * 40}ms` }} />
                <div className="shimmer h-3.5 w-40 rounded" style={{ animationDelay: `${i * 40 + 20}ms` }} />
              </div>
              <div className="shimmer h-4 w-20 rounded" style={{ animationDelay: `${i * 40 + 40}ms` }} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (state === 'error' || !offers || offers.offers.length === 0) return null

  return (
    <div className="mt-5 bg-card rounded-2xl border border-border overflow-hidden">
      <div className="px-5 py-4 md:px-6 md:py-5 border-b border-border">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          {title}
        </span>
      </div>
      <div className="divide-y divide-border">
        {offers.offers.map((offer, i) => (
          <OfferRow key={i} offer={offer} />
        ))}
      </div>
    </div>
  )
}

/* ── Used bikes (OLX) ──────────────────────────────── */

function UsedBikesSection({ usedBikes, state }: { usedBikes: UsedBikeResponse | null; state: 'loading' | 'loaded' | 'error' }) {
  if (state === 'loading') {
    return (
      <div className="mt-5 bg-card rounded-2xl border border-border px-5 py-4 md:px-6 md:py-5">
        <div className="shimmer h-3 w-32 rounded mb-4" />
        <div className="space-y-3">
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
      </div>
    )
  }

  if (state === 'error' || !usedBikes || usedBikes.offers.length === 0) return null

  return (
    <div className="mt-5 bg-card rounded-2xl border border-border overflow-hidden">
      <div className="px-5 py-4 md:px-6 md:py-5 border-b border-border">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          Used Bikes · OLX
        </span>
      </div>
      <div className="divide-y divide-border">
        {usedBikes.offers.map((offer, i) => (
          <OfferRow key={i} offer={offer} />
        ))}
      </div>
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

/* ── Loading skeleton ───────────────────────────────── */

function LoadingSkeleton() {
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

function CategorySection({ category }: { category: BikeCategory }) {
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
          <SubcategorySection key={`${sub.subcategory}-${i}`} sub={sub} />
        ))}
      </div>
    </section>
  )
}

function SubcategorySection({ sub }: { sub: BikeSubcategory }) {
  return (
    <div className="px-5 py-4 md:px-6 md:py-5">
      <h3 className="font-mono text-[10px] text-muted uppercase tracking-widest mb-3">
        {sub.subcategory}
      </h3>
      <div className="space-y-5">
        {sub.elements.map((el, i) => (
          <ElementItem key={`${el.name}-${i}`} element={el} />
        ))}
      </div>
    </div>
  )
}

function ElementItem({ element }: { element: ComponentElement }) {
  const { name, description, specs } = element
  return (
    <div>
      <p className="font-display font-bold text-charcoal text-[15px] md:text-[16px] leading-tight">
        {name}
      </p>
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
