import type { MouseEvent } from 'react'
import type { Bike, ExpertRating } from '../types'
import { isPlainClick } from '../hooks/useRoute'

export type { Bike }

interface ResultCardProps {
  bike: Bike
  rank: number
  isTop: boolean
  animationDelay: number
  onSelect: (bike: Bike) => void
  // The bike's address (/bike/{id}); the card is then a link. Without it, a button.
  href?: string
  // Expert rating (from the stored review) shown in the numeral, bar and aria text:
  // a number, "—" while pending, "?" when there is none.
  expertRating: ExpertRating
}

const formatScore = (score: number): string => {
  if (score === 10) return '10'
  return score.toFixed(1)
}

const ratingLabel = ({ state }: ExpertRating): string => {
  if (state === 'pending') return 'Ocena eksperta…'
  if (state === 'loaded')  return 'Ocena eksperta'
  return 'Brak oceny'
}

// Spoken form of the expert rating for the popular look's aria labels.
const ratingText = ({ state, rating }: ExpertRating): string => {
  if (state === 'pending')                  return 'ocena eksperta w trakcie wczytywania'
  if (state === 'loaded' && rating != null) return `ocena eksperta ${formatScore(rating)} na 10`
  return 'brak oceny'
}

export default function ResultCard({ bike, rank, isTop, animationDelay, onSelect, href, expertRating }: ResultCardProps) {
  const { brand, model, accessories, explanation } = bike
  // A pending or missing rating is 0 for the bar (empty). The numeral shows "—" while
  // pending and "?" when there is no rating.
  const score        = expertRating.rating ?? 0
  const scoreDisplay = expertRating.state === 'pending' ? '—'
    : expertRating.rating == null ? '?'
    : formatScore(expertRating.rating)
  const barWidth     = `${score * 10}%`
  const label        = ratingLabel(expertRating)
  const ariaScore    = ratingText(expertRating)

  const frame = {
    className: [
      'block relative bg-card rounded-2xl border overflow-hidden w-full text-left group',
      'p-6 md:p-8',
      'transition-all duration-300',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand',
      isTop
        ? 'border-border shadow-md hover:shadow-xl'
        : 'border-border hover:shadow-md',
    ].join(' '),
    style: {
      opacity: 0,
      animation: `slideUp 420ms cubic-bezier(0.22,1,0.36,1) ${animationDelay}ms forwards`,
    },
    'aria-label': `Zobacz specyfikację ${brand} ${model}, ${ariaScore}`,
  }

  // A real link to /bike/{id}: a modified or middle click opens it in a new tab.
  const handleLinkClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainClick(e)) return
    e.preventDefault()
    onSelect(bike)
  }

  const content = (
    <>
      {/* Left accent bar (top result only) */}
      {isTop && (
        <div className="absolute left-0 top-0 bottom-0 w-1 bg-terra" aria-hidden="true" />
      )}

      {/* Best match badge */}
      {isTop && (
        <div className="flex items-center gap-2 mb-5 ml-2">
          <span
            className="w-2 h-2 rounded-full bg-terra shrink-0"
            style={{ animation: 'pulseDot 2.2s ease-in-out infinite' }}
            aria-hidden="true"
          />
          <span className="font-mono text-xs uppercase tracking-widest text-terra select-none">
            Najlepsze dopasowanie
          </span>
        </div>
      )}

      {/* Score + content row */}
      <div className={`flex gap-5 md:gap-8 items-start ${isTop ? 'ml-2' : ''}`}>

        {/* Score numeral */}
        <div className="shrink-0 text-right w-20 md:w-24" aria-hidden="true">
          <div
            className={[
              'font-display font-bold leading-none tabular-nums',
              isTop
                ? 'text-terra text-[64px] md:text-[80px]'
                : 'text-charcoal text-[50px] md:text-[64px]',
            ].join(' ')}
          >
            {scoreDisplay}
          </div>
          <div className="font-mono text-[11px] text-muted mt-0.5">/ 10</div>
        </div>

        {/* Brand, model, accessories, explanation */}
        <div className="flex-1 min-w-0 pt-1">

          {/* Brand + rank */}
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2
                className={[
                  'font-display font-bold leading-tight group-hover:text-terra transition-colors duration-200',
                  isTop
                    ? 'text-charcoal text-[24px] md:text-[28px]'
                    : 'text-charcoal text-[19px] md:text-[22px]',
                ].join(' ')}
              >
                {brand}
              </h2>
              <p
                className={[
                  'font-display font-semibold leading-tight text-muted',
                  isTop ? 'text-[16px] md:text-[18px]' : 'text-[14px] md:text-[16px]',
                ].join(' ')}
              >
                {model}
              </p>
            </div>
            {!isTop && (
              <span
                className="font-mono text-xs text-muted shrink-0 mt-1 select-none"
                aria-label={`Pozycja ${rank}`}
              >
                #{rank}
              </span>
            )}
          </div>

          {/* Accessories chips */}
          {accessories.filter(Boolean).length > 0 && (
            <ul
              className="flex flex-wrap gap-1.5 mt-3 mb-3"
              aria-label="Najważniejsze cechy"
            >
              {accessories.filter(Boolean).map((acc, i) => (
                <li key={`${acc}-${i}`}>
                  <span className="font-mono text-[10px] text-ink px-2 py-0.5 bg-sand rounded-full border border-border inline-block leading-5">
                    {acc}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {/* Explanation — the bike's stored short description; absent until details exist */}
          {explanation.trim() && (
            <p
              className={[
                'font-body text-ink leading-relaxed',
                accessories.filter(Boolean).length === 0 ? 'mt-2' : '',
                isTop ? 'text-[15px] md:text-base' : 'text-sm md:text-[15px]',
              ].join(' ')}
            >
              {explanation}
            </p>
          )}
        </div>
      </div>

      {/* Score bar */}
      <div className={`mt-5 md:mt-6 ${isTop ? 'ml-2' : ''}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-[11px] text-muted uppercase tracking-wider">
            {label}
          </span>
        </div>

        <div
          className="h-1.5 rounded-full bg-border overflow-hidden"
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={10}
          aria-label={ariaScore}
        >
          {/* Keyed on the rating state so the fill animation replays from 0 once the
              rating arrives, instead of relying on the keyframe re-reading --bar-target. */}
          <div
            key={expertRating.state}
            className={`h-full rounded-full ${isTop ? 'bg-terra' : 'bg-ink'}`}
            style={{
              '--bar-target': barWidth,
              width: 0,
              animation: `fillBar 700ms cubic-bezier(0.22,1,0.36,1) ${animationDelay + 250}ms forwards`,
            } as React.CSSProperties}
          />
        </div>
      </div>

      {/* View specs cue */}
      <div
        className={`mt-3 flex justify-end ${isTop ? 'ml-2' : ''}`}
        aria-hidden="true"
      >
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted group-hover:text-terra transition-colors duration-200">
          Zobacz specyfikację →
        </span>
      </div>
    </>
  )

  return href
    ? <a href={href} onClick={handleLinkClick} {...frame}>{content}</a>
    : <button type="button" onClick={() => onSelect(bike)} {...frame}>{content}</button>
}
