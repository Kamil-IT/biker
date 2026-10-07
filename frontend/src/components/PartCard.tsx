import type { MouseEvent } from 'react'
import type { PartResult } from '../types'
import { equipmentPath, isPlainClick } from '../hooks/useRoute'
import { partTypeLabel } from '../partTypes'
import TileStage from './TileStage'

interface PartCardProps {
  part: PartResult
  animationDelay: number
  onSelect: (part: PartResult) => void
}

// A cassette-like drawing for the empty stage (no photo yet).
function PartArt() {
  return (
    <svg
      viewBox="0 0 64 64" fill="none" stroke="#C3B6A2" strokeWidth="2.2" aria-hidden="true"
      className="w-[34%] max-w-26"
    >
      <circle cx="32" cy="32" r="27" strokeDasharray="3 2.6" />
      <circle cx="32" cy="32" r="21" /><circle cx="32" cy="32" r="15" /><circle cx="32" cy="32" r="6" />
    </svg>
  )
}

// A parts-catalogue tile (TODO-046): the "Kadr" tile of the bike results without the expert
// rating plate and bar — "Marka · Typ", the model, chips of the key parameters, the short
// description. A part this AI search added to the catalogue carries "Nowe z AI". A real link
// to /equipment/{id}: a modified or middle click opens it in a new tab.
export default function PartCard({ part, animationDelay, onSelect }: PartCardProps) {
  const typeLabel = partTypeLabel(part.part_type)
  const eyebrow = [part.brand, typeLabel].filter(Boolean).join(' · ')
  const chips = part.key_specs.filter(Boolean)
  const text = part.short_description.trim()
  const href = equipmentPath(part.id)

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainClick(e)) return
    e.preventDefault()
    onSelect(part)
  }

  const label = [`Zobacz szczegóły: ${part.brand} ${part.model}`.replace(/\s+/g, ' ').trim(),
    typeLabel.toLowerCase(), part.is_new ? 'nowe z AI' : ''].filter(Boolean).join(', ')

  return (
    <a
      href={href}
      onClick={handleClick}
      aria-label={label}
      className={[
        'result-tile flex flex-col h-full w-full text-left group bg-card rounded-2xl border border-border overflow-hidden',
        'transition-[border-color,box-shadow] duration-150',
        'hover:border-terra hover:shadow-[0_10px_28px_-18px_rgb(43_38_32/0.55)]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand',
      ].join(' ')}
      style={{ opacity: 0, animation: `slideUp 420ms cubic-bezier(0.22,1,0.36,1) ${animationDelay}ms forwards` }}
    >
      <TileStage
        photo={part.photo}
        alt={`${part.brand} ${part.model}`.trim()}
        art={<PartArt />}
        emptyText="Brak zdjęcia. Poproś o nie w szczegółach części."
      >
        {part.is_new && (
          <span className="absolute top-3 left-3 px-2 pt-[0.22rem] pb-[0.18rem] bg-terra text-parchment rounded-[0.45rem] font-display font-bold text-[0.85rem] tracking-[0.04em] leading-tight">
            Nowe z AI
          </span>
        )}
      </TileStage>

      <div className="flex flex-col gap-2 flex-1 p-4 pb-5">
        {eyebrow && <p className="font-display font-semibold text-base leading-none text-muted">{eyebrow}</p>}
        <h2 className="font-display font-bold text-[1.6rem] leading-[1.02] text-charcoal group-hover:text-terra transition-colors duration-150">
          {part.model}
        </h2>

        {chips.length > 0 && (
          <ul className="flex flex-wrap gap-1.5 mt-0.5" aria-label="Parametry">
            {chips.map((chip, i) => (
              <li key={`${chip}-${i}`}>
                <span className="font-mono text-[10.5px] text-ink px-2 py-0.5 bg-sand rounded-full border border-border inline-block leading-[1.6]">
                  {chip}
                </span>
              </li>
            ))}
          </ul>
        )}

        {text
          ? <p className="font-body text-sm text-ink leading-relaxed line-clamp-3">{text}</p>
          : <p className="font-body italic text-sm text-muted">Nie mamy jeszcze opisu tej części.</p>}
      </div>
    </a>
  )
}
