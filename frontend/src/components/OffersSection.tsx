import { useState } from 'react'
import type { BikeOffer, BikeOfferResponse, UsedBikeResponse } from '../types'
import { MissingType } from '../types'
import { recordMissing } from '../api'
import RequestDataButton from './RequestDataButton'
import { useLoadingGrace } from '../hooks/useLoadingGrace'

/* ── Offers (all sources merged, split by is_new) ───── */

type OfferState = 'loading' | 'loaded' | 'error'

// Parse a free-text price ("3 499 zł", "999,99 zł", "1.099 zł") into a number for
// sorting; unparseable sorts last. Grosze must not become digits of the złoty part
// (centrumrowerowe.pl prices carry them), so a comma/dot before exactly three digits is
// a thousands separator and any other one is the decimal point.
function priceValue(p: string): number {
  const compact = (p ?? '').replace(/\s/g, '').replace(/[.,](?=\d{3}(?!\d))/g, '')
  const m = compact.match(/\d+(?:[.,]\d+)?/)
  const n = m ? Number(m[0].replace(',', '.')) : NaN
  return Number.isFinite(n) && n > 0 ? n : Infinity
}

interface MergedOffersSectionProps {
  company: string
  model: string
  offers: BikeOfferResponse | null
  offerState: OfferState
  decathlonOffers: BikeOfferResponse | null
  decathlonState: OfferState
  centrumOffers: BikeOfferResponse | null
  centrumState: OfferState
  usedBikes: UsedBikeResponse | null
  usedBikeState: OfferState
  onSearchUsed: () => Promise<void>
  // The New card's two search buttons; each resolves to the search's `info` ("" when none).
  onSearchAllegro: () => Promise<string>
  onSearchDecathlon: () => Promise<string>
}

export default function MergedOffersSection({
  company,
  model,
  offers,
  offerState,
  decathlonOffers,
  decathlonState,
  centrumOffers,
  centrumState,
  usedBikes,
  usedBikeState,
  onSearchUsed,
  onSearchAllegro,
  onSearchDecathlon,
}: MergedOffersSectionProps) {
  // Pool every offer from all four sources (Allegro, Decathlon, centrumrowerowe, OLX),
  // then split purely on the is_new flag.
  const allOffers: BikeOffer[] = [
    ...(offers?.offers ?? []),
    ...(decathlonOffers?.offers ?? []),
    ...(centrumOffers?.offers ?? []),
    ...(usedBikes?.offers ?? []),
  ]

  const byPrice = (a: BikeOffer, b: BikeOffer) => priceValue(a.price) - priceValue(b.price)
  const usedList = allOffers.filter(o => o.is_new === false).sort(byPrice)
  const newList = allOffers.filter(o => o.is_new === true).sort(byPrice)

  // A late source can still add rows to either category, so both cards show their
  // skeleton for the first 5 s while any source is loading. The Used card then shows
  // its rows or its "Request data" button, which runs the OLX search (TODO-031). The
  // New card shows its rows and, below them, one search button per searchable shop —
  // Allegro and Decathlon — each only while that shop has no stored row for the bike
  // (a used Allegro listing sits in the Used card but still counts: re-searching would
  // be a paid run for nothing). centrumrowerowe.pl has no button: its rows come from
  // the discovery enrichment, they are either stored or not.
  const anyLoading =
    offerState === 'loading' ||
    decathlonState === 'loading' ||
    centrumState === 'loading' ||
    usedBikeState === 'loading'
  const grace = useLoadingGrace(anyLoading)
  const searches: SourceSearch[] = []
  if ((offers?.offers.length ?? 0) === 0) {
    searches.push({ key: 'allegro', run: onSearchAllegro, idleLabel: 'Poszukaj na Allegro', pendingLabel: 'Szukam na Allegro…', emptyLabel: 'Nie znaleziono na Allegro' })
  }
  if ((decathlonOffers?.offers.length ?? 0) === 0) {
    searches.push({ key: 'decathlon', run: onSearchDecathlon, idleLabel: 'Poszukaj w Decathlonie', pendingLabel: 'Szukam w Decathlonie…', emptyLabel: 'Nie znaleziono w Decathlonie' })
  }

  return (
    <div className="mt-5 bg-card rounded-2xl border border-border overflow-hidden">
      <div className="px-5 py-4 md:px-6 md:py-5 border-b border-border">
        <span className="font-mono text-[10px] text-muted uppercase tracking-widest">
          Oferty
        </span>
      </div>
      <div className="p-4 md:p-5 space-y-4">
        <OfferCategoryCard title="Używane" list={usedList} loading={grace}>
          <RequestDataButton
            variant="inline"
            company={company}
            model={model}
            missingType={MissingType.OffersUsed}
            onRequested={onSearchUsed}
            pendingLabel="Szukam na OLX…"
          />
        </OfferCategoryCard>
        <OfferCategoryCard title="Nowe" list={newList} loading={grace} keepFooter={searches.length > 0}>
          <div className={`px-5 py-4 md:px-6 md:py-5 ${newList.length > 0 ? 'border-t border-border' : ''}`}>
            {newList.length === 0 && (
              <p className="font-body italic text-ink text-[13px] leading-relaxed mb-3">
                Nie mamy jeszcze tych danych
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {searches.map(s => (
                <SourceSearchButton key={s.key} company={company} model={model} search={s} />
              ))}
            </div>
          </div>
        </OfferCategoryCard>
      </div>
    </div>
  )
}

interface OfferCategoryCardProps {
  title: string
  list: BikeOffer[]
  loading: boolean
  // What stands below the rows: shown in place of the rows while the list is empty,
  // and also under them when `keepFooter` is set (the New card's search buttons).
  children: React.ReactNode
  keepFooter?: boolean
}

function OfferCategoryCard({ title, list, loading, children, keepFooter = false }: OfferCategoryCardProps) {
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
        <>
          {list.length > 0 && (
            <div className="divide-y divide-border">
              {list.map((offer, i) => (
                <OfferRow key={i} offer={offer} />
              ))}
            </div>
          )}
          {(list.length === 0 || keepFooter) && children}
        </>
      )}
    </div>
  )
}

