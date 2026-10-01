# TODO-041 production happy path (main 8a3cc97, 2026-10-01)
Frontend https://biker-frontend-ggkzq7ysyq-lm.a.run.app, backend https://biker-backend-ggkzq7ysyq-lm.a.run.app. Public HTTP + UI only. Screenshots in `shots/`.

| # | Case | Result |
|---|------|--------|
| 1 | Canyon Grizl CF 7 ESC: Opis + Komponenty from DB, no "Poproś o dane" in them, no /details/search request | PASS (c1_*.png; network log shows only /details, /review, /allegro, /used/olx, /decathlon, /photos) |
| 2 | Trek Marlin 4 (empty details confirmed) -> Opis button -> both Opis and Komponenty "Szukam danych roweru…" -> filled | PASS, ~125 s wall, 1 /details/search request (c2_*.png) |
| 3a | POST /details after: stored, 2-sentence Polish short_description | PASS |
| 3b | Repeat /details/search returns instantly | PASS, 200 in 0.13 s (Trek Marlin 4) |
| 4 | Search (Filters brand Trek): Marlin 4 card shows short description + chips (Shimano ESSA U2000, Tektro HD-M275, Aluminum); cards without data show no empty paragraph; rating block (TODO-040) shown as "BRAK OCENY" (no review stored) | PASS (c4_search_after.png) |
| 5 | /details unknown bike -> 200 empty; /details/search unknown bike -> 404 "Bike not found" | PASS |

Paid run: Trek Marlin 4, ~125 s, 7 categories (Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Accessories), Polish description with 3 sources.
short_description: "Trek Marlin 4 Gen 3 to wejściowy hardtail górski z aluminiową ramą Alpha Silver i 100mm amortyzacji SR Suntour, przeznaczony dla początkujących rowerzystów. Wyposażony w 8-biegowy napęd Shimano 1x8, hydrauliczne hamulce tarczowe Tektro i dostępny w trzech rozmiarach kół."

Deviations / notes
- My first script clicked the FIRST "Poproś o dane" on the page, which is the photo gallery button, so one unintended /v1/bike/photos/search ran (+ /missing photos) for Trek Marlin 4 (returned in ~3 s; the button is clickable again and no photos stored, so likely nothing found/busy). I then clicked the correct Opis button. So: 1 details search (as planned) + 1 accidental photos search.
- A second /details/search on Canyon Grizl CF 7 ESC was blocked by the auto-mode classifier and not run; the stored-return check (3b) was done on Trek Marlin 4 instead.
- Canyon Grizl CF 7 ESC (older stored details) has empty short_description; its cards show chips but no paragraph. Canyon results contain a duplicate lowercase "canyon / grizl cf 7 esc" card (#8) next to "Canyon Grizl CF 7 ESC" (#9), pre-existing casing duplicate.
