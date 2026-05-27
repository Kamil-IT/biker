import type { DescriptionCitation } from '../types'

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

/* Google AI Overview-style source chips: one clickable domain badge per
   citation, deduplicated by URL, tinted with the terracotta accent. */
export default function CitationChips({ citations }: { citations: DescriptionCitation[] }) {
  const seen = new Set<string>()
  const unique = citations.filter(c => {
    if (!c.url || seen.has(c.url)) return false
    seen.add(c.url)
    return true
  })

  if (unique.length === 0) return null

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {unique.map(c => (
        <a
          key={c.url}
          href={c.url}
          target="_blank"
          rel="noopener noreferrer"
          title={c.url}
          className="
            inline-flex items-center gap-1 px-2 py-0.5 rounded-full leading-5
            font-mono text-[10px] text-terra
            bg-terra/5 border border-terra/30
            hover:bg-terra/10 hover:text-terra-dark hover:border-terra/50
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/40
            transition-colors duration-150
          "
        >
          {hostOf(c.url)}
          <span aria-hidden="true">↗</span>
        </a>
      ))}
    </div>
  )
}
