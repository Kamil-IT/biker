import type { ContactMessageRequest, MissingDataRequest } from './types'

// A non-OK answer; `status` lets a caller tell "not found" (404) from a failure.
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

// POST a JSON body and parse the JSON answer. A non-OK status throws an ApiError carrying
// the backend's `detail` (or "Błąd serwera <status>"), so a caller can show it or let a
// "Poproś o dane" button become clickable again. An optional `signal` aborts the request.
export async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = (data as { detail?: unknown }).detail
    throw new ApiError(typeof detail === 'string' ? detail : `Błąd serwera ${res.status}`, res.status)
  }
  return await res.json() as T
}

export const errorMessage = (err: unknown): string =>
  err instanceof Error ? err.message : 'Coś poszło nie tak. Spróbuj ponownie.'

// Record a "Request data" click (POST /v1/bike/missing, TODO-026). Throws on a non-OK
// status so a caller can decide whether the failure matters.
export async function recordMissing(body: MissingDataRequest): Promise<void> {
  const res = await fetch('/v1/bike/missing', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Błąd serwera ${res.status}`)
}

// Send the Kontakt form (POST /v1/contact). Every failure throws an Error whose message is
// Polish and ready to show: 422 = the backend refused a field, anything else = try later.
export async function sendContactMessage(body: ContactMessageRequest): Promise<void> {
  let res: Response
  try {
    res = await fetch('/v1/contact', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    })
  } catch {
    throw new Error('Brak połączenia z serwerem. Spróbuj ponownie za chwilę.')
  }
  if (res.status === 422) throw new Error('Sprawdź adres e-mail i treść wiadomości.')
  if (!res.ok) throw new Error('Nie udało się wysłać wiadomości. Spróbuj ponownie za chwilę.')
}
