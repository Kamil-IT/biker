# ISSUE-016 — plan testów manualnych: flaga `is_linkable` na elementach komponentów

**Zadanie:** `backlog/TODO_ISSUE_016_COMPONENT_LINKABLE_FLAG.md` · **gałąź:** `feature/issue-016-component-linkable` · **data:** 2026-10-02
**Środowisko:** worktree `biker-wt/feature-issue-016-component-linkable`; backend `:8002`, searcher `:8102`, frontend `:5178` (Vite → 8002); lokalny PostgreSQL `biker-pg` po `migrate_component_linkable.py` (27829 true / 5143 false).
**Zasada kosztowa:** żadnych płatnych wyszukiwań szukacza (`/v1/bike/details/search`); ścieżka „model → zapis” pokryta testami jednostkowymi szukacza. API Anthropic (widok sprzętu) nie ma kredytów — jego odpowiedź błędu jest oczekiwana i darmowa.

## Wymagania (test basis)

| ID | Wymaganie |
|---|---|
| R1 | `bike_component.is_linkable` (bool, NOT NULL) zwracane w `ComponentElement.is_linkable` przez `POST /v1/bike/details` |
| R2 | Widok szczegółów roweru: nazwa elementu jest linkiem do widoku sprzętu **tylko** gdy `is_linkable === true`; inaczej zwykły tekst |
| R3 | Szukacz: schemat JSON wymaga `is_linkable` per element, prompt opisuje regułę; tylko literalne `true` jest zapisywane jako `true`; zapis/odczyt round-trip |
| R4 | Heurystyka regex `app/linkable.py` (EN + PL): „brak części”, dokumenty, nazwa = podkategoria, wymiary ≠ kody modeli, części ogólne bez marki → `False`; produkt z marką/kodem → `True`; używana przez migrację i scraper |
| R5 | Migracja: `--dry-run` nic nie zapisuje i pokazuje rozkład, realny run weryfikowany, rerun = `already-migrated` (flagi modelu zachowane), `--reclassify` nadpisuje heurystyką |
| R6 | Widok sprzętu bez zmian (nazwy nigdy nie są linkami) |
| R7 | Kolejność deployu i migracja udokumentowane (CLAUDE.md, README, backend/README, DB_MIGRATION, searcher/README, frontend/README) |

## Traceability

| Wymaganie | Implementacja | Status |
|---|---|---|
| R1 | `backend/app/models.py` (`is_linkable`), `schemas.py` `ComponentElement`, `repository.py` `rebuild_components` / `save_bike_details` | Implemented |
| R2 | `frontend/src/types.ts`, `BikeDetailsShared.tsx` `ElementItem` (`linkable = … && is_linkable === true`) | Implemented |
| R3 | `searcher/app/details_finder.py` (schema + `el.get("is_linkable") is True`), `prompts/bike_details.md`, `schemas.py`, `models.py` (DDL + check startowy), `repository.py` | Implemented |
| R4 | `backend/app/linkable.py`; `webscraper/centrumrowerowe/product_parser.py` `_Tree.build` | Implemented |
| R5 | `backend/scripts/migrate_component_linkable.py` | Implemented |
| R6 | `EquipmentDetailsView` nie przekazuje `onElementSelect` (bez zmian) | Implemented (no change) |
| R7 | `CLAUDE.md`, `README.md`, `backend/README.md`, `backend/app/DB_MIGRATION.md`, `searcher/README.md`, `frontend/README.md` | Implemented |

Extra (niewymagane, zgłoszone): brak.

## Warunki testowe

