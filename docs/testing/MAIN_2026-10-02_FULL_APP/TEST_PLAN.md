# Full-app manual test plan — main `e0ee89a` (2026-10-02)

**Change under test:** merged `main` at `e0ee89a` — PR #136 (TODO-043, search-cache tables dropped), PR #137 (`bike_detail` table removed; details live on `bike.description` / `bike.short_description`, components keyed by `bike_id`), PR #138 (TODO-042, equipment details and photos through the searcher). Regression of the whole app, not one task.

**Test basis:** `CLAUDE.md` (endpoints + frontend tables), `backend/README.md` § Endpoints, `frontend/README.md`, `searcher/README.md`.

## Scope, approach, environment

| Item | Value |
|---|---|
| Worktree | `biker-wt/deploy-e0ee89a`, detached at `e0ee89a`, no commits |
| Backend | uvicorn `:8003`, `DATABASE_URL` = local PostgreSQL `biker-pg` (already on the new layout; no migration run by QA) |
| Searcher | uvicorn `127.0.0.1:8101`, real `claude` CLI (subscription) |
| Frontend | Vite `:5178`, `BIKER_API_URL=http://localhost:8003` |
| Browser | Python Playwright (global `python`), Chromium headless, scripts + screenshots in the session scratchpad `qa-main/` |
| Anthropic API key | has **no credits**: every SDK call answers 400 — expected for search AI fallback, parse, equipment review, Ceneo; the UI must degrade, not break |
| Paid budget | **3** searcher runs, chosen for coverage (P1 equipment details, P2 bike photos, P3 Allegro via the New card on a non-Decathlon brand, whose Decathlon half is the free instant-info path) |
| Smoke suite | `scripts/test_search.py` with `BIKER_API_URL=http://localhost:8003` and `SEARCHER_URL` emptied so its single live Decathlon case SKIPs (it would be a 4th paid run) |

Techniques: use-case scenarios per screen, equivalence partitions on stored-data state (full / details only / nothing), boundary values on request validation (empty, 255/256, 512/513, id 0), state transitions of `RequestDataButton` (grace → button → pending → filled / empty label / clickable again), error guessing on the dropped tables.

### Test data

| Role | Bike / item | Stored state (2026-10-02, before testing) |
|---|---|---|
| Bike A (full) | Cannondale / Topstone Carbon 4 (id 39) | description, 67 component rows, 8 photos, review, 1 OLX offer; popular #1; `short_description` empty |
| Bike B (details only) | Trek / Marlin 4 (id 44) | description, 33 component rows, `short_description` set; no photos, review or offers |
| Bike C (nothing) | Specialized / Rockhopper Comp 29 (id 7) | bike row only |
| Equipment fixture E1 | "Schwalbe G-One Allround" (tyres) on bike A | **seeded by QA** with `equipment_repository.save_equipment_details` + `save_equipment_photos` (2 photo URLs), linked to bike A's element; `equipment` was empty before |
| Paid P1 element | "Wellgo C-156 Composite Platform Pedals" on bike A (Accessories / Pedals) | no equipment row |

Entry criteria: three servers answer (`/docs`, `/health`, Vite `/`). Exit criteria: every case Pass, or failures reported to the lead with evidence. Severity: Critical (page broken / data loss), High (feature wrong), Medium (degraded), Low (cosmetic).

## Test cases

### Home (H)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| H-01 | High | Open `/` | "Najpopularniejsze rowery" shows 3 cards in `position` order: Cannondale Topstone Carbon 4, Trek Madone SL 6, Giant Revolt Advanced Pro; stored casing; blurb ≤ 2 sentences or none |
| H-02 | High | Same page, wait for ratings | `GET /v1/bike/popular` once (StrictMode may double), one `POST /v1/bike/review` per bike; bike A shows a numeric rating, a bike without a review "Brak oceny"; no console errors |
| H-03 | High | Click bike A's card | Details view of bike A opens |

### Search (S)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| S-01 | High | Filters: brand Trek, model Marlin 4 → search | Results from the DB (no Anthropic call in the backend log, < 5 s); card shows B's stored short description and accessory chips |
| S-02 | High | Filters: brand Cannondale → search | Several cards; numerals "—" while pending, then a number or "?"; after settling, rated cards sorted by rating descending, unrated last |
| S-03 | Medium | Filters: brand Specialized, model Rockhopper Comp 29 | One card without explanation paragraph and without chips |
| S-04 | High | Free text only "szukam roweru do miasta", submit | `/v1/bike/parse` → 400 (no credits); Polish warning above the search box; no `/v1/bike/search` request; page usable |
| S-05 | High | Filters: brand "Zzqx Nonexistent" → search | DB miss → AI fallback → 400; UI shows an error / not-found state, no crash, can search again |

