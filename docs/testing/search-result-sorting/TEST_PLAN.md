# Test plan: search result sorting (branch `feature/search-result-sorting`)

## 1. Test basis

**Request (user):** "Stronie bikera brakuje w search sortowania. Dodajmy sortowanie po punktach dostanych z review i nazwie." In English: the search page has no sorting; add sorting by review points and by name.

**Interview (step 1 of the run):** it stopped at a hypothesis that nobody answered:
- a visible "Sortuj" control above the search results (expert rating / name);
- search results only, not the home page's "Najpopularniejsze rowery".

**Change set:** this branch vs `main` `080347a`.
- `frontend/src/sortBikes.ts` (new)
- `frontend/src/components/SortSelect.tsx` (new)
- `frontend/src/App.tsx`
- docs: `CLAUDE.md`, `README.md`, `frontend/README.md`

No backend change.

## 2. Requirement traceability

| # | Requirement | Implemented in | Status | Notes |
|---|---|---|---|---|
| R1 | Sort the results by the expert rating from the stored review | `frontend/src/sortBikes.ts:23-43` (`rating_desc` / `rating_asc`), ratings from `hooks/useCachedRatings.ts` | Implemented | |
| R2 | Sort the results by name | `frontend/src/sortBikes.ts:16-21,29-30` (`name_asc` / `name_desc`, brand then model, `Intl.Collator('pl', numeric)`) | Implemented | |
| R3 | A visible control on the search results | `frontend/src/components/SortSelect.tsx`, `frontend/src/App.tsx:599-602` | Implemented | from the interview hypothesis |
| X1 | (not requested) both directions for each key: 4 options | `sortBikes.ts:9-14` | Extra | confirm with the user |
| X2 | (not requested) the choice is kept across searches, "Nowe wyszukiwanie" and the wordmark, and reset by a reload | `App.tsx:72` (`sortOrder` is not in `handleReset`) | Extra | confirm with the user |
| X3 | (not requested) control hidden for a list of 0 or 1 bikes | `App.tsx:600` | Extra | |
| X4 | (design decision) unrated bikes last in **both** rating directions | `sortBikes.ts:37-39` | Extra | confirm with the user |

## 3. Scope, approach, environment

- **In scope:**
  - the "Sortuj" select;
  - the order and the "#n" rank of the result cards;
  - persistence of the choice;
  - behaviour while ratings are pending or have failed;
  - layout on desktop and mobile;
  - accessibility of the control.
- **Out of scope:**
  - backend search logic (unchanged);
  - AI search and free-text parse (cost guard: the Anthropic credits are exhausted, so AI paths are not exercised);
  - the home page popular list's own order (only checked for "no control").
- **Environment:**
  - backend from the worktree on `127.0.0.1:8003` (`DATABASE_URL` = local `biker-pg`);
  - Vite on `localhost:5178` with `BIKER_API_URL=http://localhost:8003`;
  - Chromium via Python Playwright (headless): 1100×1400 desktop, 390×844 mobile.
- **Test data:** searched through the Filtry panel, brand (and model) only, so every search is a DB hit with no AI call.

| Data set | Request | Bikes | Rated (stored review) |
|---|---|---|---|
| D-TREK | brand `Trek` | 34 | Madone SL 6 = 8.2, Madone SL 5 Gen 8 = 8.0, FX 3 = 6.5 |
| D-ARI | brand `Ari Bikes` | 17 | Delano Peak = 8.2, La Sal Peak = 7.9, Nebo Peak = 7.9 (tie) |
| D-ROMET | brand `Romet` | 8 | Wagant 3 = 7.1, Aspre = 7.0 |
| D-KROSS | brand `Kross` | 6 | KROSS Esker Eco = 7.7 (upper-case brand) |
| D-LAP | brand `Lapierre` | 2 | none |
| D-ONE | brand `Trek` + model `Marlin 5` | 1 | none |
| D-MULTI | wheel `29"` + frame `XL` + electric | 5 | brands Ari Bikes, Aventon, Raymon |

