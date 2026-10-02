# Production manual test plan: main `7b7955a` on GCP (2026-10-02)

**Change under test:** the production deployment of `main` at `7b7955a` (= `e0ee89a` + docs). It contains PR #136 (search-cache tables dropped), PR #137 (`bike_detail` removed) and PR #138 (TODO-042, equipment details and photos through the searcher). This is a post-deploy regression of the whole app on production data.

**Test basis:** `CLAUDE.md`, `backend/README.md` § Endpoints, `frontend/README.md`, and the 46-case local plan `docs/testing/MAIN_2026-10-02_FULL_APP/TEST_PLAN.md`, whose case IDs are reused here.

## Scope, approach, environment

| Item | Value |
|---|---|
| Frontend | Cloud Run `biker-frontend`, https://biker-frontend-ggkzq7ysyq-lm.a.run.app |
| Backend | Cloud Run `biker-backend`, https://biker-backend-ggkzq7ysyq-lm.a.run.app (curl / urllib) |
| Searcher | Cloud Run `biker-searcher`, never called directly; its runs were observed only through the backend and `gcloud logging read` (read-only) |
| Database | Cloud SQL `biker-pg`, never touched directly; stored state was read through the API only |
| Browser | Python Playwright (global `python`), Chromium headless, 1400x1000, scripts and screenshots in the session scratchpad `qa-prod/` |
| Anthropic API key | has **no credits**, so every SDK call is a 400. That is expected for the search AI fallback, parse, equipment review and Ceneo. The UI must degrade, not break |
| Paid budget | at most 2 searcher runs. Planned as one equipment details run plus a conditional photos run. After the first details run came back empty, the lead approved the second slot for another details run and no photos run |

**Not run on production (no cost-free or no-touch way):**
- D-05, D-06, E-04 and A-14 need a stopped searcher.
- D-07 and D-08 are paid bike runs outside the budget.
- A-15 would call the searcher directly.
- A-16 seeds fixtures into the database.
- DB-01 to DB-05 need direct database access. Stored state was checked through the API instead.

Techniques: use-case scenarios per screen, equivalence partitions on stored-data state (full / photos only / nothing), boundary values on request validation (255/256, 512/513, id 0, 32/33), `RequestDataButton` state transitions, and error guessing on the no-credit key.

### Test data (production, as read through the API before testing)

| Role | Bike / item | Stored state |
|---|---|---|
| Bike A (full) | Trek / Marlin 5 | description (English, 718 chars), 29 component elements, `short_description` empty, 8 photos, no review, 5 OLX offers, 1 Allegro offer (new), no Decathlon |
| Bike B (less data) | Trek / Marlin 6 | photos only (8). No description, components, review or offers |
| Popular | Giant Revolt Advanced Pro, Romet Aspre, Trek Madone SL 6 | ratings 8.4 / 7.0 / 8.2 |
| Paid element P1 | "Shimano Altus RD-M315" on bike A (Drivetrain / Rear Derailleur) | no equipment row; the `equipment` table was empty at deploy time |
| Paid element P2 | "Shimano Altus FD-M315" on bike A (Drivetrain / Front Derailleur) | no equipment row |
| Linked element (not created by QA) | "Giant Through Axle" on Giant Revolt Advanced Pro | created at 06:59–07:00 UTC by the user testing production by hand: equipment id 1, details stored, 4 element rows linked, no photos |

Entry criteria: frontend `/` and backend `/docs` answer 200. Exit criteria: every in-scope case Pass, or failures reported with evidence. Severity: Critical (page broken / data loss), High (feature wrong), Medium (degraded), Low (cosmetic).

## Test cases

### Home (H)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| H-01 | High | Open `/` | "Najpopularniejsze rowery" shows the 3 cards in position order with stored casing |
| H-02 | High | Wait for ratings | `GET /v1/bike/popular` once, one `POST /v1/bike/review` per bike, numeric ratings, no console errors |
| H-03 | High | Click the first card, then "Wróć do wyników" | Details view opens; back returns to the home list |

### Search (S)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| S-01 | High | Filters: Trek / Marlin 5 | DB hit < 5 s; one card with drivetrain/frame chips, no explanation paragraph (empty `short_description`), "?" / "Brak oceny" |
| S-02 | High | Filters: brand Giant | several cards; rated cards first, sorted by rating, unrated "?" last |
| S-03 | Medium | Filters: Trek / Marlin 6 | one card without explanation and without chips |
| S-04 | High | Free text "szukam roweru do miasta" only | `/v1/bike/parse` 400; Polish warning above the search box; no `/v1/bike/search` |
| S-05 | High | Filters: brand "Zzqx Nonexistent" | AI fallback 400; error banner; page usable; a following search works |

