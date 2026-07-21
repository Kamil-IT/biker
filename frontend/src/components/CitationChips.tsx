import type { DescriptionCitation } from '../types'

/* ── Citation footnote chips (Google AI Overview style) ──
 * Renders a row of small source chips below a paragraph. Each chip shows the
 * source domain, links out in a new tab, and reveals the full URL (and title,
 * when available) on hover via the native tooltip.
 * Accepts either structured `citations` or a bare `urls` array. */

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

interface Chip {
  url: string
  host: string
  tooltip: string
}

function Chips({ chips }: { chips: Chip[] }) {
  if (!chips.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-2">
      {chips.map((chip, i) => (
        <a
          key={chip.url || i}
          href={chip.url}
          target="_blank"
          rel="noopener noreferrer"
          title={chip.tooltip}
          className="
            inline-flex items-center gap-1 max-w-[220px]
            rounded-full border border-terra/30 bg-terra/5
            px-2.5 py-1 font-mono text-[10px] text-terra
            hover:border-terra hover:bg-terra/10 hover:text-terra-dark
            transition-colors duration-150
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40
          "
        >
          <span
            className="w-1 h-1 rounded-full bg-terra/60 shrink-0"
            aria-hidden="true"
          />
          <span className="truncate">{chip.host}</span>
        </a>
      ))}
    </div>
  )
}

export function CitationChips({
  citations,
  urls,
}: {
  citations?: DescriptionCitation[]
  urls?: string[]
}) {
  if (citations && citations.length) {
    const chips = citations.map(c => ({
      url: c.url,
      host: hostOf(c.url),
      tooltip: c.title ? `${c.title} — ${c.url}` : c.url,
    }))
    return <Chips chips={chips} />
  }

  if (urls && urls.length) {
    const chips = urls
      .filter(Boolean)
      .map(url => ({ url, host: hostOf(url), tooltip: url }))
    return <Chips chips={chips} />
  }

  return null
}
