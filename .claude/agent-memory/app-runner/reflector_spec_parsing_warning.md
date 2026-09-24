---
name: reflector-spec-parsing-warning
description: Recurring non-fatal backend warning on POST /v1/bike/details — reflector component specs come back as bare strings instead of dicts
metadata:
  type: project
---

`app.bike_details_finder` (behind `POST /v1/bike/details`) periodically logs
`biker.details spec[n] is not a dict: 'Front reflector'` (also seen for Rear
reflector, Pedal reflectors, Wheel reflectors, Spoke reflectors) while
processing the Accessories component category. This has recurred across
multiple separate `/v1/bike/details` calls during normal dev-server operation
(observed repeatedly on 2026-07-22).

**Why:** The LLM-returned JSON for the Accessories category sometimes emits a
spec list item as a plain string (e.g. `"Front reflector"`) instead of the
expected `{name, value}`-shaped dict. The backend's non-502 error contract
(see project CLAUDE.md — parse errors must never surface as 502) logs and
skips the offending entry rather than crashing, so the endpoint still returns
200 — this is graceful degradation, not a service outage.

**How to apply:** When the app-runner sees this log line, do NOT treat it as
a crash or increment toward a crash-loop — verify the backend is still
answering `GET /docs` with 200 and log it as a `warn` event, not `error`.
This is a known latent data-quality bug in the Accessories category JSON
shape (likely worth a real fix in `app/prompts/bike_details_accessories.md`
or the parsing logic in `app/bike_details_finder.py`), but it does not affect
service health.
