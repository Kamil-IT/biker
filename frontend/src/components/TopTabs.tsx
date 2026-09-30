import type { MouseEvent } from 'react'
import { ROUTES, type Route } from '../hooks/useRoute'

const TABS: { to: Route; label: string }[] = [
  { to: ROUTES.search,  label: 'Szukanie rowerów' },
  { to: ROUTES.fit,     label: 'Rower na Twoją miarę' },
  { to: ROUTES.contact, label: 'Kontakt' },
]

interface Props {
  active: Route
  onNavigate: (to: Route) => void
}

// TODO-041: the tab row under the BIKER wordmark. Plain links, so a modified or middle
// click still opens the tab in a new browser tab; a plain click navigates in place.
export default function TopTabs({ active, onNavigate }: Props) {
  const handleClick = (e: MouseEvent<HTMLAnchorElement>, to: Route) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    onNavigate(to)
  }

  return (
    <nav aria-label="Główna nawigacja">
      <ul className="flex gap-4 min-[421px]:gap-7 m-0 p-0 list-none">
        {TABS.map(({ to, label }) => {
          const isActive = to === active
          return (
            <li key={to}>
              <a
                href={to}
                onClick={e => handleClick(e, to)}
                aria-current={isActive ? 'page' : undefined}
                className={[
                  'group relative block pt-1 pb-3 whitespace-nowrap',
                  'font-display font-semibold text-base min-[421px]:text-[17px] tracking-[0.01em]',
                  'transition-colors duration-150',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra/50 focus-visible:rounded',
                  isActive ? 'text-charcoal' : 'text-ink hover:text-terra',
                ].join(' ')}
              >
                {label}
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
