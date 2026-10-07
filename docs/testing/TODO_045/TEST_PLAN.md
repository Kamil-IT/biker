# TODO-045 Frame-size calculator — manual test plan and results

Task: `backlog/TODO_045_FRAME_SIZE_CALCULATOR.md` (tab "Rower na Twoją miarę", `/bike-for-your-fit`, `POST /v1/fit/frame-size`).
Change set: uncommitted diff of `feature/frame-size-calculator` against `origin/main` (docs by another agent were not assessed).
Tester: manual-tester workflow (ISTQB, qa-manual-istqb + webapp-testing), 2026-10-06. Round 1.

## Environment

| Item | Value |
|---|---|
| Backend | `uvicorn` on `http://127.0.0.1:8005` (worktree code, `/docs` and `/openapi.json` reachable) |
| Frontend | Vite dev (React StrictMode on) `http://localhost:5179/bike-for-your-fit`, `/v1` proxied to 8005 |
| Tools | global Python 3.14.3 + Playwright (headless Chromium) and httpx; backend venv for pytest and the smoke case; `tsc --noEmit` |
| Oracle | expected values computed independently with exact `Decimal` arithmetic (ROUND_HALF_UP) from the spec formulas, never from the app's output |
| Scripts / evidence | scratchpad `...\scratchpad\qa045\` (`api_tests.py`, `ui_cases1.py`, `ui_cases2.py`, `harness.py`; screenshots in `shots\`, JSON results `api_results.json`, `ui1_results.json`, `ui2_results.json`). Nothing was written into the repo except this file |

## Traceability (requirement -> code -> status)

| # | Requirement (task file) | Implemented in | Status |
|---|---|---|---|
| R1 | Formulas per type (Road 0.66 cm ±2 good; MTB 0.226 in ±0.8 good; Gravel 0.65−1 cm ±2 medium; Touring / Hybrid 0.66 cm ±2 medium), result 1 decimal | `backend/app/frame_size.py:22-28,57-60` | Implemented (see D-1: exact ties round 0.1 low) |
| R2 | Letters table (cm 50/53/56/59; in 15/17/19/21), letters from the **rounded** size/range, `letter` + `letters` (1–3, ascending) | `frame_size.py:30-35,42-48,62-70` | Implemented |
| R3 | `measurement_warning` when inseam/height outside 0.40–0.50, inclusive, result still computed | `frame_size.py:38-39,61,71` | Implemented |
| R4 | Request validation 140–210 / 60–110 / enum, anything else 422 | `backend/app/schemas.py:124-135` | Implemented |
| R5 | Response model with the 9 fields | `schemas.py:138-146` | Implemented |
| R6 | Router `POST /v1/fit/frame-size`, `main.py` only `include_router`, INFO log with type and numbers | `backend/app/fit_routes.py:44-54`, `main.py:48,81` | Implemented (log line not read live) |
| R7 | Pure function, no I/O, no DB, no AI, no generic cache | `frame_size.py` (imports only `schemas`) | Implemented |
| R8 | pytest `test_frame_size.py` registered | `backend/scripts/test_frame_size.py`, `pytest.ini` | Implemented (461 pass in the registered suite) |
| R9 | Smoke `case_fit_frame_size` (200 + control values, MTB `in`, 422 for 139 / 111 / BMX, no cache row, < 5 s) | `backend/scripts/test_search.py:398-420,1147` | Implemented (ran green against :8005) |
| R10 | `FitPage` replaces `FitComingSoonPage`; `App` renders it for `fit`; teaser CSS gone | `frontend/src/App.tsx:6,341`, file deleted, `index.css` | Implemented |
| R11 | Hook: parse numbers (comma -> dot), 300 ms debounce, `AbortController` (also on unmount), states idle/loading/loaded/invalid/error, previous result kept while loading, no formulas | `frontend/src/hooks/useFrameSize.ts:24-27,53-86`, `api.ts:15-20` | Implemented |
| R12 | Types `FitBikeType`, `FrameSizeRequest`, `FrameSizeResponse` | `frontend/src/types.ts:267-290` | Implemented |
| R13 | Fields Wzrost / Długość nogi (cm, `inputmode=decimal`) + measuring instruction | `FitPage.tsx:37-62,138-152` | Implemented |
| R14 | Type pills (labels as `SearchInput`), default Szosowy | `FitPage.tsx:7-13,154-173` | Implemented |
| R15 | Result card: sketch, big number + unit (`cm` / `cale`), letter, XS–XL scale with `letters` lit and `letter` stronger, "Zakres: a–b", decimal commas | `FitPage.tsx:66-97,122,176-205` | Implemented |
| R16 | `confidence: medium` note; `measurement_warning` text (exact wording); empty state; error state with what-to-do | `FitPage.tsx:99-108,185-203`, `useFrameSize.ts:19-20` | Implemented |
| R17 | `aria-live=polite`, visible focus, `prefers-reduced-motion`, works at 360 px | `FitPage.tsx:19,70,167,176-179`, `FrameSketch.tsx:92-134` | Partial (see D-2: sketch label clipped at 360 px) |
| R18 | Sketch: fixed wheels, seat tube grows clearly with the result (MTB in -> cm for drawing only) | `FrameSketch.tsx:44-89,140-141` | Implemented |
| R19 | Dimension line parallel to the seat tube, BB axis -> tube top, end ticks; label "≈ 52,8 cm"; smooth transition | `FrameSketch.tsx:64-70,84-85,104-134,192-199`, `FitPage.tsx:122` | Implemented |
| A1 | Acceptance: `npm run build` | not run (writes `dist/`); `tsc -p tsconfig.app.json --noEmit` exit 0 used instead | Partial (build left to the lead) |
| X1 | Extra: "Spróbuj ponownie" retry button on error | `FitPage.tsx:192-203`, `useFrameSize.ts:78` | Extra (works) |
| X2 | Extra: previous result dimmed (`opacity-60`) while loading; "Liczę rozmiar…" before the first answer; `aria-busy` | `FitPage.tsx:70,178,190` | Extra |
| X3 | Extra: one screen-reader sentence, visual block `aria-hidden` | `FitPage.tsx:71-74` | Extra |
| X4 | Extra: sketch tube clamped to 40–70 cm, default 52 cm and dashed muted line before a result | `FrameSketch.tsx:33-35,140-142,187` | Extra |
| X5 | Extra: NaN / Infinity answered 422 (custom route class strips `input`) | `fit_routes.py:21-41` | Extra |
| X6 | Extra: out-of-range hint and empty-state text repeat the numbers 140–210 / 60–110 in the frontend | `FitPage.tsx:187`, `useFrameSize.ts:19` | Extra (task demands a range hint; numbers are text only, no logic) |

## Test conditions (equivalence partitions and boundary values)

| TCo | Item | Partitions / boundaries |
|---|---|---|
| C1 | height_cm | < 140 invalid (139, 139.9) · 140 · 140.1 · typical 175 · 209.9 · 210 · > 210 invalid (210.1, 211) · non-numeric / null / missing / NaN / ±Infinity / 0 / negative |
| C2 | inseam_cm | < 60 invalid (59, 59.9) · 60 · 60.1 · 109.9 · 110 · > 110 invalid (110.1, 111) |
| C3 | bike_type | 5 valid keys · `BMX`, `road` (case), `""`, null, `Hybrid`, trailing space, number, array |
| C4 | inseam / height ratio | < 0.40 (180/71.9) · = 0.40 (180/72, 150/60) · inside (178/80) · = 0.50 (180/90, 150/75) · > 0.50 (180/90.1, 178/95) · float edge 171.5/68.6 |
| C5 | Letter bounds, cm | size 49.9/50.0, 52.9/53.0, 55.9/56.0, 58.9/59.0 (Road via inseam 75.6–75.8, 80.2–80.4, 84.7–84.9, 89.3–89.5, incl. 178/80.3 -> 52.998 shown 53.0 = M) |
| C6 | Letter bounds, in | 14.9/15.0, 16.9/17.0, 18.9/19.0, 20.9/21.0 (MTB inseam 66.1–66.5, 75.1–75.3, 84.0–84.3, 92.8–93.1) and the tie 75.0 (16.95) |
| C7 | `letters` length | 1 (150/60 Road XS, 205/110 XL, MTB 178/80 M) · 2 (178/80 Road) · 3 (180/83 Touring S-M-L; Gravel range ending exactly on 53.0) |
| C8 | Rounding ties | exact x.x5 results (62.5 Road, 61 Gravel, 75.0 MTB …): full sweep inseam 60.0–110.0 step 0.1 x 5 types = 2505 cases vs Decimal oracle |
| C9 | Text input | `178`, `178,5`, `178.5`, ` 178 `, empty, `abc`, `1e3`, `-5`, `80,`, `80.`, `.5`, `8 0`, `+80`, `80,5,5`, Arabic digits, 7 digits (maxLength 6), `0`, `999999` |
| C10 | State transitions | idle -> loading -> loaded · loaded -> loading (previous kept) -> loaded · loaded -> invalid -> loaded · loaded -> error -> retry -> loaded · loaded -> cleared -> idle · unmount while pending |
| C11 | Timing | debounce 300 ms after the last change; burst typing -> 1 request; slow typing -> 1 per stable value; stale response must not overwrite the newer one |
| C12 | Environment | desktop 1280, mobile 360 (also 320 / 375 / 390 / 412 / 768 for the label), `prefers-reduced-motion`, keyboard only |

## Test cases and results (round 1)

Evidence = script id in the scratchpad (`api_tests.py` = A-, `ui_cases1.py` U-01–U-20 + U-15b, `ui_cases2.py` U-21–U-29) and screenshots in `shots\`.

### Backend API (httpx against :8005)

| ID | Req | Prio | Case (data -> expected) | Result |
|---|---|---|---|---|
| A-01 | R1 | High | 178/80 Road -> `{size 52.8, cm, 50.8–54.8, S, [S,M], good, false}` (literal spec JSON) | PASS |
| A-02 | R1 | High | 178/80 MTB -> 18.1 in, 17.3–18.9, M, [M], good | PASS |
| A-03 | R1 | High | 178/80 Gravel -> 51.0, 49.0–53.0, S, [XS,S,M], medium | PASS |
| A-04 | R1 | High | 178/80 Touring and Hybrid/Commuter -> 52.8, S, medium | PASS |
| A-06 | R4 | High | C1 boundaries 139 / 139.9 -> 422; 140 / 140.1 / 175 / 209.9 / 210 -> 200; 210.1 / 211 -> 422 | PASS |
| A-07 | R4 | High | C2 boundaries 59 / 59.9 -> 422; 60 / 60.1 / 109.9 / 110 -> 200; 110.1 / 111 -> 422 | PASS |
| A-08 | R4 | High | bike_type `BMX`, `road`, `ROAD`, `""`, null, `Hybrid`, `Folding`, `Hybrid/Commuter `, `Cruiser`, 5, `["Road"]` -> 422 | PASS |
| A-09 | R4 | Med | missing height / inseam / bike_type / empty object -> 422 | PASS |
| A-10 | R4 | Med | height null, `"abc"`, `""`, `[]`, `{}`, `"NaN"`, -1, 0, -178 -> 422 | PASS |
| A-11 | R4 | Low | numeric strings `"178"`, `"80"` -> 200 (lax coercion, informational); unknown extra field -> 200 | PASS (info) |
| A-12 | R4 | High | raw JSON `NaN`, `Infinity`, `-Infinity` in either field -> 422, not 500, no echoed input | PASS |
| A-13 | R3 | High | C4: 180/72 and 180/90 no warning; 180/71.9 and 180/90.1 warning; 178/95 warning; 150/60, 150/75 no warning; 150/75.1 warning; 210/84, 210/105 no warning; 210/83.9, 210/105.1 warning; 171.5/68.6 no warning; 140/60 no warning (0.43); 200/110 warning | PASS |
| A-14 | R2 | High | C5: 12 Road inseams around 50/53/56/59 cm incl. 178/80.3 -> 53.0 M, letters [S,M] | PASS |
| A-15 | R2 | High | C6: 16 MTB inseams around 15/17/19/21 in | PASS |
| A-16 | R2 | High | 178/80.3 Road -> `size 53.0, letter M, letters [S,M]` (the task's own example) | PASS |
| A-17 | R2 | High | C7: `letters` of length 1 (XS, XL, M), 2, 3 as computed from the spec | PASS |
| A-19 | R3 | Med | warning sweep: 4794 height/inseam pairs vs exact ratio oracle | PASS |
| A-20 | R6 | Med | GET -> 405; malformed JSON, empty body, array body -> 422 | PASS |
| A-21 | R6 | Low | 422 body is `{detail:[{type,loc,msg,ctx}]}` without `input` | PASS |
| A-22 | R7 | Med | latency over 30 calls: max 6 ms, median 4 ms | PASS |
| A-23 | R5 | Low | OpenAPI lists the route with min/max and the bike_type enum | PASS |
| A-24 | R4 | Low | float edge: `1e308` -> 422, `1.78e2` and `1.4e2` -> 200 | PASS |
| **A-15b** | R1 | Med | MTB 178/75.0 (75 x 0.226 = 16.95 exactly) -> expected 17.0 in, M (half up); **actual 16.9 in, S, range 16.1–17.8** | **FAIL (D-1)** |
| **A-18** | R1 | Med | C8 sweep, 2505 requests vs Decimal HALF_UP oracle -> **12 mismatches**, all exact x.x5 ties: Road/Touring/Hybrid 62.5; Gravel 61, 65, 71, 81, 85, 91, 105, 107; MTB 75.0. The shown size and both range ends are 0.1 low; the letter flips only for MTB 75.0 | **FAIL (D-1)** |
| A-25 | R8 | High | `pytest` (registered suite incl. `test_frame_size.py`) in the worktree venv -> 461 passed | PASS |
| A-26 | R9 | High | `case_fit_frame_size` from `test_search.py` against :8005 | PASS |
| A-27 | A1 | Med | `tsc -p tsconfig.app.json --noEmit --incremental false` -> exit 0, no output | PASS |

### UI (Playwright, desktop 1280 unless noted)

| ID | Req | Prio | Case (steps -> expected) | Result |
|---|---|---|---|---|
| U-01 | R10, R13, R14 | High | Open `/bike-for-your-fit`: title "Rower na Twoją miarę — Biker", `lang=pl`, labels, `inputmode=decimal`, measuring instruction (book, barefoot), five pills in the specified order, Szosowy checked, empty-state invitation, no request on load, no "Wkrótce", no button in `main`, active tab `aria-current` | PASS |
| U-02 | R15, R19 | High | 178 / 80 / Szosowy -> `52,8` `cm` `S`, scale S strong + M light, "Zakres: 50,8–54,8 cm", sketch label "≈ 52,8 cm", screen-reader sentence, no note, no warning, exactly 1 request `{178, 80, Road}` | PASS |
| U-03 | R15 | High | Switch to Górski (MTB) -> `18,1` `cala` `M`, "Zakres: 17,3–18,9 cala", only M lit, label "≈ 18,1 ″", requests Road then MTB | PASS |
| U-04 | R16 | High | Note "Dla tego typu roweru wynik jest przybliżony…" only for Gravel / Miejski / Trekkingowy; Gravel scale XS+S+M, keys `Hybrid/Commuter` and `Touring` sent for the last two pills | PASS |
| U-05 | R16 | High | 178 / 95 -> exact warning text shown together with `62,7` / XL; 178 / 80 -> warning gone | PASS |
| U-06 | R11 | High | Debounce: inseam 80 first, then type "178" at 70 ms per key -> **1** request, sent 302–330 ms after the last key; clear + retype 179 -> 1 request; typing 1, 16, 165 at 420 ms spacing -> 3 requests (1, 16, 165) | PASS |
| U-07 | R11 | High | "178,5" / "80,5" and "178.5" / "80.5" -> body `{178.5, 80.5}` -> `53,1` | PASS |
| U-08 | R11, R16 | High | 139/80, 211/80, 178/59, 178/111, 0/80, 999999/80 -> "Podaj wzrost od 140 do 210 cm i długość nogi od 60 do 110 cm.", no result, no label, no retry button; 150/70 then recovers to `46,2` | PASS (422 resource errors expected) |
| U-09 | R11 | High | `abc`, `1e3`, `-5`, `80,`, `80.`, `.5`, `8 0`, `,5`, `+80`, `80,5,5`, Arabic digits -> idle invitation, **no request** | PASS |
| U-10 | R11 | Low | Typing `,` after a shown result ("80,") drops the result to the idle invitation until "80,5" is typed | PASS (observation O-2) |
| U-11 | R11 | Med | Clearing a field -> idle invitation, result and label gone, no request; typing again -> exactly 1 new request | PASS |
| U-12 | R11 | Med | Held response: previous result stays, dimmed, `aria-busy=true`; then the new value, `aria-busy=false` | PASS |
| U-13 | R11 | Low | First request pending: "Liczę rozmiar…", `aria-busy=true`, then the result | PASS |
| U-14 | R16 | High | Network abort -> error text + "Spróbuj ponownie"; retry while offline -> new request, still error; backend back -> retry -> `52,8` and the button disappears | PASS |
| U-15 | R16 | Med | HTTP 500 JSON, 502 HTML, 404 -> error state with retry (not "invalid") | PASS |
| **U-15b** | R16 | Low | 200 with HTML body -> error state (PASS); 200 with JSON of the wrong shape `{"unexpected":true}` -> `FitPage` throws `Cannot read properties of undefined (reading 'toFixed')` and **the whole page unmounts** (no error boundary) | **FAIL (D-3)** |
| U-16 | R11 | High | Request 1 held, input changed, request 2 answered -> shows the newer value; request 1 aborted (`net::ERR_ABORTED`); releasing it late changes nothing | PASS |
| U-17 | R11 | Med | Gravel -> Trekkingowy -> Miejski within 100 ms -> one request, `Hybrid/Commuter`, matching result | PASS |
| U-18 | R17 | High | Keyboard: Tab height -> inseam -> checked radio (one tab stop); arrows move Road→MTB→Gravel→Hybrid→Touring, wrap both ways, Up/Down work, each re-requests; focus ring visible on inputs and pills | PASS |
| U-19 | R13 | Med | Enter in a field: no reload / navigation; maxLength 6 ("1234567" -> "123456"); " 178 " trimmed | PASS |
| U-20 | R17 | Med | `aria-live=polite`, svg `role=img` + label, visual block `aria-hidden`, labels bound to inputs, fieldset + legend "Typ roweru", radios share a name | PASS |
| U-21 | R18, R19 | High | Sketch geometry from the SVG for 160/68 (44.9), 178/80 (52.8), 195/92 (60.7), MTB 18.1 in: dimension line parallel to the seat tube (< 0.5°), length = tube length = result x 2.588 px/cm (±2 %), starts on the BB axis, ends at the tube top, offset 40 px, two end ticks, perpendicular, 14 px, centred on the line ends, solid when labelled; label starts with "≈" and equals the size; tube grows 44.9 -> 60.7 cm by ~41 px; idle = dashed muted line, no label | PASS |
| U-22 | R19 | Med | Screenshots at 44.9 / 52.8 / 60.7 / 39.6 / 72.6 cm: tube top inside the viewBox, label inside the card at 1280; 39.6 and 72.6 cm are drawn as 40 / 70 cm (clamp) | PASS (observation O-4: label box overlaps the rear wheel rim at 44.9 and 52.8 cm) |
| **U-23** | R17 | High | 360 x 740: no horizontal scroll and no element beyond the viewport in idle / road / MTB / Gravel + warning + note / 72.6 cm / invalid / error. **Sketch label is cut off at the card's left edge** for results ≥ ~58 cm (up to 4 px at 360; up to 14 px at 320; fine from 375 px) | **FAIL (D-2)** |
| U-24 | R19 | Med | `reduced_motion=reduce`: the frame path jumps (≤ 2 shapes during the change), result `transition-property: none`; normal motion: path glides through ≥ 4 shapes, `transition-property: opacity` | PASS |
| U-25 | R17 | Med | Contrast of the design-token colour pairs (computed): see O-5 | PASS (informational) |
| U-26 | RG | High | Tabs and routes: `/rower-na-twoja-miare` -> `/bike-for-your-fit`, `/kontakt` -> `/contact`, tab clicks without reload (`window` marker kept), home search form, contact form, Back / Forward, no frame-size request, no console errors | PASS |
| U-27 | R11 | Med | Leaving the tab inside the 300 ms window -> no request; leaving with a request in flight -> aborted; returning -> empty fields | PASS (observation O-3) |
| U-28 | R11 | Med | StrictMode: one request per input / type change, none on reload | PASS |
| U-29 | R11 | Low | Served source: teaser keyframes / `.scan` gone; no 0.66 / 0.226 / 0.65 / 0.40 / 0.50 in `FitPage.tsx` or the hook | PASS |

### Regression set (re-run on every round)

| ID | Area | Case |
|---|---|---|
| RG-01 | Tabs | U-26 (Szukanie rowerów / Rower na Twoją miarę / Kontakt, legacy addresses, Back / Forward) |
| RG-02 | Home | U-26 home page loads without console errors (screenshot `U26_home_desktop.png`) |
| RG-03 | Backend | A-25 registered pytest suite (461) and A-26 smoke case |
| RG-04 | Calculator | U-02, U-03, U-05, U-06, U-08, U-14 and A-01, A-13, A-14 |

## Defects and observations

| ID | Sev | Case | Description | Evidence | Suspected cause |
|---|---|---|---|---|---|
| D-1 | Low | A-15b, A-18 | Binary-float rounding of exact half results: 12 of 2505 inseams show a size and range 0.1 lower than mathematics gives (62.5 Road 41.2 instead of 41.3; 75.0 MTB 16.9 instead of 17.0). For MTB inseam 75.0 the letter flips M -> S. The spec states no tie rule, so the shown number and letter stay consistent with each other; the fix is cheap | `api_results.json`; the A-18 row lists all 12 | `backend/app/frame_size.py:58-60` rounds the float product; use `Decimal(str(x))` + `quantize(ROUND_HALF_UP)` or `round(x + 1e-9, 1)`, and add 75.0 MTB / 62.5 Road to `test_frame_size.py` |
| D-2 | Low | U-23 | At 360 px the dimension label ("≈ 60,8 cm" and longer) is clipped by the card's `overflow-hidden` on its left border; the text stays readable at 360, the "≈" is cut at 320 px | `shots\V_m_warn.png`, `V_m_max.png`, `U23_warn_360.png` | `frontend/src/components/FrameSketch.tsx:192-199` anchors the label with `-translate-x-full` left of the line; clamp its x to the card or flip it to the right side when it would leave |
| D-3 | Low | U-15b | A 200 answer whose JSON lacks the expected fields unmounts the whole app (React error in `FitPage`, no error boundary). Needs a contract break, e.g. a stale / foreign backend answering 200 | `ui1_results.json` | `useFrameSize.ts:63` trusts the response shape; `FitPage.tsx:26` calls `toFixed` on `undefined`. Validate the shape (treat as error) or add an error boundary |

Observations (no action required, listed for the lead):

- O-1 Extra behaviour X1–X6 above: retry button, dimmed previous result, `aria-busy`, "Liczę rozmiar…", clamped sketch, NaN guard. All work as intended.
- O-2 A trailing separator while typing a decimal ("80,") makes the field "not a number", so the shown result disappears for a moment (idle invitation) and returns after the next digit (U-10).
- O-3 Leaving the tab and returning clears the fields (state is not kept); the rest of the search flow keeps its state (U-27).
- O-4 The sketch label sits on the rear wheel rim at the default 52.8 cm and at 44.9 cm (screenshots `V_d_s.png`, `V_d_m.png`); it is clear of the wheel from about 60 cm.
- O-5 Contrast (computed from tokens): muted placeholder `178` / `80` and the input's "cm" suffix on sand 2.58:1 (< 4.5); parchment text on terra in the lit S/M scale cell 3.78:1 for 13 px text (< 4.5); all other pairs pass (muted on charcoal, parchment/70 cells, terra letter at 36 px, note, label).
- O-6 Typing a field slowly while the other one is already filled sends the prefix values (1, 16, then 165): each is a 422, the "Podaj wzrost od 140…" hint flashes and the browser console logs a failed-resource error per prefix (U-06). Fast typing is covered by the debounce. The frontend deliberately does not validate (spec), so this is a consequence of the design.
- O-7 On a phone the result card sits ≈ 1250 px below the top (under the form); after typing the user must scroll to see the answer (`U23_road_360.png`).
- O-8 Pill touch targets are 41 px high (≥ 24 px required, 44 px recommended); inputs use 20 px text so there is no iOS zoom.
- O-9 Backend accepts numeric strings in the JSON body and ignores unknown fields (Pydantic lax mode).
- O-10 Sketch is not to scale outside 40–70 cm: the 72.6 cm result (Road inseam > 106) is drawn as a 70 cm tube (3.6 %); the label shows the real size.
- O-11 Not executed: `npm run build` (writes `dist/`), the INFO log line on the server (log not readable from here), a real phone / Safari run, docs (another agent).

## Summary (round 1)

57 cases: **53 passed · 4 failed · 0 blocked** (3 defects: D-1 covers A-15b and A-18; D-2 = U-23; D-3 = U-15b). All severities Low; none blocks an acceptance criterion: 178/80 -> 52,8 cm S 50,8–54,8, MTB 18,1 cala M, live result without a click, debounce, warning for 178/95, dimension line with end ticks along the seat tube with "≈", no horizontal scroll at 360 px. Console errors seen: only the 422 resource errors from deliberately invalid input and `ERR_FAILED` from the deliberate network abort; on the happy paths and on the regression pages the console was clean (the React error in U-15b is the D-3 case).


---

# Round 2 (2026-10-06) — retest after the fixes

Fixes under test (lead's list): D-1 `backend/app/frame_size.py` (Decimal arithmetic, `ROUND_HALF_UP`; uvicorn on :8005 restarted), D-2 `FrameSketch.tsx` (label above the upper end of the dimension line on a leader, kept inside the card), D-3 `useFrameSize.ts` (response-shape check, bad shape -> error state), contrast: lit scale cell `bg-terra-dark`, letter `text-terra-light` (new token in `index.css`). Same environment as round 1 (backend :8005, Vite :5179 with HMR). Scripts: `api_tests.py` (A-), `ui_cases1.py`, `ui_cases2.py`, `ui_cases3.py` (round-2 cases), `harness.py`; screenshots `shots\V2_*.png`; JSON `api_results2.json`, `ui3_results.json`.

Test-script changes needed by the new markup (not app defects): the label is now a `div.absolute > span` and the lit scale cell uses `bg-terra-dark`; the selectors in the harness were updated. The analytic contrast case U-25 was replaced by two computed-in-browser cases (U-30, U-30b).

## Round-2 results

### Re-run of the round-1 failures and the new checks

| ID | Req | Prio | Case | Result |
|---|---|---|---|---|
| A-15b | R1 | Med | MTB 178/75.0 -> 17.0 in, M, range 16.2–17.8 (was 16.9 S) | PASS (D-1 fixed) |
| A-18 | R1 | Med | Sweep inseam 60.0–110.0 step 0.1 x 5 types = 2505 requests vs the exact Decimal HALF_UP oracle -> 0 mismatches (was 12) | PASS (D-1 fixed) |
| A-28 | R1 | Med | The 12 round-1 tie cases: Road/Touring/Hybrid 62.5 -> 41.3 [39.3–43.3]; Gravel 61 -> 38.7, 65 -> 41.3, 71 -> 45.2, 81 -> 51.7, 85 -> 54.3, 91 -> 58.2, 105 -> 67.3, 107 -> 68.6; MTB 75.0 -> 17.0 M | PASS |
| A-29 | R1 | Med | Random sweep, 3000 requests, height and inseam with 1–3 decimals, all 5 types, vs the Decimal oracle -> 0 mismatches | PASS |
| A-30 | R1 | Med | Inseam grid step 0.05 for Road / MTB / Gravel = 3003 requests vs the oracle (every x.xx5 tie) -> 0 mismatches | PASS |
| U-15b | R16 | Low | `{"unexpected":true}` and an HTML 200 -> error state, page alive (was: white screen) | PASS (D-3 fixed) |
| U-15c | R16 | Med | 21 wrong-shape 200 bodies (`{}`, null, array, string, number, missing `size` / `range_max` / `letter` / `measurement_warning`, `size` as string or null, `unit` km, `letter` XXL, empty / non-array / junk `letters`, unknown `bike_type`, bad `confidence`, string warning, `{detail}` envelope): each -> "Nie udało się policzyć rozmiaru…" + "Spróbuj ponownie", no result, page alive. A valid body with an extra unknown field is accepted; retry with a valid body recovers (`53,5`); a bad shape after a loaded result drops the old result | PASS |
| U-23 | R17 | High | 360 x 740, all states: no horizontal scroll, label inside the card (was clipped) | PASS (D-2 fixed) |
| U-23b-320 | R17 | High | 320 px, 30 sizes (Road, Gravel, MTB, inseam 62–110): label fully inside the card, no stroke under the label, nothing of `main` beyond the viewport | PASS (see N-1 for the page-level scroll at 320) |
| U-23b-360 | R17 | High | 360 px, same 30 sizes | PASS |
| U-23b-375 | R17 | High | 375 px, same 30 sizes | PASS |
| U-23b-412 | R17 | Med | 412 px, same 30 sizes | PASS |
| U-23c | R17 | High | 360 px states idle / road / MTB / Gravel + warning + note / invalid / error: no horizontal scroll, nothing beyond the viewport | PASS |
| U-22b | R19 | High | Label placement at ~41 / 53 / 61 / 73 cm (Road inseam 62.1 / 80.3 / 92.4 / 110 -> 41.0 / 53.0 / 61.0 / 72.6 cm) at 1280: label sits above the upper end of the dimension line on a leader, no stroke (rim, saddle, frame, stem) under it, inside the card, gap to the line 0 px. Sweep of 33 sizes (Road, MTB, Gravel x inseam 60–110 step 5): no collision, never outside the card. Screenshots `shots\V2_d_41.png`, `V2_d_53.png`, `V2_d_61.png`, `V2_d_73.png`, narrow `V2_320_max.png`, `V2_360_warn.png`, `V2_375_s.png` | PASS (O-4 fixed) |
| U-30 | R17 | High | Contrast of every text / background pair of the **result card**, computed in the browser (painted background, alpha composited) in 8 states (idle, Road, MTB, Gravel + note + warning, XS, L, invalid, error): all >= 4.5:1. Lowest: unit "cm" / "cala" and "Zakres:" (muted on charcoal) 4.72; letter in terra-light 5.10; scale cells 5.18–5.78; note 8.15; numbers, range, warning, label 13.3 | PASS |
| **U-30b** | R17 | Med | Contrast of the **form** text: placeholder `178` / `80` (20 px) and the "cm" suffix in the inputs (14 px), muted on sand, are **2.58:1** (< 4.5). Labels, hint and pills pass | **FAIL (D-4, carried over from O-5)** |

### Regression and acceptance re-run

| IDs | Covers | Result |
|---|---|---|
| A-01, A-02, A-03, A-04, A-06, A-07, A-08, A-09, A-10, A-11, A-12, A-13, A-14, A-15, A-16, A-17, A-19, A-20, A-21, A-22, A-23, A-24 (22 cases) | control example, MTB, Gravel / Touring / Hybrid, boundaries 139–211 / 59–111, bad types, NaN / Infinity, warning boundaries, letter bounds, `letters` 1–3, GET 405, 422 body, latency, OpenAPI | all PASS |
| A-25 | `pytest` registered suite in the worktree venv: **477 passed** (461 in round 1) | PASS |
| A-26 | `case_fit_frame_size` against :8005 | PASS |
| A-27 | `tsc -p tsconfig.app.json --noEmit` exit 0 | PASS |
| U-01 – U-20 (20 cases) | page content, control example 52,8 / S / "Zakres: 50,8–54,8 cm" / label "≈ 52,8 cm" / 1 request, MTB 18,1 cala M, notes and warning, **debounce** (1 request 320 ms after the last key; slow typing 1 per value; stale response aborted), comma / dot, invalid hint, non-numbers, state transitions, error + retry, 500 / 502 / 404, rapid toggling, **keyboard** (Tab order, all arrows, wrap, focus rings), Enter, maxLength, aria | all PASS (U-02, U-03, U-04 after the harness learned `bg-terra-dark` for the lit cell) |
| U-21 | sketch geometry: dimension line parallel to the seat tube, BB axis -> tube top, two perpendicular end ticks, "≈ <size>" label matching, tube grows with the result | PASS |
| U-22 | label vs rim / card at 44.9 / 52.8 / 60.7 / 39.6 / 72.6 cm: no rim crossing note any more | PASS |
| U-24 | **reduced motion**: jump, no opacity transition; normal motion glides | PASS |
| U-26 | **tabs and redirects**: `/rower-na-twoja-miare` -> `/bike-for-your-fit`, `/kontakt` -> `/contact`, tab clicks without reload, Back / Forward, home page, console clean | PASS |
| U-27, U-28, U-29 | unmount abort, StrictMode request count, teaser CSS removed / no formulas in the frontend | PASS |

## Round-1 defects: verification

| ID | Status | How verified |
|---|---|---|
| D-1 float rounding of exact halves | **Fixed, verified** | A-15b, A-18 (2505 / 0 mismatches), A-28, A-29, A-30 |
| D-2 label clipped at 360 px | **Fixed, verified** | U-23, U-23b at 320 / 360 / 375 / 412, U-22b; screenshots `shots\V2_*` |
| D-3 wrong-shape 200 blanks the page | **Fixed, verified** | U-15b, U-15c (21 shapes) |
| O-4 label on the rear wheel rim | Fixed | U-22b (33 sizes) and screenshots |
| O-5 contrast | **Partly fixed**: result card now >= 4.72:1 (U-30); the form's placeholder and "cm" suffix are still 2.58:1 | U-30b -> D-4 |

## New / remaining issues (round 2)

| ID | Sev | Case | Description | Evidence | Suspected cause |
|---|---|---|---|---|---|
| D-4 | Low | U-30b | Placeholder text `178` / `80` and the unit suffix "cm" inside the two fields are muted (#9C8E82) on sand (#EDE7DC): 2.58:1, below 4.5:1. The suffix carries information (the unit) | `ui3_results.json` (U-30b) | `FitPage.tsx:19` `placeholder:text-muted` and `FitPage.tsx:56` suffix `text-muted`; use `text-ink` (or a darker muted) on sand |

Observations (no action required):

- N-1 At 320 px the whole page scrolls horizontally (scrollWidth 327 > 320) because of the top tabs nav (`LI` / `A.whitespace-nowrap`); identical on `/` and `/contact`, so it is pre-existing and outside this task. Nothing inside `main` overflows; the task's target is 360 px, where there is no scroll.
- N-2 The branch is 5 commits behind `origin/main` (up to `07c4d25`, PRs #158 and #159) and `origin/main` changed 6 files that this branch also changes (`CLAUDE.md`, `backend/README.md`, `frontend/README.md`, `backend/app/schemas.py`, `backend/scripts/test_search.py`, `frontend/src/types.ts`): expect small merge conflicts, and `git diff origin/main` now shows unrelated main-side work as deletions.
- N-3 At 41 cm the label chip ends about 8 px from the saddle (clear, but the tightest spot); below 420 px the chip text is 11 px.
- N-4 `types.ts` now holds runtime constants (`FIT_BIKE_TYPES`, `FRAME_SIZE_LETTERS`) used by the shape check; `tsc` and the build-relevant checks are clean.
- N-5 Round-1 observations O-2, O-3, O-6, O-7, O-8, O-9, O-10 are unchanged (not in the fix list).

## Summary (round 2)

68 cases: **67 passed · 1 failed · 0 blocked**. The three round-1 defects (D-1, D-2, D-3) and the rim overlap are fixed and verified; the single failure is D-4 (Low): form placeholder and "cm" suffix contrast, carried over from round 1 and not part of the fix list. All acceptance checks pass: 178/80/Szosowy 52,8 cm S 50,8–54,8, MTB 18,1 cala M, live result, debounce, warning for 178/95, keyboard, reduced motion, tabs and redirects, no horizontal scroll at 360 px. Console: only the expected 422 / `ERR_FAILED` resource errors from deliberately provoked states; nothing on the happy paths or regression pages.


---

# Round 3 (2026-10-06) — retest of D-4

Fix under test: `FitPage.tsx` — the "cm" suffix is now `text-ink`, the input placeholders use the new token `--color-muted-dark` #716559 (`index.css`). Same environment (backend :8005, Vite :5179). Scripts as before (`ui_cases3.py` U-30 / U-30b, `ui_cases1.py`, `ui_cases2.py`, `api_tests.py`); screenshots `shots\R3_form_idle_d.png`, `R3_form_filled_d.png` (and `_m` at 360 px).

## Round-3 results

| ID | Case | Result |
|---|---|---|
| U-30b | Contrast of the form text, computed in the browser: placeholder `178` / `80` now 4.60:1 (was 2.58), "cm" suffix and every other form element >= 8.31:1 once filled; idle minimum 4.60:1, 15 elements | PASS (D-4 fixed) |
| U-30 | Result card unchanged: all text/background pairs in 8 states >= 4.5:1, lowest 4.72:1 (unit "cm" / "cala", "Zakres:") | PASS |
| U-01 | Page content, default type, no request on load | PASS |
| U-02 | Control example 178 / 80 / Szosowy: `52,8` `cm` `S`, S + M lit, "Zakres: 50,8–54,8 cm", label "≈ 52,8 cm", exactly 1 request | PASS |
| U-03 | MTB: `18,1` `cala` `M`, range 17,3–18,9 cala, label "≈ 18,1 ″" | PASS |
| U-04 | Note only for Gravel / Miejski / Trekkingowy; values per type | PASS |
| U-05 | Warning for 178 / 95 with the result `62,7` XL; gone for 178 / 80 | PASS |
| U-06 | Debounce: char-by-char typing -> 1 request, 321 ms after the last key; slow typing -> 1 per value | PASS |
| U-08 | Out-of-range -> Polish range hint, recovers | PASS |
| U-14 | Network error -> message + retry -> recovers | PASS |
| U-16 | Stale response aborted, newest value wins | PASS |
| U-18 | Keyboard: Tab order, arrows, wrap, focus rings (also on the inputs) | PASS |
| U-20 | aria-live, svg role, labels, fieldset | PASS |
| U-21 | Sketch geometry (parallel dimension line, ticks, label) | PASS |
| U-22b | Label placement at 41 / 53 / 61 / 73 cm and a 33-size sweep | PASS |
| U-23c | 360 px states: no horizontal scroll, nothing of `main` beyond the viewport | PASS |
| U-24 | Reduced motion jumps, normal motion glides | PASS |
| U-26 | Tabs and redirects (`/rower-na-twoja-miare`, `/kontakt`), Back / Forward, home page | PASS |
| U-27 | Unmount abort, empty fields after returning | PASS |
| A-01 … A-24, A-28, A-29, A-30 (27 rows) | `api_tests.py`: 30 / 30 script checks (control example, MTB, all types, boundaries, bad input, NaN, warning boundaries, letter bounds, `letters` 1–3, 2505-request oracle sweep, 3000 random, 3003 grid) | all PASS |
| A-25 | `pytest` registered suite: 477 passed | PASS |
| A-26 | `case_fit_frame_size` against :8005 | PASS |
| A-27 | `tsc --noEmit` exit 0 | PASS |

Console: no `error` / `warning` entries in any of these runs except the 422 / `ERR_FAILED` resource errors of the deliberately provoked states (U-08, U-14); happy paths and the regression pages were clean.

Observation (new, info): with the darker placeholder the example values `178` / `80` read as grey-brown against near-black typed digits (screenshots `R3_form_idle_d.png` vs `R3_form_filled_d.png`): still clearly distinguishable, but they look like numbers; that is the mockup's design choice.

## Round-3 summary

49 cases: **49 passed · 0 failed · 0 blocked**. D-4 is fixed and verified; no regressions.

---

# Final results (all rounds, final status)

Status = result of the latest run of each case; "last run" = the round in which it was last executed. No case is open.

| ID | Case | Last run | Final |
|---|---|---|---|
| A-01 | Road 178/80 -> 52.8 cm [50.8–54.8] S [S,M] good (literal spec JSON) | r3 | PASS |
| A-02 | MTB 178/80 -> 18.1 in [17.3–18.9] M | r3 | PASS |
| A-03 | Gravel 178/80 -> 51.0 [49.0–53.0] S [XS,S,M] medium | r3 | PASS |
| A-04 | Touring and Hybrid/Commuter 178/80 -> 52.8, medium | r3 | PASS |
| A-06 | Height boundaries 139 / 139.9 / 140 / 140.1 / 209.9 / 210 / 210.1 / 211 | r3 | PASS |
| A-07 | Inseam boundaries 59 / 59.9 / 60 / 60.1 / 109.9 / 110 / 110.1 / 111 | r3 | PASS |
| A-08 | Invalid `bike_type` values -> 422 | r3 | PASS |
| A-09 | Missing fields -> 422 | r3 | PASS |
| A-10 | Non-numeric / zero / negative height -> 422 | r3 | PASS |
| A-11 | Numeric strings accepted (informational) | r3 | PASS |
| A-12 | NaN / Infinity / -Infinity -> 422, not 500 | r3 | PASS |
| A-13 | Warning only outside ratio 0.40–0.50 (boundaries inclusive) | r3 | PASS |
| A-14 | Road letter bounds around 50 / 53 / 56 / 59 cm | r3 | PASS |
| A-15 | MTB letter bounds around 15 / 17 / 19 / 21 in | r3 | PASS |
| A-15b | MTB tie 75.0 -> 17.0 in, M (D-1) | r3 | PASS (fixed in round 2) |
| A-16 | 178/80.3 Road -> 53.0 cm, M, [S,M] | r3 | PASS |
| A-17 | `letters` of length 1 / 2 / 3 | r3 | PASS |
| A-18 | 2505-request sweep vs Decimal HALF_UP oracle (D-1) | r3 | PASS (fixed in round 2) |
| A-19 | Warning sweep, 4794 pairs | r3 | PASS |
| A-20 | GET 405; malformed / empty / array body 422 | r3 | PASS |
| A-21 | 422 body shape, no echoed input | r3 | PASS |
| A-22 | Latency (max 9 ms) | r3 | PASS |
| A-23 | OpenAPI lists the route | r3 | PASS |
| A-24 | Float edge inputs | r3 | PASS |
| A-25 | `pytest` registered suite (477) | r3 | PASS |
| A-26 | `case_fit_frame_size` smoke | r3 | PASS |
| A-27 | `tsc --noEmit` | r3 | PASS |
| A-28 | The 12 round-1 tie cases round half up | r3 | PASS |
| A-29 | 3000 random requests vs oracle | r3 | PASS |
| A-30 | 3003-request grid step 0.05 vs oracle | r3 | PASS |
| U-01 | Page content, default type, empty state | r3 | PASS |
| U-02 | Control example end to end | r3 | PASS |
| U-03 | MTB 18,1 cala M | r3 | PASS |
| U-04 | Approximate note per type | r3 | PASS |
| U-05 | Measurement warning 178/95 | r3 | PASS |
| U-06 | Debounce (1 request ~320 ms after the last key) | r3 | PASS |
| U-07 | Decimal comma / dot | r2 | PASS |
| U-08 | Out-of-range hint, recovery | r3 | PASS |
| U-09 | Non-numbers send no request | r2 | PASS |
| U-10 | Trailing separator drops the result (observation O-2) | r2 | PASS |
| U-11 | Clearing a field -> idle | r2 | PASS |
| U-12 | Previous result kept and dimmed while loading | r2 | PASS |
| U-13 | First request pending text | r2 | PASS |
| U-14 | Network error + retry | r3 | PASS |
| U-15 | 500 / 502 / 404 -> error state | r2 | PASS |
| U-15b | 200 with wrong shape no longer blanks the page (D-3) | r2 | PASS (fixed in round 2) |
| U-15c | 21 wrong-shape bodies, extra field tolerated, retry recovers | r2 | PASS |
| U-16 | Stale response aborted | r3 | PASS |
| U-17 | Rapid type toggling -> one request | r2 | PASS |
| U-18 | Keyboard navigation and focus rings | r3 | PASS |
| U-19 | Enter, maxLength, trimming | r2 | PASS |
| U-20 | aria | r3 | PASS |
| U-21 | Sketch geometry | r3 | PASS |
| U-22 | Sketch composition at 5 sizes | r2 | PASS |
| U-22b | Label placement 41 / 53 / 61 / 73 cm + 33-size sweep | r3 | PASS |
| U-23 | 360 px, all states (D-2) | r2 | PASS (fixed in round 2) |
| U-23b-320 | 320 px: label in card, no stroke under it | r2 | PASS |
| U-23b-360 | 360 px | r2 | PASS |
| U-23b-375 | 375 px | r2 | PASS |
| U-23b-412 | 412 px | r2 | PASS |
| U-23c | 360 px states, no overflow in `main` | r3 | PASS |
| U-24 | Reduced motion | r3 | PASS |
| U-26 | Tabs, redirects, Back / Forward, home | r3 | PASS |
| U-27 | Unmount abort, state after returning | r3 | PASS |
| U-28 | StrictMode request count | r2 | PASS |
| U-29 | Teaser CSS gone, no formulas in the frontend | r2 | PASS |
| U-30 | Result-card contrast, all pairs >= 4.5:1 (min 4.72) | r3 | PASS |
| U-30b | Form contrast >= 4.5:1 (min 4.60 idle) (D-4) | r3 | PASS (fixed in round 3) |

U-25 (analytic contrast, round 1) was superseded by U-30 / U-30b and is not counted.

## Defect log (final)

| ID | Sev | Found | Fixed and verified |
|---|---|---|---|
| D-1 float rounding of exact halves (A-15b, A-18) | Low | round 1 | round 2 |
| D-2 label clipped at 360 px (U-23) | Low | round 1 | round 2 |
| D-3 wrong-shape 200 blanks the page (U-15b) | Low | round 1 | round 2 |
| D-4 form placeholder and "cm" suffix contrast (U-30b) | Low | round 2 | round 3 |

Remaining observations, none requiring action for this task: O-2 trailing separator drops the shown result, O-3 fields reset after leaving the tab, O-6 slow typing sends prefix values (422 + console resource error), O-7 on a phone the result is about 1250 px down, O-8 pills 41 px high, O-9 backend accepts numeric strings and unknown fields, O-10 sketch clamped to 40–70 cm, N-1 the top tabs nav makes the page scroll horizontally at 320 px (pre-existing, all pages), N-2 branch 5 commits behind `origin/main` with 6 overlapping files (merge before the PR), N-3 label chip is 11 px below 420 px and 8 px from the saddle at 41 cm. Not covered: `npm run build` (writes `dist/`; `tsc --noEmit` is clean), the server log line, a real phone / Safari run, docs.

## Final totals

**68 cases (49 re-run in round 3, the rest last run in round 2): 68 passed · 0 failed · 0 blocked.** All four defects are closed.