### Bike details (D)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| D-01 | High | Open bike A, wait > 5 s | gallery, Opis, component tree, Used card (OLX), New card (Allegro); "Poproś o dane" only in the review section |
| D-03 | High | Open bike B, wait > 5 s | gallery photos shown; buttons in Opis, Specyfikacja, review, Used, New (5) |
| D-09 | Medium | Back from details | returns to the previous list |
| D-10 | Medium | Top tabs "Rower na Twoją miarę", "Kontakt", "Szukanie rowerów" | URL `/rower-na-twoja-miare`, `/kontakt`, `/`; `aria-current="page"` on the active tab; Kontakt fieldset disabled; search results kept |
| D-11 | Medium | Deep links `/kontakt`, `/rower-na-twoja-miare`, `/nie-ma-takiej` | HTTP 200 (SPA fallback); right tab; unknown path rewritten to `/` |

### Equipment (E)
| ID | Pri | Steps | Expected |
|---|---|---|---|
| E-01 | High | Giant Revolt Advanced Pro, click "Giant Through Axle" (linked) | reads `/v1/equipment/details` + `/photos` with `equipment_id: 1`; Polish description and spec tree shown; no `/search`; only the gallery button (no photos stored) |
| E-02 | High | Bike A, click "Shimano Altus RD-M315", wait > 5 s | reads by name (`company: ""`) return empty; 3 buttons (Zdjęcia, Opis, Specyfikacja); no `/v1/bike/missing` |
| E-03 | High | Same view, review section | `/v1/equipment/review` 400; section hidden; rest of the page intact |
| E-05 | High | **P1 / P2 (paid)**: click the Opis button | one `/v1/equipment/details/search`, Opis and Specyfikacja both show "Szukam danych wyposażenia…"; then data in Polish in both, or "Nie znaleziono danych" in both |
| E-06 | High | After E-05: back to bike A, re-open the element | data read from the DB by `equipment_id`, no second `/search`; `/v1/bike/details` carries `equipment_id` on that element; `/v1/equipment/details` by id answers the stored data |

### API regression (A), urllib against the backend URL
| ID | Pri | Request | Expected |
|---|---|---|---|
| A-01 | High | `/v1/bike/search` Trek/Marlin 5; `{is_electric:true}` | 200 DB hit < 5 s, no `match_score` |
| A-02 | High | `/v1/bike/search` `{}` and `{gender:"x"}` | 422 |
| A-03 | High | `/v1/bike/search` `{brand:"Zzqx Nonexistent"}` | 400 with Anthropic's detail |
| A-04 | High | `/v1/bike/missing` unknown bike; `missing_type` "" / 65 chars | 200 `bike_id:null, counter:0`; 422 |
| A-05 | High | `GET /v1/bike/popular` | 200, 3 bikes, < 5 s |
| A-06 | High | `/v1/bike/details` A, unknown; company 255 / 256; empty model | stored data with `short_description`, no `photos`, elements carry an `equipment_id` key; empty shape for unknown; 200 / 422 / 422 |
| A-07 | High | the six `/v1/bike/*/search` routes with an unknown bike | 404 "Bike not found" fast |
| A-08 | High | `/v1/bike/photos`, `/review`, `/used/olx`, `/allegro`, `/decathlon` for A and unknown | 200 stored / empty shapes < 1 s |
| A-09 | High | `/v1/bike/decathlon/search` bike A (foreign brand) | 200 `offers:[]` + Polish "Decathlon nie sprzedaje…" `info`, no searcher run |
| A-10 | High | `/v1/equipment/details` + `/photos` by unknown name, unknown id; by id 1 and by name in other casing | empty shape `equipment_id:null`; stored values by both |
| A-11 | High | `/v1/equipment/details` `equipment_id:0`, `model:""`, model 512 / 513, category 33 | 422, 422, 200 / 422, 422 |
| A-12 | High | `/v1/equipment/details/search` + `/photos/search`: unknown bike; bike A + unknown element; missing `element_name`; element 256 chars | 404 "Bike not found"; 404 "Component not found"; 422; 422 (all without a searcher run) |
| A-13 | Medium | `/v1/equipment/review` (uncached item), `/v1/bike/parse`, `/v1/bike/ceneo` | 400 with Anthropic's detail, never 5xx |

