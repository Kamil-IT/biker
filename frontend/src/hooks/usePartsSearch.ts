import { useMemo, useRef, useState } from 'react'
import { errorMessage, postJson } from '../api'
import { partTypeLabel } from '../partTypes'
import { payloadToFilters, payloadToQuery, queryToPayload } from '../partsQuery'
import { DEFAULT_PART_SORT, sortParts, type PartSortOrder } from '../sortParts'
import { PATHS, partsPath } from './useRoute'
import type { PartResult, PartsFilters, PartsParseResponse, PartsSearchPayload, PartsSearchResponse } from '../types'
import { EMPTY_PARTS_FILTERS } from '../types'

export type PartsState = 'idle' | 'loading' | 'results' | 'error'
export type AiState = 'idle' | 'running' | 'error'

// Shown when /v1/parts/parse answers 400; the backend's detail is English.
const NO_MATCH_MSG = 'Nie mamy tej części w naszej bazie'

// How a search is named in the status line: its text, else its filters ("Kaseta · Shimano").
const queryLabel = (p: PartsSearchPayload): string =>
  p.search || [partTypeLabel(p.part_type), p.brand, p.model, p.groupset].filter(Boolean).join(' · ')

// State and calls of the parts search (TODO-046, /parts) — the bike search's rules (App.tsx):
// a text-only submit is parsed first (the filters fill, the search waits for a second submit);
// a submit whose text changed since the parse clears the filters and parses again; the address
// changes only when a search runs, each search a new history entry; an address opened by link
// fills the form and searches at once, without a parse; the results of the address in memory
// are shown again without a request (Back from a part); an answer to a superseded query is
// dropped. The DB search never calls AI: "Szukaj więcej z AI" (searchAi) is the only AI call.
export function usePartsSearch(navigate: (to: string) => void) {
  const [state, setState]             = useState<PartsState>('idle')
  const [query, setQuery]             = useState('')
  const [filters, setFilters]         = useState<PartsFilters>(EMPTY_PARTS_FILTERS)
  const [showFilters, setShowFilters] = useState(false)
  const [isParsing, setIsParsing]     = useState(false)
  const [noMatchMsg, setNoMatchMsg]   = useState<string | null>(null)
  const [errorMsg, setErrorMsg]       = useState<string | null>(null)
  const [parts, setParts]             = useState<PartResult[]>([])
  const [label, setLabel]             = useState('')
  // Where the list shown came from; `aiTried` = the AI search ran for this query and found nothing.
  const [source, setSource]           = useState<'db' | 'ai'>('db')
  const [aiTried, setAiTried]         = useState(false)
  const [aiState, setAiState]         = useState<AiState>('idle')
  const [aiError, setAiError]         = useState<string | null>(null)
  const [sortOrder, setSortOrder]     = useState<PartSortOrder>(DEFAULT_PART_SORT)
  const [lastUrl, setLastUrl]         = useState<string | null>(null)
  // The free text the filters shown were parsed from (see handleSearch).
  const parsedQueryRef = useRef('')
  // The canonical query of the results in memory (or in flight).
  const searchKeyRef = useRef<string | null>(null)
  // Bumped by every search run and reset: an answer — DB or AI — of an older run is dropped, also
  // when the query is the same (an AI search still in flight when the same query is searched again).
  const runRef = useRef(0)
  const resultsRef = useRef<HTMLElement>(null)

  const sortedParts = useMemo(() => sortParts(parts, sortOrder), [parts, sortOrder])

  const updateFilter = <K extends keyof PartsFilters>(key: K, val: PartsFilters[K]) =>
    setFilters(prev => ({ ...prev, [key]: val }))

  // The form as an address fills it (its text counts as already parsed), or empty.
  const fillForm = (payload: PartsSearchPayload) => {
    const f = payloadToFilters(payload)
    setQuery(payload.search ?? '')
    setFilters(f)
    setShowFilters(Object.values(f).some(v => v !== ''))
    setNoMatchMsg(null)
    parsedQueryRef.current = payload.search ?? ''
  }

  const runSearch = async (input: PartsSearchPayload, fromForm: boolean) => {
    // Through the address form, so the request and the address always agree.
    const payload = queryToPayload(payloadToQuery(input))
    const key = payloadToQuery(payload)
    if (!key) return
    const run = ++runRef.current
    searchKeyRef.current = key
    setLastUrl(partsPath(key))
    if (fromForm) navigate(partsPath(key))
    setState('loading')
    setErrorMsg(null)
    setParts([])
    setLabel(queryLabel(payload))
    setSource('db')
    setAiTried(false)
    setAiState('idle')
    setAiError(null)
    try {
      const data = await postJson<PartsSearchResponse>('/v1/parts/search', payload)
      if (runRef.current !== run) return
      setParts(data.parts)
      setState('results')
      if (fromForm) {
        setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
      }
    } catch (err) {
      if (runRef.current !== run) return
      setErrorMsg(errorMessage(err))
      setState('error')
    }
  }

  const handleSearch = async (input: PartsSearchPayload) => {
    let payload = input
    const hasStructured = Object.entries(payload).some(([k, v]) => k !== 'search' && v !== undefined)
    setNoMatchMsg(null)
    const searchText  = payload.search?.trim() ?? ''
    const textChanged = !!searchText && searchText !== parsedQueryRef.current
    if (!searchText) parsedQueryRef.current = ''

    if (searchText && (textChanged || !hasStructured)) {
      // A changed text clears the panel first, so the new text alone decides the filters.
      if (textChanged) {
        setFilters(EMPTY_PARTS_FILTERS)
        payload = { search: payload.search }
      }
      parsedQueryRef.current = searchText
      setIsParsing(true)
      try {
        const res = await fetch('/v1/parts/parse', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ text: payload.search }),
        })
        // 400 = no part attribute recognised: warn and do not search.
        if (res.status === 400) {
          setNoMatchMsg(NO_MATCH_MSG)
          setIsParsing(false)
          return
        }
        if (res.ok) {
          const parsed: PartsParseResponse = await res.json()
          if (parsed.part_type || parsed.brand || parsed.model || parsed.groupset) {
            setFilters(prev => ({
              ...prev,
              ...(parsed.part_type ? { part_type: parsed.part_type } : {}),
              ...(parsed.brand     ? { brand: parsed.brand }         : {}),
              ...(parsed.model     ? { model: parsed.model }         : {}),
              ...(parsed.groupset  ? { groupset: parsed.groupset }   : {}),
            }))
            setShowFilters(true)
            setIsParsing(false)
            return  // the user reviews the filled filters, then submits again
          }
        }
      } catch {
        // parse failed — fall through to a text-only search
      }
      setIsParsing(false)
    }
    runSearch(payload, true)
  }

  // Every entry of a /parts address. "/parts" is the start page: an empty form (the last search
  // stays in memory, the tab leads back to it). "/parts?…" fills the form and searches — unless
  // these are the results in memory.
  const enter = (routeQuery: string) => {
    const payload = queryToPayload(routeQuery)
    fillForm(payload)
    if (routeQuery && (routeQuery !== searchKeyRef.current || state === 'error')) runSearch(payload, false)
  }

  // The click on "Szukaj więcej z AI" (shown only under an empty list): one paid web search;
  // what it finds is added to the catalogue and replaces the empty list.
  const searchAi = async () => {
    const key = searchKeyRef.current
    const run = runRef.current
    if (!key || aiState === 'running') return
    setAiState('running')
    setAiError(null)
    try {
      const data = await postJson<PartsSearchResponse>('/v1/parts/search/ai', queryToPayload(key))
      if (runRef.current !== run) return
      setParts(data.parts)
      setSource('ai')
      setAiTried(true)
      setAiState('idle')
    } catch (err) {
      if (runRef.current !== run) return
      setAiError(errorMessage(err))
      setAiState('error')
    }
  }

  // "Nowe wyszukiwanie": the start page with nothing kept; `toStart` = also go to /parts.
  const reset = (toStart: boolean) => {
    setState('idle')
    setParts([])
    setErrorMsg(null)
    setAiState('idle')
    setAiError(null)
    fillForm({})
    runRef.current += 1
    searchKeyRef.current = null
    setLastUrl(null)
    setIsParsing(false)
    if (toStart) navigate(PATHS.parts)
  }

  return {
    state, query, setQuery, filters, updateFilter, showFilters, setShowFilters, isParsing, noMatchMsg, errorMsg,
    parts: sortedParts, label, source, aiTried, aiState, aiError, sortOrder, setSortOrder, lastUrl, resultsRef,
    handleSearch, enter, searchAi, reset,
  }
}

export type PartsSearch = ReturnType<typeof usePartsSearch>
