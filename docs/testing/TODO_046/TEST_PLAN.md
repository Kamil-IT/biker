# TODO-046 Parts search tab — manual test plan and results

Task: `backlog/TODO_046_PARTS_SEARCH.md` (tab "Wyszukiwanie części", `/parts`, `POST /v1/parts/parse`, `/v1/parts/search`, `/v1/parts/search/ai`, catalogue-part equipment view).
Reference wording: `docs/mockups/wyszukiwanie-czesci/wyszukiwanie-czesci.html` (STATES start, parsed, db, empty, ai-loading, ai, ai-none, nomatch).
Change set: `feature/todo-046-parts-search` against `origin/main` (frontend + backend + searcher; docs of other agents not assessed).
Tester: manual-tester workflow (ISTQB, Playwright headless Chromium), 2026-10-07. Round 1.

## Environment

| Item | Value |
|---|---|
| REAL stack | frontend Vite dev (StrictMode) `http://localhost:5182` -> backend `127.0.0.1:8003` -> real searcher `127.0.0.1:8103`. The backend's Anthropic key has no credits: parse and "Szukaj więcej z AI" answer 400 |
| FAKE-AI stack | frontend `http://localhost:5183` -> backend `127.0.0.1:8004` (same code, only the two Anthropic calls faked, every call logged in `qa046\fake_calls.log`), searcher not configured |
| Database | shared local PostgreSQL; fixtures category `parts`, part_type cassette, Shimano: 82 Deore CS-M6100-12 and 84 Deore XT CS-M8100-12 (description + photo), 83 SLX CS-M7100-12 and 85 XTR CS-M9100-12 (neither). The fake AI stores 4 SRAM cassettes (removed once with a scratch script between rounds so `Nowe z AI` could be seen) |
| Cost guard kept | REAL stack: exactly one details search (id 83) and one photo search (id 83); "Szukaj więcej z AI" clicked once (refused for free, 400); no SRAM or id 85 opened |
| Evidence | scratch dir `...\tmp\...\qa046\` (`h.py` harness, `s1.py`-`s6.py` suites, `results_s*.json`, `shots\`, `fake_calls.log`). Nothing was written into the repo except this file |
| Oracle | wording from the mockup `STATES` and the task file; counts of `/v1/parts/*` requests recorded with a Playwright request listener; AI calls counted from `fake_calls.log` |

## Traceability (requirement -> code -> status)

| # | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | Tab "Wyszukiwanie części" between "Rower na Twoją miarę" and "Kontakt"; short labels "Na miarę" / "Części" below 640 px; fits 360 px; active on `/parts` and on `/equipment/{id}` opened from `/parts`; tab link = last parts search | `TopTabs.tsx:20-24,53-59`, `App.tsx:358-361` (`equipmentInCatalogue`) | Implemented |
| R2 | Routes `/parts`, `/parts?q&type&brand&model&group`, canonical order, unknown params / bad type dropped, `PATHS.parts`, `partsPath` | `useRoute.ts:14-19,46-49`, `partsQuery.ts:8-49` | Implemented |
| R3 | Filters panel: type (12), brand, model, group; no type-specific params | `PartsSearchInput.tsx:94-120`, `partTypes.ts` | Implemented |
| R4 | Text-only submit parses, filters fill, search waits for second submit; changed text clears filters and re-parses; unchanged text searches at once; 400 -> warning, no search | `usePartsSearch.ts:102-148` | Implemented |
| R5 | Address changes only when a search runs; each search a new history entry; address from a link searches at once without parse; same address in memory -> no request; stale answer dropped | `usePartsSearch.ts:80-100,152-158` | Implemented (stale answer verified for the DB search only) |
| R6 | Result heading, status lines (DB, AI, AI-none, not-found), "Nowe wyszukiwanie" | `PartsSearchPage.tsx:44-58,118-139` | Implemented |
| R7 | Tiles "Kadr": "Marka · Typ", model heading, chips, short description or "Nie mamy jeszcze opisu tej części.", photo on `#FFFFFF` or drawing + "Brak zdjęcia. Poproś o nie w szczegółach części.", no rating plate/bar, "Nowe z AI" badge, link to `/equipment/{id}` with aria-label | `PartCard.tsx:35-96`, `TileStage.tsx` | Implemented |
| R8 | Sort only "Nazwa: A-Z / Z-A" (brand then model, `Intl.Collator('pl')`, numeric), select only with 2+ results | `sortParts.ts`, `PartsSearchPage.tsx:141-143`, `SortSelect.tsx` | Implemented |
| R9 | AI only on click; card "Nie ma tu tego, czego szukasz?" only under 0 parts, never under results; spinner "Szukam w sieci…", skeleton tiles, error alert + button clickable | `AiSearchCard.tsx`, `PartsSearchPage.tsx:144-173`, `usePartsSearch.ts:163-182` | Implemented |
| R10 | Back from a part to `/parts?…` shows the same results (also AI-added) without a new search | `usePartsSearch.ts:152-158` (`searchKeyRef`) | Implemented |
| R11 | Equipment view of a catalogue part: auto details search on entry, photo button, back label "Wróć do wyników" to the same `/parts?…` | `App.tsx:295-307`, backend `equipment_lookup.py` | Implemented |
| R12 | `document.title` "Wyszukiwanie części — Biker" | `App.tsx` title switch | Implemented |
| R13 | Shared code still works: bike tiles via `TileStage`, bike `SortSelect` 4 options, `LoadingCard plate` | `ResultCard.tsx`, `SortSelect.tsx`, `LoadingCard.tsx` | Implemented |
| R14 | Backend `/v1/parts/*` contract (read, parse, AI, validation) | `parts_routes.py`, `parts_repository.py` | Exercised through the UI only; no direct API matrix (covered by the backend pytest and the security review in the task file) |
| X1 | Extra: the AI card stays visible (button "Szukam w sieci…") under the skeleton tiles while the AI runs | `PartsSearchPage.tsx:164-172` | Extra (matches the mockup `ai-loading`) |
| X2 | Extra: heading "Szukamy części w katalogu…" with a spinner while the DB search runs | `PartsSearchPage.tsx:121-127` | Extra |

No requirement judged Missing or Partial.

## Test cases and results (round 1)

Priority H/M/L. Technique: ST = state transition, EP = equivalence partition, BVA, EG = error guessing, UC = use case. Stack F = fake-AI 5183, R = real 5182.

| ID | Pri | Tech | Stack | Steps (condensed) | Expected | Result | Evidence |
|---|---|---|---|---|---|---|---|
| TC-01 | H | ST | F | open `/parts` | title; hero "Znajdź właściwą część."; no results block, filters closed (`aria-expanded=false`) | Pass | `shots\01_start.png` |
| TC-02 | H | ST | F | type "kaseta 12 rzędów shimano 10-51", Szukaj; Szukaj again | 1st: filters open, type=cassette, brand filled, address stays `/parts`, no `/search` request; 2nd: no re-parse, address `/parts?q=…&type=cassette&brand=shimano` | Pass | `02_parsed.png` |
| TC-03 | H | EP | F | DB results of TC-02 | "Znaleźliśmy 4 części", "W katalogu, dla „…”."; each tile "Shimano · Kaseta", chips, description or "Nie mamy jeszcze opisu tej części.", photo (82, 84) or drawing + "Brak zdjęcia. Poproś o nie w szczegółach części." (83, 85); order Deore, Deore XT, SLX, XTR; no plate/bar, no badge, no AI card | Pass | `03_db.png` |
| TC-04 | M | EP | F | sort select | options "Nazwa: A–Z", "Nazwa: Z–A"; Z–A reverses | Pass | |
| TC-05 | H | EG | F | after DB results | no AI call in `fake_calls.log` without a click | Pass (weak alone, see TC-06/16) | log |
| TC-06 | H | ST | F | text "…sram xd 10-52", parse, 2nd submit | 0 parts: "Nie znaleźliśmy żadnej części", "W katalogu nie ma nic dla „…”.", card title/text/button, no sort select, **no AI call in 3 s** | Pass | `06_empty_card.png` |
| TC-07 | H | ST | F | click "Szukaj więcej z AI" | button disabled "Szukam w sieci…", heading "Szukamy w sieci", line "Znalezione części dopiszemy…", >= 4 skeleton tiles; then 4 tiles, all "Nowe z AI", "W sieci, dla „…”. Dodaliśmy je do katalogu.", card gone, select shown, exactly 1 AI call | Pass | `07_ai_loading.png`, `07_ai_results.png` |
| TC-08 | H | UC | F | click AI tile -> `/equipment/{id}` -> "Wróć do wyników" | tab "Wyszukiwanie części" active; back label "Wróć do wyników"; return to same `/parts?…`, 4 tiles with badges, **no** new `/v1/parts/search`, no new AI call | Pass | `08_equipment_fake.png` |
| TC-09 | M | ST | F | tile, browser Back, Forward, Back | same results, no new `/v1/parts/search` | Pass | |
| TC-10 | H | ST | F | "tarcza hamulcowa xyz 9000" -> rotor + model XYZ 9000 -> search -> AI | "Ani w katalogu, ani w sieci, dla „…”.", card shown again, button enabled | Pass | `10_ai_none.png` |
| TC-11 | H | EP | F | "coś do roweru na zimę" | alert "Nie znaleziono: Nie mamy tej części w naszej bazie" above the field, address `/parts`, no search request | Pass | `11_nomatch.png` |
| TC-12 | H | EP | F | parse text A, hand-set model, change text to B, Szukaj; then Szukaj again | text changed -> filters cleared (hand model gone) and re-parsed; unchanged text -> search at once, no parse | Pass | |
| TC-13 | M | EP | F | filters only (type, brand, group), Enter in the group field | no parse; address `/parts?type=cassette&brand=Shimano&group=Deore`; "2 części"; line "W katalogu, dla „Kaseta · Shimano · Deore”." | Pass | |
| TC-14 | H | ST | F | two searches, browser Back, "Nowe wyszukiwanie" | each search a history entry, Back refills the form and re-searches the other query once, reset -> `/parts`, empty form | Pass | |
| TC-15 | H | EP/BVA | F | open `/parts?type=cassette&brand=Shimano`; `?brand=…&x=1&type=cassette`; `?type=helmet&x=1&brand=Shimano`; `?x=1&type=helmet`; `/parts/`; F5 | form filled, panel open, searches at once without `/parse`; canonical `…?type=cassette&brand=Shimano`, `?brand=Shimano`, `/parts`; F5 keeps results | Pass | |
| TC-16 | M | EG | F | `/parts?q=kaseta+shimano` | text-only address: search sends only text -> 0 parts card, "W katalogu nie ma nic dla „kaseta shimano”.", no AI call | Pass | |
| TC-17 | M | BVA | F | 1 result vs 4 results | 1: "Znaleźliśmy 1 część", no select; 4: select | Pass | |
| TC-18 | H | EG | F | AI for brand `fail` (upstream 502) | alert "Błąd: Upstream error: …", heading stays, button enabled again | Pass | `18_ai_error_fake.png` |
| TC-19 | M | EG | F | hold the first `/v1/parts/search` response, run a second query, release the first | stale answer dropped: list and address belong to the second query | Pass (DB search only) | |
| TC-20 | M | EP | F | a11y: Enter submits, alert `role=alert`, toggle `aria-expanded`/`aria-controls`, labels, tiles are `<a href=/equipment/id>` with aria-label, keyboard Enter on a focused tile, results `aria-live`, submit disabled when empty | all as expected | Pass | |
| TC-21 | H | UC | F | tab order and `aria-current`; tab link after a search; Kontakt, "Rower na Twoją miarę", BIKER wordmark | four tabs in order; tab href `/parts?type=cassette&brand=Shimano`, click shows results without a new search; contact/fit work; wordmark resets the parts search too | Pass | |
| TC-22 | H | BVA | F | widths 360, 375, 414, 639, 640, 768, 1280 | no horizontal overflow; short labels "Na miarę" / "Części" up to 639 px, long labels from 640 px | Pass | `22_tabs_360.png`, `22_tabs_1280.png` |
| TC-23 | H | Regression | F | `/search?brand=Canyon` | bike tiles keep the rating plate ("?"/bar), 4 sort options (rating asc/desc, name A–Z/Z–A), links `/bike/{id}` | Pass | `23_bike_results.png` |
| TC-24 | M | Regression | F | home popular tiles, open bike | popular tiles with photos, bike view, only the bike tab active | Pass | `24_bike_details.png` |
| TC-25 | M | Regression | F | bike 39 -> component link -> equipment | back label "Wróć do roweru", parts tab not active, back returns to `/bike/39` | Pass | |
| TC-26 | H | EP | R | real stack, text-only submit | parse 400 (no credits) shown as the "Nie znaleziono" warning, no search, address `/parts` | Pass | |
| TC-27 | H | EP | R | filters panel type+brand, Szukaj | DB search, address `/parts?type=cassette&brand=Shimano`, 4 tiles, no second parse | Pass | `27_real_db.png` |
| TC-28 | H | EG | R | `/parts?type=wheel&brand=Zzqq`, click AI once | alert "Błąd: Your credit balance is too low…", button clickable again, heading unchanged | Pass | `28_real_ai_error.png` |
| TC-29 | H | UC | R | `/parts?type=cassette&brand=Shimano&model=SLX` -> tile -> `/equipment/83` | details search starts by itself ("Szukam danych wyposażenia…", 1 `/details/search` POST), description appears after ~65 s | Pass | `29_real_equipment_searching.png`, `29_real_equipment_done.png` |
| TC-30 | H | UC | R | gallery "Poproś o dane" once | photo search (1 POST, ~53 s), photos shown | Pass | `30_real_photos_done.png` |
| TC-31 | H | UC | R | "Wróć do wyników" | tab active, back to the same `/parts?…`, 1 tile, no new `/v1/parts/search` | Pass | |
| TC-32 | M | EP | F | SRAM set sorted A–Z / Z–A, console errors | "GX Eagle Transmission XS-1275", "GX Eagle XG-1275", "X01…", "XX1…" and the reverse; no page or console errors | Pass | |

Not executed: `/v1/parts/*` API matrix (limits, SQL-looking values, NUL byte, case of `part_type`) — covered by the security review in the task file and backend pytest; stale-answer handling for the AI search; screen-reader testing; a visual pixel comparison with the mockup (wording and structure compared, screenshots inspected).

## Observations (not defects)

1. After a details or photo search in the part view, "Wróć do wyników" shows the **remembered** list: the tile of id 83 still reads "Brak zdjęcia…" / "Nie mamy jeszcze opisu tej części." although description and photos are now stored. This follows the task ("same results without a new request") but the tile is stale until the next search; consider refreshing the tile when the user returns.
2. The fake parse returns the brand as typed ("shimano", lower-case), so the address and the status line show the lower-case brand; with the real Haiku the casing is the model's. Not an app issue.
3. The home page's `GET /v1/bike/popular` and the review calls also fire when `/parts` is opened first (App-level hook, pre-existing behaviour).

## Summary round 1

32 passed, 0 failed, 0 blocked.

## Round 2 (2026-10-07, after the code review fixes)

Changes since round 1 (commit 1145a7e + the `usePartsSearch` run guard): the AI answer block is the last one whose JSON looks like parts (a trailing citation `[1]` no longer wins); only a `parts` item no bike links is searched without a bike (other categories stay 404); "Brand Model" is cut to 255; found parts are written in name order; an existing row of another type than the requested one is not answered; in the frontend every search run bumps a counter, so an AI answer still in flight is dropped when the same query is searched again (before, only a different query dropped it).

Both backends restarted on the new code; fixtures re-seeded (ids 98–101, same content as 82–85 — round 1's real details/photo search had filled id 83, so its tile no longer matched TC-03); SRAM rows reset before TC-01–TC-11 and before TC-33. Scripts `s1`–`s4`, `s6`, `s7` re-run (`s5` = TC-29–TC-31, the two paid real-searcher runs, not repeated: the bike-less path for a `parts` item is unchanged and covered by `test_equipment_repository.py`).

| ID | Result | Notes |
|---|---|---|
| TC-01 – TC-28, TC-32 | Pass | all re-run on the new code |
| TC-29 – TC-31 | Pass (round 1) | not repeated (paid searcher runs) |
| TC-33 | Pass | **new:** AI search started, the same query submitted again while it runs → after the old AI answer arrived: 0 tiles, "Nie znaleźliśmy żadnej części", button enabled, exactly 1 AI call; the next DB search finds the parts the AI stored |

## Summary round 2

33 passed (30 re-run + 3 from round 1), 0 failed, 0 blocked. Observation 1 (a tile is not refreshed after its part's details/photos were searched — the spec asks for the same results without a new request) is left for the user to decide.
