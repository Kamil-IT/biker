import type { MouseEvent } from 'react'
import { PATHS, isPlainClick } from '../hooks/useRoute'

interface Props {
  title: string
  text: string
  // A failed lookup (not a 404) offers a retry next to the way out.
  onRetry?: () => void
  onNavigate: (to: string) => void
}

// /bike/{id} or /equipment/{id} that leads nowhere — an unknown or malformed id, or a failed
// lookup. The address stays as typed; the page offers the way back to the search.
export default function NotFoundPage({ title, text, onRetry, onNavigate }: Props) {
  const goHome = (e: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainClick(e)) return
    e.preventDefault()
    onNavigate(PATHS.home)
  }

  return (
    <section className="max-w-2xl mx-auto px-4 sm:px-6 pt-14 pb-20" aria-labelledby="not-found-heading">
      <h1
        id="not-found-heading"
        className="font-display font-bold leading-[0.95] tracking-tight text-charcoal text-[40px] sm:text-[52px] mb-4"
      >
        {title}
      </h1>
      <p className="font-body text-ink text-base leading-relaxed max-w-md mb-8">{text}</p>
      <div className="flex flex-wrap items-center gap-4">
        <a
          href={PATHS.home}
          onClick={goHome}
          className="
            inline-flex items-center justify-center px-6 py-3 rounded-xl
            bg-terra hover:bg-terra-dark text-parchment
            font-display font-bold text-lg tracking-[0.04em]
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand
            transition-colors duration-150
          "
        >
          Przejdź do wyszukiwarki
        </a>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="font-mono text-[11px] text-terra uppercase tracking-wider hover:text-terra-dark focus-visible:outline-none focus-visible:underline"
          >
            Spróbuj ponownie
          </button>
        )}
      </div>
    </section>
  )
}
