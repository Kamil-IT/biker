# TODO-044 — Scalenie `equipment_detail` z `equipment`

**Branch:** `refactor/merge-equipment-detail`
**Worktree:** `C:\Users\kamil_wolny\Projects\biker-wt\refactor-merge-equipment-detail`
**Status:** DONE — merged in PR #149 (92394ac, 2026-10-02); Cloud SQL migrated and deployed the same day (backend `biker-backend-00017-8vb`, searcher `biker-searcher-00010-dkq`, frontend `biker-frontend-00012-m56`)

## Cel (trzy punkty)

1. Scalić tabele `equipment` i `equipment_detail`; zostaje nazwa `equipment` (tak jak PR #137 zrobił to dla `bike_detail` → `bike`).
2. `equipment_detail_component` → `equipment_component` (klucz `equipment_id`, `ON DELETE CASCADE`, `NOT NULL`, indeks).
3. Kolumna `company` wiersza wyposażenia była pusta, bo jedynym źródłem wiersza jest klik w nazwę elementu drzewa roweru
   (frontend wysyła company `""` i model = nazwa elementu). Zakończone wyszukiwanie szczegółów w searcherze ma uzupełniać
   brakujące `company` / `model`.

## Decyzje

- **Kolumna `name` / `name_norm`** (nazwa elementu z drzewa roweru, norma w Pythonie, nigdy SQL `lower()`) jest kluczem
  wyszukiwania; unikalność `UNIQUE(category, name_norm)` = `uq_equipment_name`, a `uq_equipment_identity` znika — dwie różne
  nazwy elementów mogą po researchu wskazać tę samą markę i model i nie mogą się zderzyć.
- **`company` / `model`** to teraz marka i model ustalone przez wyszukiwanie: `""` i nazwa, dopóki wyszukiwanie ich nie uzupełni.
- **Reguła „uzupełnij tylko brakujące”** (`save_equipment_details` w searcherze): `company` ustawiane, gdy zapisane jest `""`;
  `model` ustawiany, gdy zapisany jest pusty albo równy nazwie. Zapisana wartość nigdy nie jest nadpisywana, a `""` z wyniku się nie
  liczy. Zapis zdjęć nie rusza `company` / `model`.
- Wynik wyszukiwania (schemat JSON, prompt `equipment_details.md`) dostaje wymagane `company` i `model` (model bez marki, `""` gdy
  nieznane). Schemat roweru bez zmian — wyposażenie ma własną kopię `EQUIPMENT_DETAILS_SCHEMA`.
- **Brak backfillu przez AI** — istniejące wiersze dostają `company` / `model` przy następnym wyszukiwaniu szczegółów.
- `description` jest `NULL`, gdy wyposażenie nie ma szczegółów (np. same zdjęcia): „ma szczegóły” = `description IS NOT NULL`.
- Odczyt po nazwie (bez `equipment_id`): `name_norm == norm(model)` przy pustym company; z company — para (company_norm, model_norm)
  albo `name_norm` z „company model”. Najstarszy id wygrywa, kategoria ignorowana. Frontend bez zmian (otwiera widok po nazwie elementu
  lub po `equipment_id`, nie zakłada `response.model == nazwa`).

## Migracja i kolejność wdrożenia

`backend/scripts/migrate_merge_equipment_detail.py` (`--dry-run`, `--db`, `--url`, `migrate(...) -> dict`): jedna transakcja, orphany
komponentów do `equipment_component_orphans`, weryfikacja przed commitem, `migrated` / `already-migrated` / `repaired` / `dry-run` /
`absent` / `failed`. Stary backend po migracji odtwarza puste `equipment_detail*` przez `create_all()` — ponowne uruchomienie je usuwa
(`repaired`). Searcher nie wstanie na niezmigrowanej bazie.

Kolejność: po `migrate_equipment_tables.py`, `migrate_drop_bike_detail.py`, `migrate_rename_bike_component.py`.
Produkcja (tylko na wyraźne „go” użytkownika): backup Cloud SQL → migracja przez proxy → backend + searcher razem → frontend.
Gałąź PostgreSQL wzorowana na `migrate_drop_bike_detail.py`, ale testy działają tylko na SQLite — przed produkcją przećwiczyć na kopii PostgreSQL.

## Plan testów

- `backend/scripts/test_migrate_merge_equipment_detail.py` — stary układ → nowy, orphany, idempotencja, `repaired`, dry-run, kolizja nazw,
  ORM po migracji.
- `backend/scripts/test_equipment_repository.py` — nazwa jako tożsamość, uzupełnianie company/model, brak nadpisywania, odczyt po nazwie
  po uzupełnieniu, zdjęcia nie ruszają company/model.
- `searcher/scripts/test_equipment_searcher.py` — parsowanie `company` / `model`, zapis uzupełnia brakujące, schemat, `init_db()`.
- `backend/scripts/test_search.py` — fixtury smoke (wymaga działającego serwera i zmigrowanej bazy).