- **Techniques:**
  - equivalence partitioning: result-list states (error, 1, 2, many) and rating states (rated, unrated, pending, failed);
  - boundary values: list size 1 / 2;
  - state transitions of the select;
  - error guessing: ties, case, numbers in model names, persistence across views.
- **Entry criteria:** build passes (`npm run build` exit 0); both servers answer 200.
- **Exit criteria:**
  - every High case passes;
  - no console errors;
  - every failure is fixed and re-tested together with the regression set.

## 4. Test conditions

| ID | Condition | Technique | Req |
|---|---|---|---|
| TCOND-01 | Control visible for a list of ≥ 2 bikes, absent for 1 bike and when there is no list | EP + BVA (1 / 2) | R3, X3 |
| TCOND-02 | Default option is "Ocena eksperta: od najwyższej" | — | R1 |
| TCOND-03 | Rating, highest first: rated bikes descending, then unrated bikes in backend order | EP | R1 |
| TCOND-04 | Rating, lowest first: rated bikes ascending, unrated bikes still last | EP | R1, X4 |
| TCOND-05 | Equal ratings keep backend order | error guessing | R1 |
| TCOND-06 | Name A–Z: brand, then model; case-insensitive; numbers by value | EP | R2 |
| TCOND-07 | Name Z–A is the reverse of A–Z | EP | R2 |
| TCOND-08 | Every option change re-orders immediately; returning to the default restores the first order | state transition | R1-R3 |
| TCOND-09 | Pending ratings: rating orders keep backend order; name orders sort at once | EP | R1, R2 |
| TCOND-10 | Failed rating calls: all "?", no error UI, backend order | EP | R1 |
| TCOND-11 | "#n" rank follows the displayed order | — | R3 |
| TCOND-12 | Choice kept across details/back, new search, "Nowe wyszukiwanie", wordmark; reset by reload | state transition | X2 |
| TCOND-13 | Label associated, keyboard operable | checklist | R3 |
| TCOND-14 | Layout fits on 390 px without horizontal overflow | checklist | R3 |

## 5. Test cases

Common preconditions: backend on :8003 and Vite on :5178 are running, the local `biker-pg` holds the data sets above, and http://localhost:5178/ is open.

"Search X" means: click **Filtry**, fill **Marka** (and **Model**) with X, click **Znajdź mój rower**, then wait until no card shows "Ocena eksperta…" (pending).

