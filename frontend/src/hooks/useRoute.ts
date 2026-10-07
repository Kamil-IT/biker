import { useCallback, useEffect, useState, type MouseEvent } from 'react'
import { canonicalQuery } from '../searchQuery'
import { canonicalQuery as canonicalPartsQuery } from '../partsQuery'

// Every view has its own address, so a link, a new tab, F5 and Back/Forward show the same
// thing. A handful of fixed patterns does not need a router library: the History API plus a
// popstate listener covers it (nginx and Vite already fall back to index.html).
export type Route =
  | { name: 'home' }
  | { name: 'search'; query: string }   // canonical query string (searchQuery.ts), never empty
  | { name: 'bike'; id: number | null }  // null: not a valid id — shown as "not found"
  | { name: 'equipment'; id: number | null }
  | { name: 'fit' }
  | { name: 'parts'; query: string }    // TODO-046: canonical partsQuery.ts string; '' = the start page
  | { name: 'contact' }

export const PATHS = { home: '/', fit: '/bike-for-your-fit', parts: '/parts', contact: '/contact' } as const
export const searchPath    = (query: string) => `/search?${query}`
export const partsPath     = (query: string) => (query ? `${PATHS.parts}?${query}` : PATHS.parts)
export const bikePath      = (id: number) => `/bike/${id}`
export const equipmentPath = (id: number) => `/equipment/${id}`

// The Polish tab addresses of TODO-041 keep working: rewritten to the new ones on load.
const LEGACY: Record<string, string> = { '/rower-na-twoja-miare': PATHS.fit, '/kontakt': PATHS.contact }

// State of a history entry: `from` = the in-app address it was opened from (the back buttons
// use it), `scrollY` = where to scroll when Back/Forward returns to it.
interface EntryState { from?: string; scrollY?: number }

const parseId = (s: string): number | null =>
  /^[1-9]\d{0,9}$/.test(s) && Number(s) <= 2147483647 ? Number(s) : null

// The route of an address and its canonical form (trailing slashes dropped, old paths
// mapped, search parameters normalised, anything unknown → "/"). /search without a usable
// parameter is the home page; /parts without one is the parts search's start page.
function resolve(pathname: string, search: string): { route: Route; url: string } {
  const trimmed = pathname.replace(/\/+$/, '') || '/'
  const path = LEGACY[trimmed] ?? trimmed
  if (path === '/search') {
    const query = canonicalQuery(search)
    if (query) return { route: { name: 'search', query }, url: searchPath(query) }
  }
  const item = /^\/(bike|equipment)\/([^/]+)$/.exec(path)
  if (item) return { route: { name: item[1] as 'bike' | 'equipment', id: parseId(item[2]) }, url: path }
  if (path === PATHS.fit) return { route: { name: 'fit' }, url: path }
  if (path === PATHS.parts) {
    const query = canonicalPartsQuery(search)
    return { route: { name: 'parts', query }, url: partsPath(query) }
  }
  if (path === PATHS.contact) return { route: { name: 'contact' }, url: path }
  return { route: { name: 'home' }, url: PATHS.home }
}

const currentUrl = () => window.location.pathname + window.location.search
const entryState = (): EntryState => (window.history.state ?? {}) as EntryState

function readLocation() {
  return resolve(window.location.pathname, window.location.search)
}

// A plain left click; a modified or middle click is left to the browser (new tab / window).
export const isPlainClick = (e: MouseEvent) =>
  e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey

export interface Location {
  route: Route
  // The in-app address the current entry was opened from (null: typed, linked or reloaded).
  from: string | null
}

export default function useRoute() {
  const [location, setLocation] = useState<Location>(() => ({ route: readLocation().route, from: entryState().from ?? null }))

  useEffect(() => {
    // Scroll positions are restored by hand: the browser would restore them before the
    // restored view has rendered.
    window.history.scrollRestoration = 'manual'
    const { url } = readLocation()
    if (url !== currentUrl()) window.history.replaceState(entryState(), '', url)
    const onPop = () => {
      const { route, url: canonical } = readLocation()
      if (canonical !== currentUrl()) window.history.replaceState(entryState(), '', canonical)
      setLocation({ route, from: entryState().from ?? null })
      // Instant, not the page's smooth scroll-behavior: the view comes back where it was.
      const y = entryState().scrollY ?? 0
      requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({ top: y, behavior: 'instant' })))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // A new history entry (or, with `replace`, the current one rewritten); the page starts at the top.
  const navigate = useCallback((to: string, opts: { replace?: boolean } = {}) => {
    const target = new URL(to, window.location.origin)
    const { route, url } = resolve(target.pathname, target.search)
    if (url === currentUrl()) {
      window.scrollTo({ top: 0 })
      return
    }
    const from = currentUrl()
    if (opts.replace) {
      window.history.replaceState({ from: entryState().from }, '', url)
    } else {
      window.history.replaceState({ ...entryState(), scrollY: window.scrollY }, '')
      window.history.pushState({ from } satisfies EntryState, '', url)
    }
    setLocation({ route, from: opts.replace ? entryState().from ?? null : from })
    window.scrollTo({ top: 0 })
  }, [])

  // A "Wróć" button: Back through the history when the entry behind is the parent view (its
  // scroll position and in-memory state come back), else a new entry for `fallback`.
  const goBack = useCallback((isParent: (url: string) => boolean, fallback: string) => {
    const from = entryState().from
    if (from && isParent(from)) window.history.back()
    else navigate(fallback)
  }, [navigate])

  return { ...location, navigate, goBack }
}