**Total in scope: 31 cases** (H 3 · S 5 · D 5 · E 5 · A 13).

## Results (2026-10-02, 08:50–09:10 local time)

**31 passed · 0 failed · 0 blocked.** No 5xx anywhere: every response seen in the browser and in the 53 API checks was 200, 400, 404 or 422.

| Case | Result | Evidence / notes |
|---|---|---|
| H-01 | Pass | 3 cards: Giant Revolt Advanced Pro, Romet Aspre, Trek Madone SL 6 (`h01_home.png`) |
| H-02 | Pass | `/v1/bike/popular` once, 3 reviews: 8.4 / 7.0 / 8.2; no console errors |
| H-03 | Pass | card click opens Giant details (5 DB reads + review); "Wróć do wyników" shows the popular list again |
| S-01 | Pass | 2.5 s; chips "Shimano Altus RD-M315", "Aluminum"; no explanation; "?" + "Brak oceny" (`s01_trek_marlin5.png`) |
| S-02 | Pass | Giant: 8 cards, Revolt Advanced Pro 8.4 first, 7 unrated "?" after it (`s02_giant.png`) |
| S-03 | Pass | Marlin 6 card: no explanation, no chips, "Brak oceny" |
| S-04 | Pass | parse 400, alert "Nie znaleziono: Nie mamy tego roweru w naszej bazie", no `/v1/bike/search` (`s04_freetext.png`) |
| S-05 | Pass | search 400, banner "Błąd: Your credit balance is too low…" (O2), next search Trek / Marlin 6 works (`s05_unknown_brand.png`) |
| D-01 | Pass | 8 photos, Opis, tree, Used: 5 OLX offers, New: 1 Allegro offer; one button, in "Recenzja ekspertów" (`d01_after_grace.png`) |
| D-03 | Pass | photos shown; 5 buttons: Opis, Specyfikacja, review, Used, New (`d03_after_grace.png`) |
| D-09 | Pass | back from details returns to the list (home and results) |
| D-10 | Pass | URLs, `aria-current`, page titles "Rower na Twoją miarę — Biker" / "Kontakt — Biker"; Kontakt fieldset disabled; Marlin 6 result kept (`d10_tab_*.png`) |
| D-11 | Pass | all three deep links HTTP 200; `/nie-ma-takiej` → `/` (`d11_*.png`) |
| E-01 | Pass | `equipment_id: 1` sent in both reads; Polish description, sources, spec tree (Polish labels, "Thread pitch" untranslated, O5); only the gallery button; no `/search` (`e01_linked_giant_axle.png`) |
| E-02 | Pass | reads by name `{"company":"","model":"Shimano Altus RD-M315"}` empty; 3 buttons; no `/v1/bike/missing` (`e02_equip_view.png`) |
| E-03 | Pass | `/v1/equipment/review` 400; review section not rendered; only that 400 in the console |
| E-05 (P1) | Pass with note | "Shimano Altus RD-M315": one `/v1/equipment/details/search`, body `{bike_company:"Trek", bike_model:"Marlin 5", element_name:"Shimano Altus RD-M315"}` (no category; the searcher picked `parts`). Both sections showed "Szukam danych wyposażenia…" (`e05_pending.png`) and no photos search was sent. Searcher log: CLI 40.3 s, 10 turns, $0.176, "model reports the item was not found", nothing written. Both sections then showed "Nie znaleziono danych" (`e05_after.png`). This code does not exist (O6), and the local run saw the same result. The empty path is correct |
| E-05 (P2) | Pass | "Shimano Altus FD-M315": one shared run, both sections "Szukam danych wyposażenia…" (`e05b_pending.png`), 45.6 s. Both sections then filled in Polish (`e05b_after.png`): description 756 chars, short description 279 chars, 2 elements (Napęd / "Shimano Altus FD-M315-TS" and General / "FD-M315-TS"), sources dassets.shimano.com and productinfo.shimano.com (Shimano PDFs). The gallery button stayed and no photos search was sent |
| E-06 | Pass | After P2, back to Marlin 5 and re-open: `/v1/equipment/details` and `/photos` sent with `equipment_id: 3`, data shown at once, only the gallery button, no `/search` (`e06b_reenter.png`). API: `/v1/bike/details` Marlin 5 has `equipment_id: 3` on Drivetrain / Front Derailleur "Shimano Altus FD-M315" only. `/v1/equipment/details` by id 3 and by lower-case name answer the stored data in 0.08 s. `/v1/equipment/photos` by id 3 gives `photos: []`. After P1 (empty) the re-entry read by name, sent no `/search` and showed the 3 buttons again (O4). Linked read on the user's equipment id 1: both Giant "Giant Through Axle" rows carry `equipment_id: 1` (E-01) |
| A-01 – A-12 | Pass | 52 of 53 checks passed on the first pass. Every DB read took under 0.5 s (max `/v1/bike/search {is_electric:true}` 0.48 s, others 0.05–0.13 s). Every 404 guard answered in about 0.1 s without a searcher run |
| A-13 | Pass (retest) | The first pick, `Shimano / Altus RD-M315`, was a 200 from the old generic cache: a test-data error (O3). Uncached `Zzqx / QA Uncached Part 7781` gave a 400 with Anthropic's detail. Parse and Ceneo gave 400 |

