import type { MouseEvent } from 'react'
import { PATHS, isPlainClick } from '../hooks/useRoute'

export type Tab = 'search' | 'fit' | 'parts' | 'contact'

interface Props {
  active: Tab
  // "Szukanie rowerów" leads back to the last search (its results are kept), else to "/".
  searchHref: string
  // "Wyszukiwanie części" likewise: the last parts search, else "/parts" (TODO-046).
  partsHref: string
  onNavigate: (to: string) => void
}

// TODO-041: the tab row under the BIKER wordmark. Plain links, so a modified or middle
// click still opens the tab in a new browser tab; a plain click navigates in place. Four
// tabs since TODO-046: below 640 px the long labels give way to short ones so the row fits
// from 360 px.
export default function TopTabs({ active, searchHref, partsHref, onNavigate }: Props) {
  const tabs: { key: Tab; to: string; label: string; short?: string }[] = [
    { key: 'search',  to: searchHref,    label: 'Szukanie rowerów' },
    { key: 'fit',     to: PATHS.fit,     label: 'Rower na Twoją miarę', short: 'Na miarę' },
    { key: 'parts',   to: partsHref,     label: 'Wyszukiwanie części',  short: 'Części' },
    { key: 'contact', to: PATHS.contact, label: 'Kontakt' },
  ]

  const handleClick = (e: MouseEvent<HTMLAnchorElement>, to: string) => {
    if (!isPlainClick(e)) return
    e.preventDefault()
    onNavigate(to)
  }

  return (
    <nav aria-label="Główna nawigacja">
      <ul className="flex gap-4 sm:gap-7 m-0 p-0 list-none">
        {tabs.map(({ key, to, label, short }) => {
          const isActive = key === active
          return (
            <li key={key}>
              <a
                href={to}
                onClick={e => handleClick(e, to)}
                aria-current={isActive ? 'page' : undefined}
                // The short label is what a narrow screen shows; the accessible name stays the full one.
                aria-label={short ? label : undefined}
                className={[
                  'group relative block pt-1 pb-3 whitespace-nowrap',
                  'font-display font-semibold text-base min-[421px]:text-[17px] tracking-[0.01em]',
                  'transition-colors duration-150',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:rounded',
                  isActive ? 'text-charcoal' : 'text-ink hover:text-terra',
                ].join(' ')}
              >
                {short ? (
                  <>
                    <span className="hidden sm:inline">{label}</span>
                    <span className="sm:hidden" aria-hidden="true">{short}</span>
                  </>
                ) : label}
                <span
                  aria-hidden="true"
                  className={[
                    'absolute left-0 right-0 -bottom-px h-[3px] rounded-t-[3px] origin-left',
                    'transition-transform duration-200 ease-out motion-reduce:transition-none',
                    isActive
                      ? 'bg-terra scale-x-100'
                      : 'bg-border scale-x-0 group-hover:scale-x-[0.35]',
                  ].join(' ')}
                />
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
