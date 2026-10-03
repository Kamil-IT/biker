# Contact form ("Napisz do nas") — manual test plan and results

Task (the user, 2026-10-03): the Kontakt tab's "Napisz do nas" form gets a backend that saves what a visitor writes into the database.
Change set: uncommitted diff of `cez/09bf0edc` against `main` (080347a). Tester: manual-tester skill, 2026-10-03.

## Assumptions (made autonomously, the user asked not to be consulted)

- Messages are only stored (`contact_message`) and read by hand with SQL. No e-mail, no admin list, no rate limit.
- Name optional; e-mail, topic and message required. Limits: name ≤ 100, e-mail ≤ 254, message ≤ 5000 characters.
- Spam: a hidden honeypot field `website`. When it is filled, the request answers 200 but stores nothing.

## Environment

| Item | Value |
|---|---|
| Database | local PostgreSQL `biker-pg` (`localhost:5432/biker`), table `contact_message` created by `init_db()` at backend start |
| Backend | `uvicorn app.main:app --port 8003` (8000–8002 taken) |
| Frontend | Vite on 5188, `BIKER_API_URL=http://127.0.0.1:8003` (5173–5177 taken) |
| Tools | Python Playwright (global python), headless Chromium; curl; SQLAlchemy from the backend venv for DB checks |

## Traceability

| # | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | Filled-in form is sent and saved in the DB | `frontend/src/components/ContactPage.tsx`, `frontend/src/api.ts` `sendContactMessage`, `backend/app/contact_routes.py`, `backend/app/models.py` `ContactMessage` | Implemented |
| R2 | The visitor sees the outcome (sending, sent, error) | `ContactPage.tsx` | Implemented |
| R3 | Bad input is refused (client and server) | `ContactPage.tsx` (`required`, `pattern`, `maxLength`, blank-message check), `backend/app/schemas.py` `ContactMessageRequest` | Implemented |
| R4 | A failed save never looks sent | `contact_routes.py` (503), `api.ts` (Polish error per status) | Implemented |
| X1 | (not requested) honeypot anti-spam field | `ContactPage.tsx`, `contact_routes.py` | Extra — a cheap guard for a public form that writes to the DB |
| X2 | (not requested) "Imię (opcjonalnie)" label, new intro sentence, "wkrótce" notice removed | `ContactPage.tsx` | Extra — follows from the form going live |

## Test cases

| ID | Req | Prio | Case (steps → expected) |
|---|---|---|---|
| TC-01 | R1 | High | Open `/kontakt` → form enabled, no "wkrótce" notice, 5 topics with the old Polish labels |
| TC-02 | R1/R2 | High | Fill " Ola " / `ola.qa@example.pl` / "Błędne dane roweru" / Polish text → submit → "Dziękujemy!" with the e-mail; one `POST /v1/contact` 200; DB row `name='Ola'`, `topic='wrong_data'`, text identical, `created_at` set |
| TC-03 | R1 | Medium | Name left empty → sent; DB row `name=''` |
| TC-04 | R3 | High | E-mail empty → browser blocks the submit, no request |
| TC-05 | R3 | High | E-mail `a@b` (valid for `type=email`, not for the backend) → blocked by `pattern`, no request |
| TC-06 | R3 | High | Message of spaces/newlines only → "Wpisz treść wiadomości.", no request |
| TC-07 | R3 | Medium | BVA: typing 5001 characters leaves 5000 in the box; a 5000-character message is stored in full |
| TC-08 | R2 | Medium | After sending, "Napisz kolejną wiadomość" → form back, name + e-mail kept, message empty, topic reset; a second send stores a second row |
| TC-09 | R4 | High | Backend answers 503 (route stub) → alert "Nie udało się wysłać wiadomości. Spróbuj ponownie za chwilę.", fields kept, button clickable |
| TC-10 | R4 | Medium | Backend answers 422 (route stub) → alert "Sprawdź adres e-mail i treść wiadomości." |
| TC-11 | R4 | Medium | Network failure (route abort) → alert "Brak połączenia z serwerem. Spróbuj ponownie za chwilę." |
| TC-12 | R2 | Medium | Slow backend (2 s stub delay) → button "Wysyłam…", fields disabled; a double click sends one request |
| TC-13 | X1 | High | Honeypot invisible and not reachable with Tab; API with `website` filled → 200 `{ok:true}`, no row |
| TC-14 | R3 | High | API: bad e-mail, unknown topic, blank message, 5001 chars, name 101 chars → 422 each, no row; NUL dropped; real backend 503 when the write fails (pytest `test_failed_write_is_503`) |
| TC-15 | R1 | Low | Keyboard only: Tab name → e-mail → topic → message → button, Enter submits; labels tied to inputs |