**Observations (not regressions of this deployment):**
- O1: the stored descriptions and review explanations of the popular bikes and of Trek Marlin 5 are English, while the docs say Polish. This is old data.
- O2: a search 400 shows the backend's English Anthropic message inside the Polish banner ("Błąd: Your credit balance is too low…").
- O3: the generic-cache row of `/v1/equipment/review` for `Shimano / Altus RD-M315` describes a different part (RD-M310). Its explanation keeps raw `<cite index="…">` markup, which `/v1/equipment/review` returns unstripped. The UI asks with `company: ""`, so it misses this row and the section stays hidden. Low.
- O4: after an empty equipment search, re-entering the item shows "Poproś o dane" again, so another paid run is one click away. This is by design.
- O5: several spec keys and one subcategory have no Polish label in `specLabels.ts`, so they fall back to English: "Thread pitch" (Giant axle), and "Cable pull", "Mounting type", "Chainstay angle" and the subcategory "General" (FD-M315). Low.
- O6: the stored Trek Marlin 5 spec lists "Shimano Altus RD-M315". Shimano's Altus rear derailleur is the RD-M310 (FD-M315 is the front derailleur), so the part code is probably wrong in the stored details. The model's "not found" is then a correct answer, not a searcher fault. A component element with a wrong code costs a paid run that cannot succeed.
- O7: the user tested production by hand at the same time. The searcher logs show an equipment photos run and a details run at 06:59 UTC for "Giant Through Axle" on Giant Revolt Advanced Pro. The details run stored equipment id 1: Polish description, 6 component rows, 4 element rows linked, 75.6 s, $0.135. Its photos run ended at 07:03 UTC after 237 s (CLI 33 turns, $0.849, the backend request 237.4 s) with no product URL found, and wrote nothing. That is about five times a details run for a generic part name, and worth a look at the photos prompt's turn budget (Medium, cost). A further outside photos run started at 07:02 UTC for the element "Giant Revolt Advanced Pro" (the frame), with a CLI time of 37.3 s and $0.098. That element now carries `equipment_id: 2`. Each searcher request started a new Cloud Run instance (`--concurrency 1`), with a cold start of about 15 s before the CLI starts.

**Paid runs (this QA session)**

| Run | Case | Wall time (UI) | Searcher / CLI | Cost (CLI) | Stored (as seen through the API) |
|---|---|---|---|---|---|
| P1 equipment details, "Shimano Altus RD-M315" on Trek Marlin 5 | E-05 | 45.4 s (backend 43.4 s) | CLI 40.3 s, 10 turns, `found: false` | $0.176 | nothing: `/v1/equipment/details` by name stays empty, no `equipment_id` on the bike's element |
| P2 equipment details, "Shimano Altus FD-M315" on Trek Marlin 5 (approved by the lead) | E-05 / E-06 | 45.6 s (backend 45.4 s) | CLI 45.1 s, 8 turns, `found: true` | $0.266 | equipment id 3 (`parts`): description, short description, 10 component rows (2 elements), linked to Marlin 5's front-derailleur row only |

**Total paid by QA: 2 runs, $0.442.** No photos run was made, on the lead's instruction.

**QA writes on production:** one `bike_missing_request` attempt for an unknown bike (`qa_prod`), which writes nothing by design. P1 wrote nothing. P2 wrote equipment id 3 and linked one element row of Trek Marlin 5. That data is left in place, like the local QA data. The UI buttons for the equipment view send no `/v1/bike/missing`.