| ID | Title | Req | Prio | Data | Steps | Expected result |
|---|---|---|---|---|---|---|
| TC-01 | Control shown with 4 options and the right default | R3, R1, X1 | High | D-TREK | Search Trek | Select labelled "Sortuj" above the cards. Options in this order: "Ocena eksperta: od najwyższej", "Ocena eksperta: od najniższej", "Nazwa: A–Z", "Nazwa: Z–A". Value `rating_desc` |
| TC-02 | No control for exactly 1 bike (BVA) | X3 | Medium | D-ONE | Search Trek + Marlin 5 | 1 card, no "Sortuj" select |
| TC-03 | Control shown for exactly 2 bikes (BVA) | R3, X3 | Medium | D-LAP | Search Lapierre | 2 cards and the select |
| TC-04 | No control when the search fails | X3 | Medium | `/v1/bike/search` mocked to 500 | Search Trek | "Błąd:" alert, no results section, no select |
| TC-05 | Rating, highest first | R1 | High | D-TREK | Search Trek | Cards 1-3: Madone SL 6 8.2, Madone SL 5 Gen 8 8.0, FX 3 6.5; then 31 "?" cards in backend order (brand + model A–Z) |
| TC-06 | Rating, lowest first, unrated still last | R1, X4 | High | D-TREK | Search Trek, select "Ocena eksperta: od najniższej" | Cards 1-3: FX 3 6.5, Madone SL 5 Gen 8 8.0, Madone SL 6 8.2; then the same 31 "?" cards in the same order as TC-05 |
| TC-07 | Ties keep backend order | R1 | Medium | D-ARI | Search Ari Bikes; check the highest-first order, then the lowest-first order | Highest first: Delano Peak 8.2, La Sal Peak 7.9, Nebo Peak 7.9. Lowest first: La Sal Peak, Nebo Peak, Delano Peak |
| TC-08 | Name A–Z: case-insensitive, numbers by value | R2 | High | D-TREK, D-KROSS | Search Trek, select "Nazwa: A–Z"; then search Kross | Trek: Allant+ 7 first, X-Caliber 8 last; Marlin 4, 5, 6, 7, 8 come before Marlin 20; rated and unrated bikes mixed. Kross: "KROSS Esker Eco" first, then Explorer 5.0, Explorer 7.0, Level 3.0, Sentio 1.0, Sentio 2.0 |
| TC-09 | Name Z–A is the exact reverse | R2 | High | D-TREK | Select "Nazwa: Z–A" | Order is the exact reverse of TC-08's Trek list |
| TC-10 | Name sort across brands | R2 | Medium | D-MULTI | Open Filtry: wheel 29", frame XL, electric checked; search; select A–Z, then Z–A | A–Z: Ari Bikes ×2 (Timp Peak, Wire Peak 2.0), Aventon ×2 (Current ADV, Current EXP), Raymon. Z–A: Raymon first, Ari Bikes Timp Peak last |
| TC-11 | Rank follows displayed order | R3 | Medium | D-TREK | After each option of TC-05/06/08/09, read the "#n" of every card | "#1"…"#34" top to bottom in every order |
| TC-12 | State transitions round trip | R1-R3 | High | D-ROMET | Search Romet; go highest first → A–Z → Z–A → lowest first → highest first | Each step re-orders at once. The final order equals the initial one: Wagant 3 7.1, Aspre 7.0, then 6 "?" |
| TC-13 | Pending ratings | R1, R2 | Medium | D-ROMET; `/v1/bike/review` delayed 4 s | Search Romet; within the delay read the order, then pick A–Z; then pick highest first and wait | While pending: cards show "—", rating order = backend order. A–Z applies immediately while pending. After settling, highest first: Wagant 3, Aspre first |
| TC-14 | Rating calls failing | R1 | Low | D-ROMET; `/v1/bike/review` aborted | Search Romet | All cards "?" / "Brak oceny", no error alert, backend order, select present |
| TC-15 | Choice persists, reload resets | X2 | Medium | D-TREK, D-ROMET | Search Trek, pick A–Z; open card #1, check the details heading, click back; click "Nowe wyszukiwanie"; search Romet; click the BIKER wordmark; search Romet; reload the page and search Romet | Back from details: still A–Z, same order. Home after "Nowe wyszukiwanie": popular list, no select. Romet search: A–Z. After the wordmark reset: A–Z. After reload: highest first |
| TC-16 | Accessibility | R3 | Low | D-ROMET | Find the select by its label "Sortuj"; focus it with the keyboard and change the option with the keyboard | Select found by its label; keyboard change re-orders the list; focus ring visible |
| TC-17 | Mobile layout | R3 | Low | D-ROMET, 390×844 | Search Romet; screenshot the results header | Select fully visible, no horizontal scroll (`scrollWidth <= innerWidth`) |

### Regression set (adjacent features)

| ID | Title | Prio | Steps | Expected |
|---|---|---|---|---|
| RG-01 | Card rating display unchanged | High | Search Trek; inspect the Madone SL 6 and Allant+ 7 cards | Madone SL 6: "8.2", "/ 10", label "Ocena eksperta", bar `aria-valuenow` 8.2. Allant+ 7: "?", "Brak oceny" |
| RG-02 | Home page popular list | Medium | Open / | "Najpopularniejsze rowery" section rendered, no "Sortuj" select on the home page |
| RG-03 | Details open the clicked bike from a sorted list | High | Search Trek, pick lowest first, click card #1 | Details view for Trek FX 3 |
| RG-04 | No console errors | Medium | Whole run | No `console.error` and no page errors (StrictMode duplicate fetches are expected) |

## 6. Results: round 1 (2026-10-03)

**21 passed · 0 failed · 0 blocked**

- **Environment:**
  - the code of this branch (tested at a local autosave commit with identical files, squashed before the PR);
  - backend `127.0.0.1:8003` against local `biker-pg`;
  - Vite `localhost:5178`;
  - Chromium headless (Python Playwright).