interface SourceSearch {
  key: string
  run: () => Promise<string>
  idleLabel: string
  pendingLabel: string
  emptyLabel: string
}

type SearchStatus = 'idle' | 'searching' | 'empty'

// One shop's on-demand search in the New card. The click records `offers_new` through
// POST /v1/bike/missing (a failed record does not stop the search), then runs the
// search. Rows that come back unmount this button in the parent; still mounted after
// the search means nothing was found, so it stays disabled with `emptyLabel` (and the
// backend's `info`, e.g. "Decathlon nie sprzedaje marki …"). A failed search makes it
// clickable again.
function SourceSearchButton({ company, model, search }: { company: string; model: string; search: SourceSearch }) {
  const [status, setStatus] = useState<SearchStatus>('idle')
  const [info, setInfo] = useState('')

  const click = async () => {
    setStatus('searching')
    await recordMissing({ company, model, missing_type: MissingType.OffersNew }).catch(() => undefined)
    try {
      setInfo(await search.run())
      setStatus('empty')
    } catch {
      setStatus('idle')
    }
  }

  const label =
    status === 'empty'     ? search.emptyLabel :
    status === 'searching' ? search.pendingLabel :
                             search.idleLabel

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={click}
        disabled={status !== 'idle'}
        aria-live="polite"
        className={`
          self-start inline-flex items-center gap-2
          px-4 py-2 rounded-full border
          font-mono text-[11px] tracking-wide
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40 focus-visible:ring-offset-2 focus-visible:ring-offset-card
          transition-colors duration-150
          ${status === 'empty'
            ? 'bg-transparent border-terra/40 text-terra cursor-default'
            : 'bg-terra border-terra text-parchment hover:bg-terra-dark hover:border-terra-dark disabled:opacity-70 disabled:cursor-wait'}
        `}
      >
        {status === 'searching' && (
          <span
            className="spin w-3 h-3 rounded-full border-2 border-parchment/30 border-t-parchment shrink-0"
            aria-hidden="true"
          />
        )}
        {label}
      </button>
      {status === 'empty' && info && (
        <p className="font-body italic text-muted text-[12px] leading-snug max-w-md">{info}</p>
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
        {/* An Allegro offer found from search results alone may carry no price (TODO-033). */}
        {offer.price ? (
          <span className="font-display font-bold text-terra tabular-nums text-[15px]">
            {offer.price}
          </span>
        ) : (
          <span className="font-mono text-[10px] text-muted">cena w ofercie</span>
        )}
      </div>
      <span className="shrink-0 font-mono text-[13px] text-terra group-hover:text-terra-dark transition-colors duration-150" aria-hidden="true">
        →
      </span>
    </a>
  )
}
