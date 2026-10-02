# Test plan — centrumrowerowe.pl offers in the "Nowe" card

Branch `feature/centrumrowerowe-offers`. Intent confirmed with the user on 2026-10-02 (interview, no backlog file).

## Requirements

| ID | Requirement | Implemented in |
|----|-------------|----------------|
| R1 | `POST /v1/bike/centrumrowerowe` returns only the bike's stored `centrumrowerowe.pl` rows: a DB read, no AI, no cache, no search route | `backend/app/main.py`, `backend/app/offers_repository.py` `get_centrumrowerowe_offers` |
| R2 | Opening the details view reads it, and its offers land in the "Nowe" card sorted by price | `frontend/src/App.tsx`, `frontend/src/components/OffersSection.tsx` |
| R3 | The single New-card button is replaced by "Poszukaj na Allegro" and "Poszukaj w Decathlonie". Each button shows while its source has no stored row, also under existing rows | `OffersSection.tsx` `MergedOffersSection` / `SourceSearchButton` |
| R4 | A click runs only that source's search and records `offers_new`. Rows that come back hide the button. An empty result shows a disabled "Nie znaleziono …" plus `info`. An error makes the button clickable again | `OffersSection.tsx`, `App.tsx` `searchAllegro` / `searchDecathlon` |
| R5 | centrumrowerowe.pl has no search button | `OffersSection.tsx` |
| R6 | The Used card (OLX button) is unchanged | `OffersSection.tsx` |

## Environment

- Worktree stack: a fake searcher on `127.0.0.1:8102` (2 s delay; a model containing "Fail" → 502, "Empty" → empty, otherwise one offer). The backend runs on `8002` with `SEARCHER_URL` pointing at the fake, and the frontend on `5186`.
- Database: the local `biker-pg`. No paid searcher run and no Cloud SQL write.
- Fixture bikes:
  - `QA Centrum` with the models Only Centrum, Centrum And Allegro, Used Allegro, Fail Bike and Empty Bike
  - `Rockrider` / `QA Centrum Decathlon`

## Cases

| ID | Req | Steps | Expected |
|----|-----|-------|----------|
| TC-01 | R1 | smoke `case_centrumrowerowe` | Only the centrumrowerowe row is returned (the decathlon row of the same bike is filtered out). Lookup ignores case and whitespace, and the response uses the stored casing. No cache row is written, the call takes < 5 s, an unknown bike gets an empty 200, an empty company gets 422 |
| TC-02 | R2, R3, R5 | Open Only Centrum | `/v1/bike/centrumrowerowe` is called. Two rows show in price order 999,99 zł → 1 099 zł. Both search buttons are visible, and neither "Poproś o dane" nor "Nie mamy…" appears |
| TC-03 | R3 | Open Centrum And Allegro | allegro 1 299 is listed before centrum 1 399. Only the Decathlon button shows |
| TC-04 | R3 | Open Used Allegro | The used allegro row is in the Used card and centrum is in Nowe. The Allegro button is hidden (an Allegro row exists) and the Decathlon button is visible |
| TC-05 | R4 | Rockrider bike → "Poszukaj w Decathlonie" | "Szukam w Decathlonie…" shows while the Allegro button stays enabled. The decathlon row (1 200) is listed before centrum (1 499) and the Decathlon button disappears. The fake gets 1 decathlon call and `offers_new` goes up by 1 |
| TC-06 | R4 | Empty Bike → both buttons | Allegro shows a disabled "Nie znaleziono na Allegro". Decathlon (foreign brand) shows "Nie znaleziono w Decathlonie" plus the "Decathlon nie sprzedaje marki QA Centrum…" info. The fake gets only the allegro call |
| TC-07 | R4 | Fail Bike → Allegro | The button shows "Szukam…" and becomes clickable again after the 502. The Decathlon button is unaffected |
| TC-08 | R3, R4 | Only Centrum → both buttons at once | The searches settle independently. The allegro row 1 050 sits between 999,99 and 1 099, and the Allegro button disappears |
| TC-09 | R6 | Only Centrum | The Used card still shows "Poproś o dane" |
| TC-10 | — | 390 px viewport | The layout holds, with no horizontal scroll |

## Results

| ID | Round 1 | Round 2 | Notes |
|----|---------|---------|-------|
| TC-01 | Pass | Pass | |
| TC-02 | **Fail** | Pass | `priceValue` read "999,99 zł" as 99999, so it sorted after 1 099. Fixed: grosze are now parsed as decimals |
| TC-03 | Pass | Pass | |
| TC-04 | Pass | Pass | |
| TC-05 | Fail (test) | Pass | The test's expected order contradicted its own comment. The app's order was correct |
| TC-06 | Pass | Pass | |
| TC-07 | Pass | Pass | |
| TC-08 | **Fail** | Pass | Same price-parsing bug as TC-02 |
| TC-09 | Pass | Pass | |
| TC-10 | Pass | Pass | Checked on a screenshot |

There were no console errors. The backend smoke run `test_search.py` gave 19 passed, 0 failed and 4 skipped (`--ai`).