## Regression set

| ID | Area | Case |
|---|---|---|
| RG-01 | Tabs | Szukanie rowerów / Rower na Twoją miarę / Kontakt switch by click; deep link `/kontakt` loads; browser Back returns |
| RG-02 | Home | `/` shows the search form and the popular-bikes section; no console errors |
| RG-03 | API | `backend/scripts/test_search.py` (all no-API cases, incl. `/v1/bike/missing`) and the full pytest suite |

## Results

Script: Python Playwright, async, headless Chromium (session scratchpad, not in the repo). Each QA row uses an e-mail `qa-contact-NN@example.pl`; all of them were deleted after each round (8 rows per round).

| ID | Round 1 | Round 2 | Evidence |
|---|---|---|---|
| TC-01 | Pass | Pass | form enabled, the 5 labels unchanged |
| TC-02 | Pass | Pass | 1 × `POST /v1/contact` 200; row `name='Ola'` (trimmed), `topic='wrong_data'`, Polish text with a newline identical, `created_at` set |
| TC-03 | Pass | Pass | `name=''`, default topic `missing_bike` |
| TC-04 | Pass | Pass | `validity.valid=false`, 0 requests |
| TC-05 | Pass | Pass | `validity.patternMismatch=true` for `a@b`, 0 requests |
| TC-06 | Pass | Pass | alert "Wpisz treść wiadomości.", 0 requests |
| TC-07 | Pass | Pass | typing past 5000 leaves 5000; 5000 characters stored |
| TC-08 | Pass | Pass | name + e-mail kept, topic back to `missing_bike`, message empty; 2 rows |
| TC-09 | Pass | Pass | 503 stub → Polish alert, fields kept, button enabled, no row |
| TC-10 | Pass | Pass | 422 stub → "Sprawdź adres e-mail i treść wiadomości." |
| TC-11 | Pass | Pass | aborted request → "Brak połączenia z serwerem. Spróbuj ponownie za chwilę." |
| TC-12 | Pass | Pass | 2 s delay: "Wysyłam…", fieldset disabled, second click + Enter → still 1 request, 1 row |
| TC-13 | Pass | Pass | honeypot at x = −9999, tab order name → e-mail → topic → message → button; API with `website` → 200 `{ok:true}`, no row |
| TC-14 | Pass | Pass | 6 × 422 (bad e-mail ×2, label instead of slug, blank message, 5001 chars, 101-char name), no row; NUL dropped. The real 503 path is covered by pytest `test_failed_write_is_503` |
| TC-15 | Fail (script) | Pass | round 1 checked the labels after the submit, when the form had already been replaced by the thank-you panel. Moved the check before the submit; the expected result is unchanged |
| RG-01 | Pass | Pass | tabs by click, `aria-current`, browser Back |
| RG-02 | Pass | Pass | search form and "Najpopularniejsze rowery" visible |
| RG-03 | Pass | — | `test_search.py` against :8003: 20 passed, 0 failed, 4 skipped (3 × `--ai`, the Decathlon live run without a searcher); `pytest -m "not llm"`: 315 passed (26 new in `scripts/test_contact.py`) |

Console errors were seen only in TC-09/10/11: the browser's own "Failed to load resource" lines for the stubbed 503/422/abort, as expected.

**Round 2: 17 passed · 0 failed · 0 blocked.**
