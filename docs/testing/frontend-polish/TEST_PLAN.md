# Test plan — frontend translated to Polish

**Test basis:** user request "Przepisz cały frontend na polski" (no backlog file). Change set: uncommitted diff in `frontend/src/**`, `frontend/index.html`.
**Scope:** every user-visible string (text, placeholders, `aria-label`s, errors, page title/`lang`). **Out of scope:** backend-generated content (explanations, spec trees, reviews, category names) — shown as returned.
**Approach:** system-level UI tests in Chromium (Playwright). Search uses a DB-cached brand (`Trek`) and a cached parse (`bike for 10km`); detail/equipment endpoints are mocked with `page.route` to avoid Anthropic API cost.
**Exit criteria:** all cases Pass; no English UI strings found by the leftover scan; no console errors.

## Traceability

| Req | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | Search page UI in Polish | `App.tsx`, `SearchInput.tsx`, `index.html` | Implemented |
| R2 | Result cards in Polish | `ResultCard.tsx`, `App.tsx` results section | Implemented |
| R3 | Bike details view in Polish | `BikeDetailsView.tsx`, `BikeDetailsShared.tsx` | Implemented |
| R4 | Request-data button in Polish | `RequestDataButton.tsx` | Implemented |
| R5 | Equipment view in Polish | `EquipmentDetailsView.tsx` | Implemented |
| R6 | Errors / warnings in Polish | `App.tsx` (parse 400, search error) | Implemented |
| R7 (risk) | Filter values sent to backend unchanged (English) | `SearchInput.tsx` `Option { value, label }` | Implemented |

## Test cases

| ID | Req | Pri | Preconditions / data | Steps | Expected result |
|---|---|---|---|---|---|
| TC01 | R1 | High | Home page | Open `/` | `<html lang="pl">`, title "Biker — Znajdź swój idealny rower", hero "Znajdź swój / idealny rower.", Polish placeholder, button "Znajdź mój rower", footer "Napędzane przez Claude" |
| TC02 | R1 | High | Home | Click "Filtry", then "Opcje zaawansowane", tick e-bike | Labels Marka/Model/Typ roweru/Rok/Rozmiar kół/Rozmiar ramy/Płeć/Materiał ramy/Typ hamulców/Napęd/Pojemność baterii (Wh); toggles read "Ukryj filtry" / "Mniej opcji zaawansowanych"; checkboxes Polish |
| TC03 | R1 | Med | Filters open | Read `<option>` texts of every select | Labels Polish (e.g. Szosowy, Damski, Karbon, Tarczowe hydrauliczne), empty option "Dowolny"/"Dowolna" |
| TC04 | R7 | **High** | Filters open; `/v1/bike/search` intercepted (mocked response) | Select Płeć=Damski, Materiał=Karbon, Hamulce=Tarczowe hydrauliczne, Typ=Szosowy; submit | Request body has `gender:"Female"`, `frame_material:"Carbon"`, `brake_type:"Hydraulic Disc"`, `bike_type:"Road"` |
| TC05 | R6 | High | Cached parse `bike for 10km` → 400 | Type text, submit | Alert "Nie znaleziono: Nie mamy tego roweru w naszej bazie"; no search request |
| TC06 | R2 | High | Brand `Trek` (DB hit, no AI) | Filters → Marka=Trek, submit | "Wyniki dla", "Nowe wyszukiwanie", "Najlepsze dopasowanie", score label ends "dopasowanie", "Zobacz specyfikację →" |
| TC07 | R6 | Med | Search mocked 500 | Submit | "Błąd: …" alert with Polish text |
| TC08 | R2 | Med | Search mocked `bikes: []` | Submit | "Nie znaleziono: Żaden rower nie pasuje…" |
| TC09 | R3 | High | Details endpoints mocked with data | Open first result | "Wróć do wyników", "Dopasowanie", "Opis", "Źródła", "Oferty", "Używane", "Nowe", badges "Nowy"/"Używany", "Recenzja ekspertów", "Czytaj recenzję" |
| TC10 | R4 | High | Details endpoints mocked empty; `/v1/bike/missing` mocked | Open result, wait >5 s, click a button | "Nie mamy jeszcze tych danych" + "Poproś o dane"; after click "Zgłoszono ✓"; section titles Zdjęcia/Opis/Recenzja ekspertów/Specyfikacja |
| TC11 | R3/R6 | Med | `/v1/bike/details` mocked 500 | Open result | "Nie udało się wczytać specyfikacji." + "Spróbuj ponownie" |
| TC12 | R5 | High | TC09 state; equipment endpoints mocked | Click a component name | "Wróć", category "Kask", Polish review heading; empty-spec text "Nie znaleziono szczegółowej specyfikacji tego produktu." when components empty |
| TC13 | all | Med | After TC01–TC12 | Scan visible text + aria-labels on each view for a list of old English strings | None found |

**Regression set:** TC04, TC05, TC06, TC10 (search pipeline, parse flow, request-data flow).

## Results — round 2 (2026-09-24)

13 passed · 0 failed · 0 blocked (TC13 accepted with a known limitation, user decision)

| ID | Result | Notes |
|---|---|---|
| TC01–TC12 | Pass | Round 1 failures in TC01 were test-script defects (CSS `uppercase` in `inner_text`), fixed in the script only |
| TC13 | Pass (known limitation) | Results header "Wyniki dla" shows `"Brand: Trek"` — the enriched query string built by the backend (`SearchRequest.enriched_query()` in `backend/app/schemas.py`), not a frontend string. AI explanations/accessory chips are also English (backend content, out of scope). User decided (2026-09-24) to leave backend-generated text as-is — out of scope |

No console errors. Evidence: Playwright screenshots in the session scratchpad (`shots/tc*.png`).

## Round 3 — spec-tree labels (2026-09-24)

Request: translate the component tree's labels (Material, Weight, Axle Dimension, category and subcategory names). Implemented in `frontend/src/specLabels.ts`, applied in `BikeDetailsShared.tsx` `CategorySection`. Coverage on `cache.db` data: categories 100 %, subcategories 100 %, spec keys 95 % of rows (most of the remainder read the same in Polish: Standard, Tubeless, Offset, Reach, TPI).

**Constraint:** no Anthropic tokens available, so only cached requests could reach the backend. Bike: Goetze Onyx Pro (`parse`, `search`, `details`, `offer`, `ceneo`, `decathlon` cached); `review`, `used` and equipment endpoints were mocked, and any other request was aborted. The backend log for the run shows 6 cache hits and no misses.

| ID | Case | Result |
|---|---|---|
| TS01 | Category headers are Polish (Rama, Napęd, Hamulce, Koła, Kokpit, Siodło i sztyca, Oświetlenie), with no English | Pass |
| TS02 | Subcategories are Polish (Widelec, Przerzutka tylna, Kaseta, Korba, Suport, Łańcuch…) | Pass |
| TS03 | Spec keys are Polish (Materiał, Waga, Wymiar osi, Prześwit na oponę, Średnica rury sterowej, Zębatki, Zakres…) | Pass |
| TS04 | Spec values (`Steel`) and component names (`Shimano Tourney …`) are unchanged | Pass |
| TS05 | The component-name link still sends the untranslated name to `/v1/equipment/details` | Pass |
| TS06 | Regression: the rest of the details page is still Polish | Pass |
| TS07 | No uncached request was sent | Pass |

7 passed · 0 failed · 0 blocked.