### Bike details (D)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| D-01 | High | Open bike A | Gallery 8 photos; Opis text; component tree (translated labels); review explanation + source table; Used card shows the OLX offer; no "Poproś o dane" in those sections |
| D-02 | High | Bike A, wait > 5 s | New card shows "Poproś o dane" (no new offers stored) |
| D-03 | High | Open bike B, wait > 5 s | Opis + component tree shown; buttons in gallery, review, Used, New; none in Opis / Komponenty |
| D-04 | High | Open bike C, wait > 5 s | Buttons in gallery, Opis, Komponenty, review, Used, New |
| D-05 | High | **Searcher stopped**: bike C, click Opis button | `/v1/bike/missing` `description` 200; `/v1/bike/details/search` 503; button clickable again; no crash |
| D-06 | Medium | **Searcher stopped**: bike C, click gallery button | `/missing` `photos` 200; `/v1/bike/photos/search` 503; button clickable again |
| D-07 | High | **P2** (searcher up): bike B, click gallery "Poproś o dane" | "Szukam zdjęć…" while running; photos replace the button, or "Nie znaleziono zdjęć"; `bike_missing_request` (B, photos) +1; `bike_detail_photos` rows for B (insert-only) |
| D-08 | High | **P3**: bike A, click New card button | `/missing` `offers_new`; `/v1/bike/decathlon/search` instant 200 with the Polish not-sold `info` (no searcher run); `/v1/bike/allegro/search` runs once; rows land in New/Used by `is_new`, or "Nie znaleziono ofert" |
| D-09 | Medium | From details click back | Returns to the previous list (results or home) |
| D-10 | Medium | Top tabs: click "Rower na Twoją miarę", "Kontakt", "Szukanie rowerów" | URL `/rower-na-twoja-miare`, `/kontakt`, `/`; `aria-current="page"` on the active tab; Kontakt form disabled; search results kept |
| D-11 | Medium | Deep links: open `/kontakt`, `/rower-na-twoja-miare`, `/nie-ma-takiej` directly | Right tab rendered; unknown path rewritten to `/` |

### Equipment (E)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| E-01 | High | Bike A → click "Schwalbe G-One Allround" (E1, linked) | `/v1/equipment/details` and `/v1/equipment/photos` sent with `equipment_id`; seeded description, spec tree and 2 photos shown; no `/search` request; no buttons |
| E-02 | High | Bike A → click "Shimano GRX RD-RX812" (no `equipment_id`), wait > 5 s | Reads by name (`company: ""`) return empty; buttons in gallery, Opis, Specyfikacja (3); no `/v1/bike/missing` call from them |
| E-03 | High | Same view: review section | `/v1/equipment/review` 400 (no credits); section shows a graceful unavailable/empty state; rest of the page intact |
| E-04 | High | **Searcher stopped**: click equipment Opis button | `/v1/equipment/details/search` 503; button clickable again |
| E-05 | High | **P1**: bike A → "Wellgo C-156 Composite Platform Pedals" → click Opis button | One `/v1/equipment/details/search` (Specyfikacja button shares it, "Szukam danych wyposażenia…" on both); data fills Opis + Specyfikacja; DB: `equipment` row + details + components, bike A's element row gets `equipment_id` |
| E-06 | High | After E-05: back to bike A, click the pedals again | Reads by `equipment_id`, data shown at once, no second `/search` |

