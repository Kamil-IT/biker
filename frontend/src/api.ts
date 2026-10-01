// POST a JSON body and parse the JSON answer. A non-OK status throws an Error carrying
// the backend's `detail` (or "Błąd serwera <status>"), so a caller can show it or let a
// "Poproś o dane" button become clickable again.
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail ?? `Błąd serwera ${res.status}`)
  }
  return await res.json() as T
}
