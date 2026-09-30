import { useCallback, useEffect, useState } from 'react'

// TODO-041: the three top tabs, each with its own URL. Three fixed paths do not need a
// router library — the History API plus a popstate listener covers back/forward, refresh
// and deep links (nginx and Vite already fall back to index.html).
export const ROUTES = {
  search:  '/',
  fit:     '/rower-na-twoja-miare',
  contact: '/kontakt',
} as const

export type Route = typeof ROUTES[keyof typeof ROUTES]

const TITLES: Record<Route, string> = {
  '/':                     'Biker — Znajdź swój idealny rower',
  '/rower-na-twoja-miare': 'Rower na Twoją miarę — Biker',
  '/kontakt':              'Kontakt — Biker',
}

const KNOWN = new Set<string>(Object.values(ROUTES))

// Trailing slashes are tolerated; an unknown path means the home page.
function readRoute(): Route {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  return (KNOWN.has(path) ? path : ROUTES.search) as Route
}

export default function useRoute(): [Route, (to: Route) => void] {
  const [route, setRoute] = useState<Route>(readRoute)

  useEffect(() => {
    // An unknown address is rewritten to "/" so the URL matches what is shown.
    const initial = readRoute()
    if (window.location.pathname !== initial) {
      window.history.replaceState(null, '', initial + window.location.search + window.location.hash)
    }
    const onPop = () => setRoute(readRoute())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    document.title = TITLES[route]
  }, [route])

  const navigate = useCallback((to: Route) => {
    if (to !== readRoute()) {
      window.history.pushState(null, '', to)
      setRoute(to)
    }
    window.scrollTo({ top: 0 })
  }, [])

  return [route, navigate]
}
