# TODO-043 — Usunięcie tabel `search_cache` i `search_bike_rating_cache`

**Branch:** `feature/043-drop-search-cache-tables`
**Worktree:** `C:\Users\kamil_wolny\Projects\biker-wt\feature-043-drop-search-cache-tables` (backend 8001, frontend 5174, searcher 8101)
**Status:** TODO — implemented, waiting for QA + PR

## Skąd się wzięło (inwentaryzacja bazy, 2026-10-01)

Przegląd 15 tabel na Cloud SQL `biker-pg` wykazał dwie, do których od dawna nikt nie czyta:

| Tabela | GCP | lokalny `biker-pg` | `cache.db` | Kto pisał | Kto czytał |
|---|---|---|---|---|---|
| `search_cache` | 48 | 46 | 47 | `store.save_search` | nikt od TODO-024/025 |
| `search_bike_rating_cache` | 210 | 199 | 206 | `store.save_search` | nikt od TODO-024/025 |

Od TODO-041 kolumny `explanation` / `accessories` były zapisywane jako `""` / `"[]"`, a `rating`
zniknęło w TODO-040 — zostawał sam link wyszukiwanie → rower, którego nic nie używało.

## Zakres

1. **Aplikacja (backend):** modele `SearchCache` / `SearchBikeRating` usunięte z `app/models.py`;
   `store.save_search(query, bikes)` tylko dopilnowuje, że każdy znaleziony rower istnieje w `bike`
   (lookup przez `repository._find_bike_id`, nowy wiersz z casingiem z odpowiedzi AI); `SEARCH_TTL_SECONDS`
   usunięte; `init_store` zostaje jako hook startowy. Zapis do `bike` **zostaje** — `bike_exists` strzeże
   każdego wyszukiwania on-demand, a DB-first search potrzebuje wiersza.
2. **Migracja** `backend/scripts/migrate_drop_search_tables.py` — `DROP TABLE search_bike_rating_cache`
   (dziecko), potem `search_cache`; jedna transakcja na SQLite i PostgreSQL; liczba wierszy `bike`
   porównana przed i po (różnica = rollback, exit 1); idempotentna (`already-migrated`); `--dry-run`,
   `--db`, `--url`; importowalna `migrate(...) -> dict`. Skrypt `migrate_drop_search_rating.py`
   (TODO-040) usunięty — nie ma już tabeli, którą zmieniał.
3. **Trzy bazy:** lokalny `biker-pg` ✅ (199 + 46 wierszy, `bike` 723 bez zmian), `cache.db` ✅
   (206 + 47, `bike` 674), **Cloud SQL — do uruchomienia przez użytkownika** przez proxy po deployu
   backendu (klasyfikator blokuje Claude'owi dostęp do prod).
4. **Testy:** `test_details_repository.py` — `test_save_search_stores_bikes_only` +
   `test_migrate_drop_search_tables`; `test_search.py` i `test_e2e_ui_db.py` bez odwołań do tabel.
5. **Dokumentacja:** `CLAUDE.md`, `README.md`, `backend/README.md`, `backend/app/DB_MIGRATION.md`
   (§ Search tables dropped), `backend/app/DB_MODELS_SUMMARY.md`.

## Kolejność wdrożenia

Nowy backend nie dotyka tych tabel, więc: (1) deploy backendu, (2) drop na Cloud SQL przez proxy:

```
cloud-sql-proxy --gcloud-auth --port 6543 biker-engine-prod:europe-central2:biker-pg
cd backend
PGPASSFILE=gcp-prod-pgpass.conf python scripts/migrate_drop_search_tables.py --dry-run --url postgresql+psycopg://biker@127.0.0.1:6543/biker
PGPASSFILE=gcp-prod-pgpass.conf python scripts/migrate_drop_search_tables.py --url postgresql+psycopg://biker@127.0.0.1:6543/biker
```

Odwrotna kolejność też nie gubi danych: stary backend logowałby WARNING przy każdym wyszukiwaniu AI
(`save_search` rollback), odpowiedź i tak wraca.

## Kryteria akceptacji

- [ ] `POST /v1/bike/search` (DB hit i ścieżka AI) działa bez obu tabel; rower z odpowiedzi AI ląduje w `bike`
- [ ] widok szczegółów otwiera się z wyniku wyszukiwania (`bike_exists` → 200, nie 404)
- [ ] `migrate_drop_search_tables.py`: dry-run nic nie zapisuje, drop zachowuje `bike`, drugi run = no-op
- [ ] `pytest backend/scripts` zielone; `scripts/test_search.py` zielone na backendzie z worktree
- [ ] żadnych odwołań do `search_cache` / `search_bike_rating_cache` / `SEARCH_TTL_SECONDS` w `backend/app`