### API regression (A) — curl / httpx against `:8003`
| ID | Pri | Request | Expected |
|---|---|---|---|
| A-01 | High | `/v1/bike/search` `{brand:"Trek",model:"Marlin 4"}`; `{wheel_size:...}` / `{is_electric:true}` | 200 DB hit < 5 s, no `match_score` |
| A-02 | High | `/v1/bike/search` `{}` and `{gender:"x"}` | 422 |
| A-03 | High | `/v1/bike/search` `{brand:"Zzqx Nonexistent"}` | 400 with Anthropic's detail |
| A-04 | High | `/v1/bike/missing` A twice; unknown bike; `missing_type` "" / 65 chars | counter +1 each; 200 `bike_id:null,counter:0`; 422 |
| A-05 | High | `GET /v1/bike/popular` | 200, 3 bikes, < 5 s |
| A-06 | High | `/v1/bike/details` A, B, C, unknown; company 256 chars; empty model | stored data with `short_description`, no `photos`, elements carry `equipment_id` key; empty shape for C/unknown; 422 |
| A-07 | High | `/v1/bike/details/search`, `/photos/search`, `/review/search`, `/used/search`, `/allegro/search`, `/decathlon/search` unknown bike | 404 "Bike not found" fast |
| A-08 | High | `/v1/bike/photos`, `/review`, `/used/olx`, `/allegro`, `/decathlon` for A and unknown | 200 stored / empty shapes < 5 s |
| A-09 | High | `/v1/bike/decathlon/search` bike A (foreign brand) | 200 `offers:[]` + Polish `info`, < 5 s, no searcher call |
| A-10 | High | `/v1/equipment/details` + `/photos` by id, by name (other casing), unknown id, unknown name | stored values by both; empty shape `equipment_id:null` |
| A-11 | High | `/v1/equipment/details` `equipment_id:0`, `model:""`, model 513 chars, category 33 chars | 422 |
| A-12 | High | `/v1/equipment/details/search` + `/photos/search`: unknown bike; known bike + unknown element; missing `element_name` | 404 "Bike not found"; 404 "Component not found"; 422 |
| A-13 | Medium | `/v1/equipment/review`, `/v1/bike/parse`, `/v1/bike/ceneo` | 400 with Anthropic's detail (no credits), not 500 |
| A-14 | High | **Searcher stopped**: details/search B, review/search B, equipment/details/search (A + real element) | 503 with the documented fixed detail strings |
| A-15 | High | Searcher direct: `/health`; `/v1/search/details` without key; with key and `{}` | 200 ok + DB true; 401; 422 |
| A-16 | High | Smoke suite `scripts/test_search.py` (`BIKER_API_URL=:8003`, `SEARCHER_URL=""`) | All cases PASS, live Decathlon SKIP |

### DB sanity (DB) — read-only `psql`
| ID | Pri | Check | Expected |
|---|---|---|---|
| DB-01 | High | `\dt` | no `bike_detail`, no `search_cache`, no `search_bike_rating_cache`; `equipment*` tables present |
| DB-02 | High | bikes with components but no `bike.description` | 0 (or explained by discovery rows) |
| DB-03 | High | `bike_detail_component.bike_id` NULL count; `equipment_id` pointing at a missing `equipment` | 0 / 0 |
| DB-04 | High | `equipment` ↔ `equipment_detail` (≤ 1 per equipment) ↔ components / photos FKs | consistent; E1 and P1 rows present and linked to bike A only |
| DB-05 | Medium | Paid-run writes | P2 photos for B only; P3 `allegro.pl` rows for A only; `bike_missing_request` rows for the clicks |

**Total: 46 cases** (H 3 · S 5 · D 11 · E 6 · A 16 · DB 5).

## Results — rounds 1 and 2 (2026-10-02, final)

Round 1: 44 passed · 0 failed · 2 blocked (E-05, E-06, data path not observed).
Round 2 (approved 4th paid run): **46 passed · 0 failed · 0 blocked**