- **Script and evidence:** the session scratchpad holds `run_qa.py` plus the evidence screenshots and `results.json`.
- **Rating oracle:** the expected rating order is computed independently, from one `POST /v1/bike/review` per bike against the backend.

| Case | Result | Observed |
|---|---|---|
| TC-01 | Pass | label "Sortuj", value `rating_desc`, 4 options in the planned order, select above the first card |
| TC-02 | Pass | Trek + Marlin 5: 1 card, no select |
| TC-03 | Pass | Lapierre: 2 cards, select shown |
| TC-04 | Pass | `/v1/bike/search` mocked to 500: "Błąd:" alert, no results section, no select |
| TC-05 | Pass | Madone SL 6 8.2, Madone SL 5 Gen 8 8.0, FX 3 6.5, then 31 "?" cards in backend order (matches the oracle exactly) |
| TC-06 | Pass | FX 3 6.5, Madone SL 5 Gen 8 8.0, Madone SL 6 8.2, then the same 31 "?" cards |
| TC-07 | Pass | highest first: Delano Peak 8.2, La Sal Peak 7.9, Nebo Peak 7.9; lowest first: La Sal Peak, Nebo Peak, Delano Peak (tie keeps backend order) |
| TC-08 | Pass | Trek: Allant+ 7 … X-Caliber 8, Marlin 4, 5, 6, 7, 8 before Marlin 20, whole list in natural case-insensitive order; Kross: "KROSS Esker Eco" first |
| TC-09 | Pass | Z–A is the exact reverse of A–Z |
| TC-10 | Pass | A–Z: Ari Bikes ×2, Aventon ×2, Raymon; Z–A is the reverse |
| TC-11 | Pass | "#1"…"#34" top to bottom in all four orders |
| TC-12 | Pass | Romet round trip highest first → A–Z → Z–A → lowest first → highest first; final order equals the initial one (Wagant 3 7.1, Aspre 7.0, …) |
| TC-13 | Pass | `/v1/bike/review` held: "—" on every card, backend order; A–Z applies at once while pending; highest first stays in backend order until released; after release Wagant 3, Aspre first |
| TC-14 | Pass | `/v1/bike/review` aborted: every card "?", backend order, no alert, select present |
| TC-15 | Pass | A–Z kept after details (Allant+ 7) and back, same order; home after "Nowe wyszukiwanie" shows the popular list and no select; Romet search still A–Z; after the BIKER wordmark still A–Z; reload resets to highest first |
| TC-16 | Pass | `getByLabel("Sortuj")` finds the select; Tab from "Nowe wyszukiwanie" lands on it; ArrowDown switches to "od najniższej" and re-orders; focus ring = terracotta 2 px at 20 % |
| TC-17 | Pass | 390 px: `scrollWidth` 390 = `innerWidth`; select at x 128-374 |
| RG-01 | Pass | Madone SL 6 shows "8.2", bar `aria-valuenow` 8.2, label "Ocena eksperta"; Allant+ 7 shows "?" and "Brak oceny" |
| RG-02 | Pass | home page: "Najpopularniejsze rowery" rendered, no select |
| RG-03 | Pass | lowest first, card #1 opens the details of Trek FX 3 |
| RG-04 | Pass | no console or page errors on the unmocked pages |

**Observation (not a defect):** right after a re-sort, the cards React moves replay their entrance animation. The card slides up again and its rating bar refills from 0, so a screenshot taken 250 ms after a change shows those bars empty. 2.5 s after each of the four changes, all 34 cards had opacity 1 and every bar was at rating × 10 % (82 / 80 / 65 %). The same replay already happened before this change, when the list re-sorted after the ratings arrived.

**Needs a decision from the user (extras, not requested):** X1 both directions for each key; X2 the choice is kept across searches and reset by a reload; X3 no control for 0 or 1 bike; X4 unrated bikes last in both rating directions.

**Not covered:** the free-text and AI search paths. The cost guard applies: the Anthropic credits are exhausted, and the change does not touch those paths.
