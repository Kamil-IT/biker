---
name: discovery-import
description: Import the pending bike_discovery bikes (centrumrowerowe.pl) straight into GCP Cloud SQL and fill every gap (offer, Haiku short description, photos, details, review), stopping at the user's subscription limits, then verify that everything landed
usage: Use when asked to continue / resume / run the bike-discovery import into production, or to check how many discovered bikes are imported and how many are left
---

# Discovery import into Cloud SQL

Repeats the 2026-10-02 import session. Scripts live in `webscraper/centrumrowerowe/`
(`enrich.py`, `verify_discovery.py`, `run_loop.sh`; details in that folder's `README.md` §§ 5–6).
Talk to the user in Polish.

## Decisions already made by the user (do not re-ask)

- Insert **straight into GCP Cloud SQL** — no local run + `copy_to_db.py`.
- Batches of **5** bikes.
- AI **only when something is missing**:
  - category → `bike.category` from the discovery `bike_type` (Polish shop type → English category via
    `backend/app/bike_categories.py`, e.g. `trekkingowy` → `Trekking`), **no AI**, only while NULL, never
    overwritten. `process_queue.py` sets it for newly processed bikes, `enrich.py` (step `category`) fills
    the bikes processed before; an unmapped type stays NULL — report it, don't guess a category.
  - offer = each centrumrowerowe listing → `bike_offer` (`source='centrumrowerowe.pl'`, `is_new` true,
    price `1 099 zł`), **no AI**. Shown in the "Nowe" card via `POST /v1/bike/centrumrowerowe` (PR #151).
  - photos → `/v1/bike/photos/search`, only when the bike has none.
  - details → `/v1/bike/details/search`, only when the description text or the components are missing.
  - `short_description` → **Haiku** via `claude -p --model haiku` (subscription), only while empty.
  - review → `/v1/bike/review/search`, only when there is no `bike_review` row.
  - Paid searches go through the **deployed backend** (`https://biker-backend-ggkzq7ysyq-lm.a.run.app`).
- Stop at **80 % of the 5 h window** or **85 % of the 7-day window** — whichever comes first.
  "Finish only what started" — never leave a half-written bike.
- Skip the 55 bikes done/skipped before 2026-10-02: always pass `--since 2026-10-02T12:00`.

## Steps

1. **Status first** (read-only) — tell the user in numbers:
   - subscription usage (5 h / 7 d % and reset times):
     `python -c "import enrich; print(enrich.Guard(101,101)._read())"`
     (from `webscraper/centrumrowerowe`, retries a 429 by itself);
   - queue: `select status, count(*) from bike_discovery group by 1`;
   - categories: `select b.category, count(*) from bike_discovery d join bike b on b.id = d.bike_id group by 1`
     (NULL = still to fill or unmapped `bike_type`);
   - how many are imported vs left.

   Estimate the throughput: ~135 bikes use ~71 points of the 5 h window and ~5 points of the 7-day window.
   If the 7-day headroom is small, say so before starting.
2. **Prerequisites**:
   - the Cloud SQL proxy listens on 6543 (`netstat -ano | grep ":6543 "`); otherwise ask the user to run
     `cloud-sql-proxy --gcloud-auth --port 6543 biker-engine-prod:europe-central2:biker-pg`;
   - env `PYTHONUTF8=1`,
     `DATABASE_URL=postgresql+psycopg://biker@127.0.0.1:6543/biker`
     (the env var wins over `backend/.env`),
     `PGPASSFILE=<repo>\backend\gcp-prod-pgpass.conf`;
   - every write needs `--allow-remote`.
3. **Run** — start the loop as a detached process (it does not depend on the session shell):
   `Start-Process "C:\Program Files\Git\usr\bin\bash.exe" -ArgumentList "-l","/c/Users/kamil_wolny/Projects/biker/webscraper/centrumrowerowe/run_loop.sh" -WindowStyle Hidden -PassThru`.
   - Each round runs `enrich.py --allow-remote --batch 5 --since 2026-10-02T12:00`.
   - A 5 h stop waits for the window to reset, then continues.
   - A 7-day stop, an empty queue or any other stop ends the loop; `verify_discovery.py` then runs once.
   - Everything is logged to `runs/loop.log`.
4. **Watch** with `Monitor` on `runs/loop.log`, with a narrow filter:
   `^LOOP|STOP|Traceback|failed \||lost \||ERROR=`. Usage lines are too noisy.
   Re-arm the monitor when it expires. For progress, count `INFO done |` and `enriched |` lines.
5. **Verify** (read-only), and always after a stop:
   `verify_discovery.py --allow-remote --since 2026-10-02T12:00 --recheck 20`.
   - Exit 1 on any ERROR; `queue.open` errors only mean bikes are still pending.
   - Report per bike type: description/components/photos, offer, category, short description, review (found / nothing found).
   - `bike.category` ERROR = NULL although the type maps (rerun enrich); WARN = unmapped `bike_type` —
     list those types for the user (adding them belongs in `bike_categories.py`, not in this run).
   - Also report how many of the 20 rechecked bikes matched the shop page 1:1.
6. **If the user says stop**:
   1. Kill the bash `run_loop.sh` processes first, so no new round starts.
   2. Let `enrich.py` finish the batch it is enriching, then kill it before it claims the next one.
   3. Check that no `bike_discovery` row is `in_progress` (otherwise release it: `pending`, `attempts - 1`, `locked_at` NULL).
   4. Add the free offers for bikes that are queue-done but not yet enriched:
      `enrich.store_offers(bike_id, discovery_id)`.
   5. Leave the paid gaps; the next run fills them from the DB.
7. Finish with the numbers (imported / left / gaps), the usage, and when the next window allows a resume.

## Gotchas learned

- `bike.category` needs `backend/scripts/migrate_bike_category.py` on the target database first (PR #158;
  its Cezar run reported the Cloud SQL step done 2026-10-06, column + backfill from `bike_discovery`).
  Without the column the ORM fails on the first bike. Check before a run:
  `backend\.venv\Scripts\python.exe backend\scripts\migrate_bike_category.py --url <Cloud SQL url> --dry-run`
  (`already-migrated` = fine; `backfilled`/`dry-run` = it would still fill rows — harmless, `enrich.py` does the same).

- `db.py` loads `backend/.env`, which carries an `ANTHROPIC_API_KEY` without credits.
  The Haiku call must drop it from the CLI env, or it fails with "Credit balance is too low".
  `enrich.py` already does this.
- `api.anthropic.com/api/oauth/usage` rate-limits (429). `enrich.py` reads it at most once a minute,
  retries with Retry-After, and keeps a reading for up to 5 min. Don't add your own polling of that endpoint while the loop runs.
- The searcher stores a review only when `ref` is non-empty **and** `sources_used >= 1`.
  Anything else counts as "empty" and is recorded in `runs/enrich_attempts.json`, so it is not paid for again
  (`--retry-empty` overrides). About 2/3 of these cheaper bikes have no usable review — that is expected.
- Enrichment picks the lowest bike ids still missing something, so it can lag the queue by one batch.
- Prod writes may be refused by the permission classifier. If so, give the user the exact command to run with `!`.
- The 7-day window is shared with the user's own sessions — usage of this session counts too.