- TC-A (R1): każda odpowiedź `/v1/bike/details` ma `is_linkable` typu bool na każdym elemencie; dla Giant Revolt Advanced Pro w Akcesoriach tylko „Giant Multi-Tool” = true.
- TC-B (R2): partycje — `true` → `<button aria-label="Zobacz szczegóły wyposażenia: …">`; `false` → `<p>` bez przycisku; zbiór podlinkowanych nazw w całym drzewie = zbiór nazw z `true` w API.
- TC-C (R2/R6): klik w link `true` otwiera widok sprzętu; w widoku sprzętu brak linków-elementów.
- TC-D (R3): wartości `true` / `false` / brak / `"true"` (string) / `1` → tylko pierwsza daje `true`; schemat wymaga pola; round-trip przez `save_details`.
- TC-E (R4): partycje heurystyki (produkt z marką, kod modelu, „not included”, PL „brak w zestawie”, dokumenty, nazwa = podkategoria, wymiary, części ogólne, polskie znaki).
- TC-F (R5): dry-run → brak kolumny; run → flagi; rerun → `already-migrated` i ręcznie zmieniona flaga zachowana; `--reclassify` → heurystyka; baza bez tabeli → `absent`; realna baza `biker-pg`: rerun `already-migrated`.
- TC-G (regresja): strona główna z popularnymi rowerami i ocenami; wejście w szczegóły z karty; rower bez szczegółów → „Poproś o dane” w sekcji Komponenty; wyszukiwanie po filtrach marka+model (DB, bez AI) → wyniki → szczegóły.

## Przypadki testowe

| ID | Wym. | Warunki wstępne | Kroki | Dane | Oczekiwany wynik | Prio |
|---|---|---|---|---|---|---|
| TC-01 | R1 | backend :8002 | `POST /v1/bike/details` | Giant / Revolt Advanced Pro | 200; każdy element ma `is_linkable` bool; Akcesoria: Giant Multi-Tool=true, None included / Owner's Manual / Quick Start Guide / Warranty Documentation=false | P1 |
| TC-02 | R2 | frontend :5178 | Strona główna → karta „Giant Revolt Advanced Pro” → sekcja Akcesoria | j.w. | „Giant Multi-Tool” jest przyciskiem z aria-label „Zobacz szczegóły wyposażenia: Giant Multi-Tool” i strzałką ↗; pozostałe 4 nazwy to zwykły tekst (brak przycisku) | P1 |
| TC-03 | R1+R2 | j.w. | W widoku szczegółów zebrać wszystkie przyciski-linki elementów i porównać z API | j.w. | zbiór nazw przycisków == zbiór nazw z `is_linkable: true` w API; liczba elementów bez przycisku == liczba `false` | P1 |
| TC-04 | R2/R6 | j.w. | Klik „Giant Multi-Tool” | — | otwiera się widok sprzętu z nagłówkiem „Giant Multi-Tool”; brak przycisków „Zobacz szczegóły wyposażenia” w tym widoku; powrót działa | P2 |
| TC-05 | R3 | venv | `pytest searcher/scripts/test_details_finder.py` | — | zielone, w tym `test_is_linkable_taken_from_the_model_only_when_literally_true`, `test_schema_requires_is_linkable_per_element`, `test_is_linkable_round_trips_through_save_details` | P1 |
| TC-06 | R4 | venv | `pytest backend/scripts/test_linkable.py` + `webscraper … test_product_parser.py::test_is_linkable_set_by_the_shared_heuristic` | — | zielone | P1 |
| TC-07 | R5 | venv | `pytest backend/scripts/test_migrate_component_linkable.py`; `migrate_component_linkable.py` na `biker-pg` ponownie | — | zielone; `RESULT: already-migrated`; rozkład w DB 27829/5143 | P1 |
| TC-08 | reg. | frontend | Strona główna | — | sekcja „Najpopularniejsze rowery” z ≥ 3 kartami, bez błędów konsoli typu `Uncaught` | P2 |
| TC-09 | reg. | frontend | Filtry → Marka „Giant”, Model „Revolt Advanced Pro” → Szukaj → klik karty | — | wynik z DB (bez AI), szczegóły otwierają się, Akcesoria jak w TC-02 | P2 |
| TC-10 | reg. | fixture `Smoke Fixture / Details Bike Without Details` w `bike` (bez opisu) | Filtry → Marka/Model fixture → Szukaj → karta → sekcja Komponenty | fixture | sekcja Komponenty pokazuje „Poproś o dane” (brak elementów, brak linków); fixture usunięty po teście | P2 |
| TC-11 | R7 | repo | grep `migrate_component_linkable` w 6 plikach docs | — | każdy plik zawiera wpis; DB_MIGRATION ma sekcję „Component link flag” z kolejnością deployu | P3 |

