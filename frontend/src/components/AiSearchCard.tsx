interface AiSearchCardProps {
  running: boolean
  onSearch: () => void
}

// "Szukaj więcej z AI" (TODO-046): shown under "Nie znaleźliśmy żadnej części" only — never
// under results. The AI search runs on this click only (a paid web search), never by itself.
export default function AiSearchCard({ running, onSearch }: AiSearchCardProps) {
  return (
    <div className="mt-2 px-5 py-5 md:px-6 bg-card border border-dashed border-border rounded-2xl flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
      <div className="max-w-[34rem]">
        <h3 className="font-display font-bold text-xl leading-tight text-charcoal">Nie ma tu tego, czego szukasz?</h3>
        <p className="mt-1 font-body text-sm text-ink leading-relaxed">
          Przeszukamy sieć i dopiszemy nowe części do katalogu. To potrwa do ok. 40 s.
        </p>
      </div>
      <button
        type="button"
        onClick={onSearch}
        disabled={running}
        aria-busy={running}
        className="
          inline-flex items-center gap-2 shrink-0
          px-5 py-2.5
          bg-transparent text-terra border border-terra rounded-xl
          font-display font-bold text-base tracking-wider uppercase
          hover:bg-terra hover:text-parchment
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand
          disabled:opacity-65 disabled:cursor-progress disabled:hover:bg-transparent disabled:hover:text-terra
          transition-colors duration-150
        "
      >
        {running ? (
          <>
            <span className="spin w-3.5 h-3.5 rounded-full border-2 border-terra/30 border-t-terra" aria-hidden="true" />
            Szukam w sieci…
          </>
        ) : 'Szukaj więcej z AI'}
      </button>
    </div>
  )
}