| Case | Result | Evidence / notes |
|---|---|---|
| H-01 – H-03 | Pass | 3 popular cards in position order, ratings 7.2 / 8.2 / 8.4 from 3 `/v1/bike/review` calls, click opens details; no console errors |
| S-01 | Pass | Trek / Marlin 4 → 1 card with the stored Polish short description and chips "Shimano ESSA", "Tektro HD-M275", "Aluminum"; "?" (no review) |
| S-02 | Pass | brand Cannondale → 3 cards, numerals 7.2, ?, ? (rated first) |
| S-03 | Pass | Rockhopper Comp 29 card has no explanation and no chips, "Brak oceny" |
| S-04 | Pass | parse 400 → alert "Nie znaleziono: Nie mamy tego roweru w naszej bazie", no `/v1/bike/search` |
| S-05 | Pass | AI fallback 400 → error banner, a new search afterwards works. Observation O2 |
| D-01 – D-04 | Pass | Bike A: 8 photos, Opis, tree, review table, 5 OLX offers, only the New card shows the button. Bike B: 4 buttons (gallery, review, Used, New). Bike C: 6 buttons |
| D-05, D-06 | Pass | Searcher stopped: `/missing` 200 (`description`, `photos`), `/details/search` and `/photos/search` 503, buttons clickable again |
| D-07 (P2) | Pass | Trek Marlin 4 photos: "Szukam zdjęć…", 8 trekbikes.com photos stored and shown, 30 s, `/missing` photos 200 |
| D-08 (P3) | Pass (empty path) | Cannondale New card: Decathlon foreign-brand 200 at once, Allegro 200 with 0 offers after 51 s, button "Nie znaleziono ofert"; `/missing` offers_new. The offers-found path was not exercised |
| D-09 – D-11 | Pass | back keeps results; tabs set URL + `aria-current`, Kontakt fieldset disabled, results kept; deep links incl. unknown path → `/` |
| E-01 | Pass | linked fixture read by `equipment_id: 1`, seeded description, spec and 2 photos, no search, no buttons |
| E-02, E-03 | Pass | unlinked element read by name, 3 buttons, no `/missing`; equipment review 400 hides the section, page intact |
| E-04 | Pass | searcher stopped: equipment details and photos search 503, all 3 buttons clickable again, no `/missing` |
| E-05 (P1) | Pass with note | "Wellgo C-156 Composite Platform Pedals" (obscure OEM pedal): one shared run, both buttons "Szukam danych wyposażenia…", model answered `found: false` after 38 s ($0.16), nothing written, both buttons "Nie znaleziono danych". The empty path is correct |
| E-05 (P4, round 2) | Pass | "Shimano GRX RD-RX812": one shared run, 105 s (CLI 104 s, 11 turns, $0.25). Polish description (789 chars), short description, 2 elements and 2 sources shown in Opis and Specyfikacja. DB: equipment id 4 with 1 details row and 7 component rows, `equipment_id` 4 set on bike 39's element row only. Another bike's row with the same name stays unlinked, as specified |
| E-06 (round 2) | Pass | back + re-enter reads `/v1/equipment/details` with `equipment_id: 4` and shows the data; no second search |
| A-01 | Pass (retest) | `{is_electric:true, brand:"Trek"}` was a DB miss (no Trek e-bike stored) → AI 400; test-data error. `{is_electric:true}` → 200 DB hit |
| A-02 – A-13, A-15 | Pass | 69/70 API checks in round 1, all documented statuses, 422 boundaries (255/256, 512/513, id 0 and 2^31), 404 guards before the searcher |
| A-14 | Pass | searcher stopped: 5 search routes → 503 with the documented fixed details |
| A-16 | Pass | `test_search.py`: 18 passed, 0 failed, 4 skipped (live Decathlon with `SEARCHER_URL` unset, 3 `--ai` cases) |
| DB-01 – DB-05 | Pass | no `bike_detail` / `search_cache` / `search_bike_rating_cache`; 619 bikes with components all have `bike.description`; 0 NULL `bike_id`, 0 dangling `equipment_id`; after round 2: 2 equipment rows (fixture id 1 and P4 id 4), each with 1 details row, linked to bike 39 only; smoke fixtures cleaned up; P2 wrote 8 photos for bike 44 only; P3 wrote nothing |

**Observations (not regressions of these PRs):**
- O1: the stored descriptions and review explanations of the popular bikes are English, while the docs say Polish. This is old data.
- O2: a search 400 shows the backend's English Anthropic message inside the Polish banner ("Błąd: Your credit balance is too low…"). Search errors pass `detail` straight to the banner.
- O3: the Allegro search's `info` comes back in English ("No current active listings found…").
- O4: after an empty equipment search, re-entering the item shows "Poproś o dane" again, so another paid run is one click away. This is by design, because button state lives in the component, the same as for bikes.
- QA data left in `biker-pg`: equipment id 1 (fixture, linked to bike 39), equipment id 4 from P4 (linked to bike 39), `bike_missing_request` rows from the clicks plus `qa_regression` (counter 2) on bike 39, and 8 photos for Trek Marlin 4 from P2.

**Paid runs**

| Run | Case | Wall time | Cost (CLI) | Written |
|---|---|---|---|---|
| P1 equipment details, Wellgo pedals | E-05 | 39 s (CLI 38 s) | $0.161 | nothing (`found: false`) |
| P2 bike photos, Trek Marlin 4 | D-07 | 30 s (CLI 19 s + scrape) | $0.063 | 8 rows in `bike_detail_photos` for bike 44 |
| P3 Allegro via New card, Cannondale Topstone Carbon 4 | D-08 | 51 s (CLI 51 s) | $0.192 | nothing (0 listings) |
| P4 equipment details, Shimano GRX RD-RX812 (approved by the lead) | E-05 / E-06 | 105 s (CLI 104 s, 11 turns) | $0.251 | equipment id 4: 1 details row, 7 component rows, bike 39's element linked |

**Total paid: 4 runs, $0.667.**
