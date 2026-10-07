import type { CSSProperties, MouseEvent } from 'react'
import type { Bike, ExpertRating } from '../types'
import { isPlainClick } from '../hooks/useRoute'
import { bikeCategoryLabel } from '../specLabels'
import TileStage from './TileStage'

export type { Bike }

interface ResultCardProps {
  bike: Bike
  rank: number
  isTop: boolean
  animationDelay: number
  onSelect: (bike: Bike) => void
  // The bike's address (/bike/{id}); the card is then a link. Without it, a button.
  href?: string
  // Expert rating (from the stored review) shown in the plate, bar and aria text:
  // a number, "—" while pending, "?" when there is none.
  expertRating: ExpertRating
}

const formatScore = (score: number): string => {
  if (score === 10) return '10'
  return score.toFixed(1)
}

// Spoken form of the expert rating for the aria labels.
const ratingText = ({ state, rating }: ExpertRating): string => {
  if (state === 'pending')                  return 'ocena eksperta w trakcie wczytywania'
  if (state === 'loaded' && rating != null) return `ocena eksperta ${formatScore(rating)} na 10`
  return 'brak oceny'
}

function BikeArt() {
  return (
    <svg
      viewBox="0 0 120 64" fill="none" stroke="#C3B6A2" strokeWidth="2.4"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      className="w-[46%] max-w-36"
    >
      <circle cx="26" cy="44" r="17" /><circle cx="94" cy="44" r="17" />
      <path d="M26 44 58 44 50 21Z M50 21 82 19 58 44 M82 19 94 44 M50 21 47 13 M41 13H54 M82 19 80 12 88 11" />
    </svg>
  )
}

export default function ResultCard({ bike, rank, isTop, animationDelay, onSelect, href, expertRating }: ResultCardProps) {
  const { brand, model, accessories, explanation } = bike
  const categoryLabel = bikeCategoryLabel(bike.category)

  // A pending or missing rating is 0 for the bar (empty). The numeral shows "—" while
  // pending and "?" when there is no rating.
  const score        = expertRating.rating ?? 0
  const noRating     = expertRating.state !== 'pending' && expertRating.rating == null
  const scoreDisplay = expertRating.state === 'pending' ? '—'
    : expertRating.rating == null ? '?'
    : formatScore(expertRating.rating)
  const barWidth     = `${score * 10}%`
  const ariaScore    = ratingText(expertRating)
  const chips        = (accessories ?? []).filter(Boolean)
  const text         = (explanation ?? '').trim()

  const frame = {
    className: [
      'result-tile flex flex-col h-full w-full text-left group bg-card rounded-2xl border border-border overflow-hidden',
      'transition-[border-color,box-shadow] duration-150',
      'hover:border-terra hover:shadow-[0_10px_28px_-18px_rgb(43_38_32/0.55)]',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand',
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
      {/* Photo stage: the photo is contained, never cropped, on its own edge colour */}
      <TileStage
        photo={bike.photo ?? null}
        bg={bike.photo_bg}
        alt={`${brand} ${model}`}
        art={<BikeArt />}
        emptyText="Brak zdjęcia. Poproś o nie w szczegółach roweru."
      >
        {/* Rating plate */}
        <div
          className="absolute top-3 left-3 flex items-baseline gap-1.5 px-2.5 pt-1.5 pb-1 bg-parchment border border-charcoal/10 rounded-[0.55rem] shadow-[0_2px_10px_-4px_rgb(43_38_32/0.35)]"
          aria-hidden="true"
        >
          <b
            className={[
              'font-display font-extrabold text-[1.9rem] leading-[0.9] tabular-nums',
              isTop ? 'text-terra' : noRating ? 'text-muted' : 'text-charcoal',
            ].join(' ')}
          >
            {scoreDisplay}
          </b>
          <span className="font-display font-semibold text-[0.95rem] text-muted">
            {noRating ? 'bez oceny' : '/ 10'}
          </span>
        </div>

        {/* Bottom edge = expert rating bar */}
        <div
          className="absolute inset-x-0 bottom-0 h-[5px] bg-charcoal/20"
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
            className="result-bar h-full bg-terra"
            style={{
              '--bar-target': barWidth,
              width: 0,
              animation: `fillBar 700ms cubic-bezier(0.22,1,0.36,1) ${animationDelay + 250}ms forwards`,
            } as CSSProperties}
          />
        </div>
      </TileStage>

      {/* Body */}
      <div className="flex flex-col gap-2 flex-1 p-4 pb-5">
        {categoryLabel && (
          <span className="inline-block self-start font-mono text-[10px] uppercase tracking-widest text-terra">
            {categoryLabel}
          </span>
        )}
        <div className="flex items-start justify-between gap-3">
          <p className="font-display font-semibold text-base leading-none text-muted">{brand}</p>
          <span
            className="font-mono text-xs text-muted shrink-0 select-none leading-none"
            aria-label={`Pozycja ${rank}`}
          >
            #{rank}
          </span>
        </div>
        <h2 className="font-display font-bold text-[1.6rem] leading-[1.02] text-charcoal group-hover:text-terra transition-colors duration-150">
          {model}
        </h2>

        {chips.length > 0 && (
          <ul className="flex flex-wrap gap-1.5 mt-0.5" aria-label="Najważniejsze cechy">
            {chips.map((acc, i) => (
              <li key={`${acc}-${i}`}>
                <span className="font-mono text-[10.5px] text-ink px-2 py-0.5 bg-sand rounded-full border border-border inline-block leading-[1.6]">
                  {acc}
                </span>
              </li>
            ))}
          </ul>
        )}

        {text ? (
          <p className="font-body text-sm text-ink leading-relaxed line-clamp-3">{text}</p>
        ) : chips.length === 0 ? (
          <p className="font-body italic text-sm text-muted">Nie mamy jeszcze opisu tego roweru.</p>
        ) : null}
      </div>
    </>
  )

  return href
    ? <a href={href} onClick={handleLinkClick} {...frame}>{content}</a>
    : <button type="button" onClick={() => onSelect(bike)} {...frame}>{content}</button>
}