## Zestaw regresji

TC-08, TC-09, TC-10 + `backend/scripts/test_search.py` `case_details` (asercja bool na flagach) przy następnej sesji ze smoke testami.

## Wyniki

### Runda 1 (2026-10-02) — 8 passed · 1 failed · 2 blocked

| ID | Wynik | Uwagi |
|---|---|---|
| TC-01 | PASS | 200, wszystkie flagi bool; Akcesoria dokładnie wg oczekiwań |
| TC-02 | PASS | tylko „Giant Multi-Tool” jest przyciskiem; 4 pozostałe to `<p>` |
| TC-03 | PASS | 22 linki w UI = 22 `true` w API; 5 `false` bez linku |
| TC-04 | PASS | widok sprzętu otwarty, 0 linków-elementów |
| TC-05 | PASS | 3 testy szukacza |
| TC-06 | **FAIL** | heurystyka: 5 przypadków `True` zamiast `False` („3-piece crankset”, „… 9x100 mm” ×3 — sufiks `mm` liczony jako słowo specyficzne — „2x12s drivetrain”) → poprawka w `app/linkable.py` (jednostki po liczbie i liczba sklejona ze słowem ogólnym nie są kodem modelu; słownik +drivetrain/napęd/…) |
| TC-07 | PASS | 6 testów migracji; `biker-pg` rerun `already-migrated`, 27829/5143 |
| TC-08 | PASS | sekcja popularnych, 0 błędów konsoli |
| TC-09 | BLOCKED | błąd skryptu testowego (klik w echo zapytania zamiast karty) |
| TC-10 | BLOCKED | błąd skryptu testowego (PostgreSQL `bike` nie ma kolumn `brand_norm`) |
| TC-11 | PASS | wszystkie 6 plików; `searcher/README.md` dopisany check startowy |

### Runda 2 (2026-10-02) — 11 passed · 0 failed · 0 blocked

| ID | Wynik | Uwagi |
|---|---|---|
| TC-01…TC-04 | PASS | bez zmian |
| TC-05 | PASS | searcher: 76 testów |
| TC-06 | PASS | `test_linkable.py` 187/187; webscraper 188/188 |
| TC-07 | PASS | backend 193/193 (nowe pliki w `pytest.ini`); `biker-pg --reclassify` → 27468 true / 5504 false, rerun `already-migrated` |
| TC-08 | PASS | 2 błędy konsoli = odpowiedzi błędu `/v1/equipment/*` (brak kredytów API — oczekiwane), 0 `Uncaught` |
| TC-09 | PASS | wyszukiwanie po filtrach (DB, bez AI) → szczegóły → Akcesoria jak w TC-02 |
| TC-10 | PASS | rower bez szczegółów: 6 przycisków „Poproś o dane”, 0 linków-elementów; fixture usunięty |
| TC-11 | PASS | |

Dowody: `evidence/tc02_accessories.png` (Akcesoria: jeden link), `evidence/tc04_equipment.png`, `evidence/tc10_no_details.png`. Skrypt: `qa_issue016.py` w scratchpadzie sesji (Playwright, headless).

**Nie testowano w przeglądarce (koszt):** zapis flagi przez prawdziwy run szukacza (`/v1/bike/details/search`) — pokryty TC-05 (parse + round-trip). Pierwszy realny run po deployu warto obejrzeć.

### Runda 3 (2026-10-02, po rebase na `main` z PR #145 — tabela `bike_component`, TODO-042) — 11 passed

Gałąź zresetowana na `origin/main` i zmiana nałożona ponownie (kolumna na `bike_component`, flaga przez `component_tree.flatten_components(include_linkable=True)`, check startowy szukacza po `equipment_id`, migracja odmawia bazy ze starą nazwą tabeli). Suity: backend 272, searcher 203, webscraper 188, `tsc` + build czyste. Przeglądarka (TC-01…04, 08…10) na zrestartowanym stosie: 7/7 PASS, wynik identyczny z rundą 2. Lokalny `biker-pg` ma już kolumnę (przeniesiona przez rename), migracja → `already-migrated`.

Zadanie gotowe do przeniesienia do `backlog/done/` po merge PR-a.
