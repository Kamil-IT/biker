import type { Bike } from '../types'

export type { Bike }

interface ResultCardProps {
  bike: Bike
  rank: number
  isTop: boolean
  animationDelay: number
  onSelect: (bike: Bike) => void
}

const scoreLabel = (score: number): string => {
  if (score >= 10) return 'Perfect match'
  if (score >= 9)  return 'Excellent match'
  if (score >= 8)  return 'Great match'
  if (score >= 7)  return 'Good match'
  if (score >= 5)  return 'Possible match'
  if (score >= 3)  return 'Partial match'
  if (score >= 1)  return 'Poor match'
  return 'No match'
}

const formatScore = (score: number): string => {
  if (score === 0)  return '—'
  if (score === 10) return '10'
  return score.toFixed(1)
}

export default function ResultCard({ bike, rank, isTop, animationDelay, onSelect }: ResultCardProps) {
  const { brand, model, accessories, match_score, explanation } = bike
  const scoreDisplay = formatScore(match_score)
  const barWidth     = `${match_score * 10}%`
  const label        = scoreLabel(match_score)

  return (
    <button
      type="button"
      onClick={() => onSelect(bike)}
      className={[
        'relative bg-card rounded-2xl border overflow-hidden w-full text-left group',
        'p-6 md:p-8',
        'transition-all duration-300',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand',
        isTop
          ? 'border-border shadow-md hover:shadow-xl'
          : 'border-border hover:shadow-md',
      ].join(' ')}
      style={{
        opacity: 0,
        animation: `slideUp 420ms cubic-bezier(0.22,1,0.36,1) ${animationDelay}ms forwards`,
      }}
      aria-label={`View specifications for ${brand} ${model}, match score ${match_score} out of 10`}
    >
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
            Best match
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
                aria-label={`Rank ${rank}`}
              >
                #{rank}
              </span>
            )}
          </div>

          {/* Accessories chips */}
          {accessories.filter(Boolean).length > 0 && (
            <ul
              className="flex flex-wrap gap-1.5 mt-3 mb-3"
              aria-label="Key features"
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

          {/* Explanation */}
          <p
            className={[
              'font-body text-ink leading-relaxed',
              accessories.length === 0 ? 'mt-2' : '',
              isTop ? 'text-[15px] md:text-base' : 'text-sm md:text-[15px]',
            ].join(' ')}
          >
            {explanation}
          </p>
        </div>
      </div>

      {/* Score bar */}
      <div className={`mt-5 md:mt-6 ${isTop ? 'ml-2' : ''}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-[11px] text-muted uppercase tracking-wider">
            {label}
          </span>
          <span className="font-mono text-[11px] text-muted" aria-hidden="true">
            {Math.round(match_score * 10)}%
          </span>
        </div>

        <div
          className="h-1.5 rounded-full bg-border overflow-hidden"
          role="progressbar"
          aria-valuenow={match_score}
          aria-valuemin={0}
          aria-valuemax={10}
          aria-label={`Match score: ${match_score} out of 10`}
        >
          <div
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
          View specs →
        </span>
      </div>
    </button>
  )
}
