# Production manual test plan: frame named after its bike, `e4330a4` (2026-10-02)

**Change under test:** PR #143 "Search a frame named after its bike as that bike's frameset", merged as `e4330a4` and deployed to production. Searcher revision `biker-searcher-00009-wnn`, backend `biker-backend-00016-4r4`, frontend unchanged.

**Test basis:** `docs/EQUIPMENT_SEARCHER_MIGRATION.md` § 13 and the fix note in `backlog/done/DONE_042_EQUIPMENT_SEARCHER.md`. Before the fix, a details search for a Frame element named exactly like its bike ended with `found: false` and stored nothing. The view then showed "Nie znaleziono danych" in Opis and Specyfikacja. Plan format follows `docs/testing/PROD_2026-10-02_7b7955a/TEST_PLAN.md`.

## Scope, approach, environment

| Item | Value |
|---|---|
| Frontend | Cloud Run `biker-frontend`, https://biker-frontend-919806073640.europe-central2.run.app |
| Backend | Cloud Run `biker-backend`, https://biker-backend-919806073640.europe-central2.run.app (curl, read-only) |
| Searcher | Cloud Run `biker-searcher`, never called directly; observed through the backend and `gcloud logging read` |
| Database | Cloud SQL `biker-pg`, never touched directly; state read through the API only |
| Browser | Python Playwright (global `python`), Chromium headless, 1400x1000; script `tc01.py` and screenshots in the session scratchpad `qa-frame/` |
| Paid budget | one equipment details searcher run (about $0.4, up to 6 min), approved by the lead |

Scope is one happy path. Negative cases, the photos route and the other categories were covered by the earlier plan and are out of scope here.

Technique: use-case scenario with state-transition checks on `RequestDataButton` (idle → searching → replaced by data) and a re-entry check that no second paid run is sent.

### Test data (production, read through the API before testing)

| Item | Stored state before the run |
|---|---|
| Bike Giant / Revolt Advanced Pro | Frame / Frame element "Giant Revolt Advanced Pro" with specs Material, Weight, Axle Dimension, Tyre Clearance; already carries `equipment_id: 2` |
| Equipment id 2 | created earlier by an outside photos run: category `parts`, 8 photos, **no** description, **no** components (`pre_eq2_details.json`) |

So the view was expected to show photos plus the "Poproś o dane" button in Opis and Specyfikacja, and the paid run was needed.

Entry criteria: frontend `/` and backend `/docs` answer 200 (both did). Exit criteria: TC-01 Pass, or a failure reported with evidence.

## Test case

| ID | Pri | Steps | Expected |
|---|---|---|---|
| TC-01 | High | 1. Filters: brand "Giant", model "Revolt Advanced Pro", search. 2. Open the result. 3. In Komponenty click the Frame element "Giant Revolt Advanced Pro". 4. Wait out the 5 s grace and click "Poproś o dane" once. 5. Wait up to 6 min. 6. "Wróć", re-open the element. 7. Reload the app, search again, re-open the element | 3: equipment view, eyebrow "Części rowerowe". 4: Opis and Specyfikacja both show "Szukam danych wyposażenia…". 5: one `POST /v1/equipment/details/search` → 200, non-empty `components` (a Frame element with material, weight, axle, tyre clearance), `equipment_id` non-null; Opis shows a description, Specyfikacja the tree with Polish labels; no 5xx. 6–7: `POST /v1/equipment/details` by `equipment_id` returns the same data at once, no `/search` call. `POST /v1/bike/details` carries `equipment_id` on the Frame element |

## Results (2026-10-02, 09:45–09:50 local time)

**TC-01: Pass.** One note on console errors below.

