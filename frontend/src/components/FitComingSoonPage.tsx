import type { MouseEvent } from 'react'
import { ROUTES, type Route } from '../hooks/useRoute'

interface Props {
  onNavigate: (to: Route) => void
}

const STEPS = [
  { title: 'Opowiesz o sobie',         text: 'Wzrost, przekrok, gdzie i jak jeździsz oraz ile chcesz wydać.' },
  { title: 'AI zmierzy dopasowanie',   text: 'Policzy rozmiar ramy i sprawdzi, które geometrie pasują do Twojej sylwetki.' },
  { title: 'Dostaniesz swoje rowery',  text: 'Modele z naszej bazy z oceną ekspertów i aktualnymi ofertami.' },
]

// TODO-041: "Rower na Twoją miarę" tab — a coming-soon teaser for the AI bike fitter.
// Nothing here calls the backend.
export default function FitComingSoonPage({ onNavigate }: Props) {
  const goSearch = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    onNavigate(ROUTES.search)
  }

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 pb-20">
      <section className="pt-14 pb-10 md:pt-20 md:pb-14" aria-labelledby="fit-heading">
        <h1
          id="fit-heading"
          className="font-display font-bold leading-[0.92] tracking-tight text-charcoal text-[52px] sm:text-[68px] md:text-[80px] mb-4"
        >
          Rower na<br />Twoją miarę.
        </h1>
        <p className="font-body text-ink text-base md:text-[17px] leading-relaxed max-w-sm">
          Pracujemy nad doborem roweru z pomocą AI. Ta część serwisu jeszcze nie działa.
        </p>
      </section>

      <section aria-labelledby="fit-soon-heading">
        <div className="relative overflow-hidden rounded-[1.25rem] bg-charcoal text-parchment">
          <span className="absolute top-5 left-5 inline-flex items-center gap-2 px-3 py-1 rounded-full border border-terra/70 bg-charcoal/80 font-display font-semibold text-base tracking-[0.04em]">
            <span className="w-[7px] h-[7px] rounded-full bg-terra" aria-hidden="true" />
            Wkrótce
          </span>

          <svg
            viewBox="0 -50 600 380"
            className="block w-full h-auto"
            role="img"
            aria-label="Szkic roweru z liniami pomiarów: wysokość siodła, zasięg i rozmiar ramy, jeszcze bez wartości"
          >
            <defs>
              <pattern id="fit-dots" width="20" height="20" patternUnits="userSpaceOnUse">
                <circle cx="1" cy="1" r="1" fill="var(--color-ink)" />
              </pattern>
              <linearGradient id="fit-scan" x1="0" x2="1">
                <stop offset="0"    stopColor="var(--color-terra)" stopOpacity="0" />
                <stop offset="0.85" stopColor="var(--color-terra)" stopOpacity="0.22" />
                <stop offset="1"    stopColor="var(--color-terra)" stopOpacity="0.9" />
              </linearGradient>
            </defs>
            <rect y="-50" width="600" height="380" fill="url(#fit-dots)" />

            {/* Bike */}
            <g fill="none" stroke="var(--color-parchment)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="150" cy="235" r="68" strokeWidth="2" opacity="0.7" />
              <circle cx="440" cy="235" r="68" strokeWidth="2" opacity="0.7" />
              <path d="M150 235 L280 235 L250 118 Z" />
              <path d="M250 124 L392 130 L280 235" />
              <path d="M392 130 L402 160 L440 235" />
              <path d="M392 130 L386 104 L412 100" />
              <path d="M250 118 L244 100" />
              <path d="M226 98 H264" strokeWidth="5" />
              <circle cx="280" cy="235" r="11" strokeWidth="2" />
            </g>

            {/* Measurement lines, values still unknown */}
            <g fill="none" stroke="var(--color-muted)" strokeWidth="1.2" strokeDasharray="4 5">
              <path d="M540 98 V303" />
              <path d="M532 98 H548 M532 303 H548" strokeDasharray="none" />
              <path d="M245 62 H400" />
              <path d="M245 54 V70 M400 54 V70" strokeDasharray="none" />
              <path d="M292 232 L262 120" />
            </g>
            <g fill="var(--color-muted)" fontFamily="var(--font-mono)" fontSize="15">
              <text transform="translate(562 200) rotate(-90)" textAnchor="middle">wysokość siodła ?</text>
              <text x="298" y="48">zasięg ?</text>
              <text x="300" y="182">rama ?</text>
            </g>

            {/* Contact points */}
            <g>
              <circle cx="245" cy="98"  r="12" fill="none" stroke="var(--color-terra)" opacity="0.45" />
              <circle cx="245" cy="98"  r="5"  fill="var(--color-terra)" />
              <circle cx="405" cy="101" r="12" fill="none" stroke="var(--color-terra)" opacity="0.45" />
              <circle cx="405" cy="101" r="5"  fill="var(--color-terra)" />
              <circle cx="280" cy="235" r="18" fill="none" stroke="var(--color-terra)" opacity="0.45" />
              <circle cx="280" cy="235" r="5"  fill="var(--color-terra)" />
            </g>

            <rect className="scan" x="0" y="-50" width="90" height="380" fill="url(#fit-scan)" />
          </svg>

          <div className="px-6 pb-6">
            <h2 id="fit-soon-heading" className="font-display font-bold text-[28px] sm:text-[38px] leading-[1.05]">
              AI dopasuje rower do Ciebie
            </h2>
            <p className="mt-2 font-body text-parchment/75 leading-relaxed max-w-[34rem]">
              Powiesz nam, jak jeździsz i jaką masz sylwetkę, a AI dobierze rozmiar ramy i znajdzie rowery, które będą na Ciebie pasować.
            </p>
          </div>
        </div>

        <ol className="mt-12 grid gap-6 sm:grid-cols-3 list-none p-0" aria-label="Jak to będzie działać">
          {STEPS.map((step, i) => (
            <li key={step.title} className="border-t-2 border-charcoal pt-3.5">
              <span className="block mb-1.5 font-display font-extrabold text-[30px] leading-none text-terra" aria-hidden="true">
                {i + 1}
              </span>
              <h3 className="font-display font-bold text-[21px] leading-[1.1] text-charcoal mb-1">{step.title}</h3>
              <p className="font-body text-[15px] text-ink leading-relaxed">{step.text}</p>
            </li>
          ))}
        </ol>

        <div className="mt-12 pt-7 border-t border-border flex flex-wrap items-center justify-between gap-4">
          <p className="font-body text-ink">Do tego czasu możesz opisać swój rower w wyszukiwarce.</p>
          <a
            href={ROUTES.search}
            onClick={goSearch}
            className="
              inline-flex items-center justify-center px-6 py-3 rounded-xl
              bg-terra hover:bg-terra-dark text-parchment
              font-display font-bold text-lg tracking-[0.04em]
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:ring-offset-2 focus-visible:ring-offset-sand
              transition-colors duration-150
            "
          >
            Szukaj rowerów
          </a>
        </div>
      </section>
    </div>
  )
}