| Step | Result | Notes | Evidence |
|---|---|---|---|
| 1–2 | Pass | `/v1/bike/search` 200 in 63 ms, one card; details view reads (details, photos, review, OLX, Allegro, Decathlon) all 200 under 0.2 s | `01_search.png`, `02_bike_details.png` |
| 3 | Pass | Equipment view opened with eyebrow "Części rowerowe". It read `/v1/equipment/details` and `/photos` with `equipment_id: 2`. Gallery showed 8 frame photos. Opis and Specyfikacja showed "Poproś o dane" (2 buttons, no gallery button) | `03_equipment_before.png` |
| 4 | Pass | Clicked the Specyfikacja button once at 07:45:31 UTC. Both sections showed "Szukam danych wyposażenia…". Request body `{"bike_company":"Giant","bike_model":"Revolt Advanced Pro","element_name":"Giant Revolt Advanced Pro","category":"parts"}` | `04_pending.png` |
| 5 | Pass | `POST /v1/equipment/details/search` **200** after 161.6 s. `equipment_id: 2`, category `parts`. Polish description of 933 chars and short description of 197 chars. Sources: giant-bicycles.com product page and a BikeRadar review. Components: Frame / Frame "Revolt Advanced Pro" with Material "Advanced-grade composite carbon", Weight "990 g (M)", Axle standard "12x142 mm", Tyre clearance "42 mm / 53 mm (flip chip)", Seatpost diameter, Brake mount, Cable routing, Sizes. A second element "Advanced SL-Grade Composite fork" has 4 specs. The view rendered both sections: Opis text with source chips, and the tree under "Części rowerowe / Rama" with Polish labels (Materiał, Waga, Standard osi, Prześwit na oponę, Średnica sztycy, Mocowanie hamulca, Prowadzenie linek, Rozmiary) | `search_response.json`, `05_after.png`, `05_after_text.txt` |
| 6 | Pass | After "Wróć" and re-open: `/v1/equipment/details` with `equipment_id: 2` in 87 ms, body identical to the search response. Data shown at once, no button, **no** `/search` request | `06_reentry.png`, `bodies.json` |
| 7 | Pass | After a full app reload and a new search: `/v1/bike/details` lists Frame / Frame "Giant Revolt Advanced Pro" with `equipment_id: 2`. Re-open read the same data in 65 ms, again **no** `/search` request | `07_reload_reentry.png`, `network.json` |
| No 5xx | Pass | 34 `/v1/*` responses: 31 are 200, plus three `/v1/equipment/review` 400 | `network.json` |
| Console | Pass with note | The only console errors are three "Failed to load resource: 400", one per equipment-view open. Each is the known `/v1/equipment/review` 400: the Anthropic API key has no credits. The section stays hidden as designed (earlier plan, E-03). Nothing comes from the change under test | `network.json` |

### Searcher run stats (Cloud Run logs, `biker-searcher-00009-wnn`)

| Metric | Value |
|---|---|
| Request | `equipment details search request | bike='Giant' 'Revolt Advanced Pro' element='Giant Revolt Advanced Pro' type='Frame' category='parts'` |
| CLI message | contains `(listed under "Frame" on the spec sheet)` and "This element carries the bike's own name: it is the Frame of that bike (for a frame: the frameset sold or documented by the bike maker), not the complete bike" |
| CLI | `claude-haiku-4-5-20251001`, `subtype=success`, `num_turns=12`, elapsed 161.16 s, `total_cost_usd=0.338` |
| Result | description 933, short 197, elements 2, sources 2 (the model answered found: true, so the run stored data) |
| Stored | `equipment_id=2`, `component_rows=12`, `linked=4`, `saved=1` |
| Searcher HTTP latency | 161.35 s, status 200 |
| Backend request (browser) | 161.6 s |

### Observations

- O1: the run cost $0.338 with 12 turns and 161 s. That is about twice a typical equipment details run ($0.18–0.27, 8–10 turns, 40–45 s in the earlier plan). It matches the local probe in § 13 ($0.38, 16 turns, 180 s). Frame runs are the expensive kind. Worth watching, as § 13 says.
- O2: the run reused equipment id 2, which an outside photos run had created earlier without details. The details were added to it and the photos were kept. The bike's Frame element already linked to id 2 before this test, so the link check confirms the link survived; the run did not create it.
- O3: the stored element is named "Revolt Advanced Pro", without the brand, and the fork is stored as a second element under Frame. Both are reasonable for a frameset. The view's header keeps the element name "Giant Revolt Advanced Pro".
- O4: spec values stay English ("Hydraulic disc", "Internal brake hose routing"), as designed. Only labels are translated.

**Paid runs (this QA session):** one equipment details run, $0.338. **QA writes on production:** equipment id 2 gained a description, short description and 12 component rows, and 4 element rows of Giant Revolt Advanced Pro were linked. The data is left in place.
