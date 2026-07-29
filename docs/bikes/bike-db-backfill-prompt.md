# Prompt — backfill bike details into `backend/cache.db` (22-agent fan-out)

Paste the block below into Claude Code (repo root `C:\Users\kamil_wolny\Projects\biker`).
Change only the **Batch** line at the top.

Topology: **20 web-search researchers → 1 coordinator → 1 DB writer.** The coordinator is
the only hub; no two agents ever talk to each other directly.

```
researcher-01 ─┐
researcher-02 ─┤
      …        ├──► coordinator ◄──► db-writer
researcher-19 ─┤        ▲
researcher-20 ─┘        │
                      lead (you)
```

---

## PROMPT

You are the **lead**. You are backfilling the SQLite database `backend/cache.db` with real
bike specification data, using the brand/model spine in `docs/bike-brands-models.json`, by
orchestrating a 22-agent swarm.

**Batch:** process `N = 100` models, brand filter = `<none>` (set a brand name to restrict).

### Source of truth

- Model list: `docs/bike-brands-models.json` → `models[]`, each row
  `{ brand, model, year, url, source, confidence, ref, price, currency, ... }`.
  Documented in `docs/README-bike-dataset.md`.
- Component JSON shape: `backend/app/prompts/bike_details.md` — **follow it exactly**.
- Target tables: `bike`, `bike_detail`, `bike_detail_component`, `bike_detail_photos`
  (ORM in `backend/app/models.py`, writer in `backend/app/repository.py`).

---

## 1. Agent roster

Spawn **all 22 agents in ONE message**, each with `run_in_background: true` and an explicit
`name` — the name is what makes an agent addressable via `SendMessage`. Load the messaging
tool first: `ToolSearch("select:SendMessage")`.

| Name | Count | subagent_type | Role |
|---|---:|---|---|
| `coordinator` | 1 | `hierarchical-coordinator` | Hub. Owns the work queue, validates every payload, routes all traffic, tracks the whole flow, produces the final report. |
| `researcher-01` … `researcher-20` | 20 | `researcher` | Web-search only. Given a shard of bikes, find real specs, emit the `bike_details.md` JSON. **No DB access whatsoever.** |
| `db-writer` | 1 | `backend-dev` | Sole writer. Owns `backend/cache.db`. Consumes validated payloads from the coordinator, inserts via `repository.save_bike_details`, verifies each row, reports back. |

Why exactly one writer: SQLite takes a **database-level** write lock. Twenty concurrent
writers would serialise into `database is locked` errors, not parallel throughput. The
researchers are the parallel part; the write is deliberately a funnel.

---

## 2. Communication protocol — coordinator-mediated, JSON only

**Hard rule: every message passes through `coordinator`.** A researcher never messages
`db-writer`; `db-writer` never messages a researcher; researchers never message each other.
Any agent that needs something from another agent asks the coordinator, and the coordinator
relays. The coordinator is a participant in **100 % of traffic** — that is what lets it
analyse the flow and rebalance work.

Every `SendMessage` body is the literal line `MSG <TYPE>`, a newline, then **one JSON
object and nothing else** — no other prose before or after:

```
MSG ASSIGN
{"msg_id":"c-0001", …}
```

**That prefix line is mandatory, not decoration.** `SendMessage` parses a body that is a
bare JSON object and rejects it against its own internal `type` discriminators
(`shutdown_request`, `plan_approval_response`, …), so an unprefixed envelope fails with
`InputValidationError` and never reaches the recipient. The prefix keeps the body a string.
Observed directly on the trial run's kickoff message, which failed twice before the prefix
was added.

**Do not blame this for a silent round.** A rejected send fails loudly and immediately. If
messages return `success: true` and the recipients still produce nothing, the envelope is
not your problem — look at the start-work directive in §3.

Envelope:

```json
{
  "msg_id": "r07-0003",
  "ts": "2026-07-28T10:14:02Z",
  "from": "researcher-07",
  "to": "coordinator",
  "reply_to": "c-0021",
  "type": "RESULT",
  "payload": { }
}
```

- `msg_id` — unique per sender: `<agent-slug>-<seq>`, seq zero-padded to 4.
- `reply_to` — the `msg_id` this answers, or `null` for an unsolicited message.
- `to` — always `"coordinator"` for researchers and `db-writer`. The coordinator may
  address any agent by name.
- `type` — one of the message types below. Unknown types are an error, not a guess.

### Message types

| `type` | Direction | `payload` |
|---|---|---|
| `ASSIGN` | coordinator → researcher | `{ "shard_id": int, "start_now": true, "bikes": [{ "brand", "model", "year", "url", "source", "ref" }] }` |
| `PROGRESS` | researcher → coordinator | `{ "shard_id", "done": int, "total": int, "current": "brand model" }` |
| `RESULT` | researcher → coordinator | `{ "brand", "model", "source_urls": [str], "spec_file": "path", "categories": int, "spec_rows": int, "photos": int, "description_chars": int, "confidence": "high"\|"medium" }` |
| `SKIP` | researcher → coordinator | `{ "brand", "model", "reason": "no_source"\|"not_a_bike"\|"duplicate"\|"blocked" , "detail": str }` |
| `WRITE_REQUEST` | coordinator → db-writer | the validated `RESULT` payload, plus `"batch_seq": int` |
| `WRITE_ACK` | db-writer → coordinator | `{ "brand", "model", "status": "stored"\|"skipped_fresh"\|"failed", "verified": bool, "db_rows": { "bike_detail_component": int, "bike_detail_photos": int }, "error": str\|null }` |
| `QUERY` | any → coordinator | `{ "question": str, "about": str }` — e.g. a researcher asking whether a near-duplicate model is already claimed |
| `RELAY` | coordinator → any | `{ "origin": "<agent>", "question": str, "context": obj }` — how the coordinator forwards a `QUERY` on someone's behalf |
| `ANSWER` | any → coordinator | `{ "reply_to_query": "msg_id", "answer": str, "data": obj\|null }` |
| `STATUS_REQ` | coordinator → any | `{}` |
| `STATUS` | any → coordinator | `{ "state": "idle"\|"working"\|"blocked"\|"done", "shard_id": int\|null, "done": int, "total": int, "note": str }` |
| `SHARD_DONE` | researcher → coordinator | `{ "shard_id", "results": int, "skips": int }` |
| `SHUTDOWN` | coordinator → any | `{ "reason": str }` |

**Payloads never carry the full component tree.** A 200-spec bike inside a chat message
would blow up the coordinator's context twenty times over. Instead each researcher writes
its bike JSON to a spool file and the `RESULT` message carries only the **path plus
counts** (`spec_file`). The coordinator validates the file on disk; `db-writer` reads it
from disk.

### Spool directory

```
backend/scratch/backfill/
  inbox/<brand-slug>__<model-slug>.json   ← researcher writes, coordinator validates, db-writer reads
  done/<brand-slug>__<model-slug>.json    ← db-writer moves it here after a verified insert
  failed/<brand-slug>__<model-slug>.json  ← db-writer moves it here on failure, with an .error.txt beside it
```

Slug = lowercase, non-alphanumerics → `-`, collapsed. Each spool file:

```json
{
  "brand": "State Bicycle Co.",
  "model": "4130 All-Road",
  "description": "4-5 sentence plain-text overview…",
  "photos": ["https://…", "…"],
  "components": [ /* the bike_details.md array, verbatim */ ],
  "source_urls": ["https://…"],
  "researched_by": "researcher-07",
  "researched_at": "2026-07-28T10:14:02Z"
}
```

---

## 3. Lead — startup sequence

1. `ToolSearch("select:SendMessage")`.
2. Create the spool dirs; back up the DB: `copy backend\cache.db backend\cache.db.bak`.
3. Read `docs/bike-brands-models.json`, apply the **selection rules** (§4), take `N` rows.
4. Split into **20 shards**, round-robin by index so no single shard is all one brand
   (same-brand bikes share sources and would serialise one researcher's lookups).
5. Spawn all 22 agents in one message, `run_in_background: true`, each prompt containing:
   its own name, the protocol above verbatim, and *who it may message* (answer: only
   `coordinator`).

   **Never end a worker prompt with "wait for your ASSIGN / do nothing until it arrives."**
   A background agent with nothing to do completes as idle, and the `ASSIGN` then lands in
   a transcript that has already decided it is finished — the send succeeds, the work never
   starts, and the agent reports nothing at all. This killed the entire first trial round:
   all five `ASSIGN`s returned `success: true` and produced zero spool files. Instead give
   each researcher its shard **in the spawn prompt** and tell it to begin immediately, or
   have the coordinator's `ASSIGN` carry `"start_now": true` meaning *this message is the
   work order, act on it in this turn*. The `db-writer` is the exception that proves it:
   its job on receipt is to reply, which is itself a messaging action, so it woke correctly
   where the researchers did not.
6. Kick off with a single `SendMessage` to `coordinator` carrying the shard plan as JSON.
7. **Then stop and report to the user what is running.** Do not poll. The coordinator
   reports in when the batch is done or when it needs a decision.

---

## 4. Selection rules (lead applies before sharding)

From `models[]`, take the first `N` rows satisfying **all** of:

1. `confidence != "low"` — low-confidence rows are framesets/kits, not complete bikes.
2. `model` is non-empty and is not obviously a part/apparel item. `confidence: "high"` is
   **not** sufficient — plenty of high-confidence rows are framesets, mudguards and
   frame+shock packages. Filter the model name against a part/frameset regex covering at
   least: `frame`, `wheel`, `fork`, `shock`, `kit`, `attachment`, `bar`, `stem`,
   `seatpost`, `saddle`, `pedal`, `tyre/tire`, `bag`, `rack`, plus apparel; and drop names
   containing `&` or a trailing `+`, which mark frame+component bundles.
3. Not already stored: `repository.get_bike_details(brand, model)` returns `None`.
   (Lookup is exact and case-sensitive — pass the dataset's own casing verbatim.)
4. Cap at **2 models per brand**. `models[]` is alphabetically clustered, so an unfiltered
   head-of-list take is a handful of brands deep — one researcher then holds a whole
   brand's lookups and serialises on the same source pages.

Preserve the dataset casing of `brand` and `model` — those two strings become
`bike.brand` / `bike.model` and are the display casing everywhere in the app.

---

## 5. Researcher agents (×20) — instructions to embed in each prompt

You are `researcher-NN`. You do **web research only**. You never open `cache.db`, never
import `app.repository`, never write SQL. You message **only** `coordinator`, and every
message you send is a single JSON object per the protocol.

On `ASSIGN`, for each bike in your shard:

1. Research the real specification of that exact bike. Prefer, in order: the row's own
   `url` (manufacturer / storefront product page), the manufacturer's spec sheet, a
   reputable review with a full spec table. **Never invent a component.**
2. Convert the raw spec text into the JSON array defined by
   `backend/app/prompts/bike_details.md`. Non-negotiable points from that file:
   - Top level is a **JSON array of category objects**:
     `{"category", "subcategories": [{"subcategory", "elements": [{"name", "description", "specs": [{"key","value"}]}]}]}`
   - Emit the eight categories in this order, omitting a *subcategory* only when the bike
     genuinely lacks that part:
     `Frame` (Frame, Fork, Seatpost Clamp) · `Drivetrain` (Rear Derailleur, Cassette,
     Crank, Bottom Bracket, Chain, + Front Derailleur if fitted) · `Brakes` (Brake Lever
     Front, Brake Lever Rear, Brake Rotor) · `Wheels` (Front Wheel, Rear Wheel, Tyres,
     Thru Axle Front, Thru Axle Rear) · `Cockpit` (Handlebar / Stem, Bar Tape) ·
     `Saddle & Seatpost` (Saddle, Seatpost) · `Lighting` (Reflectors) ·
     `Accessories` (Tool, Pedals, Included Items)
   - Any value you could not find is `""` — never `null`, never a guess, never "N/A".
   - `specs: []` is legitimate when an element has no published specs.
3. Write a 4–5 sentence plain-text overview (what it is for, frame material, drivetrain
   highlight, who it suits).
4. Collect up to 8 product image URLs from the manufacturer/product page if directly
   available; otherwise `[]`. Do not fabricate image URLs.
5. Write the spool file to `backend/scratch/backfill/inbox/<slug>.json`, then send one
   `RESULT` message with the path and counts.

**A spool file that has vanished from `inbox/` means success, not loss.** `db-writer` moves
each file to `done/` once it is stored and verified. Never re-check your own files, and
never rewrite one you cannot find — you would be re-researching a bike that is already in
the database. On the trial run this caught two of five researchers independently, so treat
it as the default expectation rather than an edge case.

If no trustworthy spec source exists for a bike, send `SKIP` with `reason: "no_source"` and
move on. A partly-empty row is fine; a fabricated one is not. Send `PROGRESS` every 3 bikes
and `SHARD_DONE` at the end. If you need to know something another agent holds, send
`QUERY` to `coordinator` — never contact that agent yourself.

---

## 6. `db-writer` — instructions to embed in its prompt

You are `db-writer`, the **only** agent permitted to touch `backend/cache.db`. You message
only `coordinator`. You act solely on `WRITE_REQUEST`; you never read the spool `inbox/`
speculatively and you never accept work from a researcher.

Do **not** hand-write SQL. Go through the ORM writer so the flattening, ordering and
cascade behaviour stay identical to the live `/v1/bike/details` path
(`repository.save_bike_details` writes `bike` → `bike_detail` → `bike_detail_component`
one row per spec, `component_order`/`element_order`/`spec_order` preserving order → and
`bike_detail_photos` ordered by `display_order`).

Run from `backend/` with the venv active (`.venv\Scripts\activate`):

```python
# backend/scripts/backfill_details.py  (create if missing; keep it re-runnable)
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import init_db
from app.repository import get_bike_details, save_bike_details
from app.schemas import (
    BikeDetailsResponse, BikeDescription,
    BikeCategory, BikeSubcategory, ComponentElement, SpecItem,
)

init_db()  # no-op on an existing cache.db

def store_spool(spool_path: str) -> dict:
    """Insert one researcher spool file. Returns the WRITE_ACK payload."""
    doc = json.loads(Path(spool_path).read_text(encoding="utf-8"))
    brand, model = doc["brand"], doc["model"]

    if get_bike_details(brand, model) is not None:
        return {"brand": brand, "model": model, "status": "skipped_fresh",
                "verified": True, "db_rows": {}, "error": None}

    resp = BikeDetailsResponse(
        company=brand,
        model=model,
        description=BikeDescription(text=doc["description"], segments=[], citations=[]),
        components=[
            BikeCategory(
                category=c["category"],
                subcategories=[
                    BikeSubcategory(
                        subcategory=s["subcategory"],
                        elements=[
                            ComponentElement(
                                name=e.get("name", ""),
                                description=e.get("description", ""),
                                specs=[SpecItem(key=sp.get("key", ""), value=sp.get("value", ""))
                                       for sp in e.get("specs", [])],
                            ) for e in s.get("elements", [])
                        ],
                    ) for s in c.get("subcategories", [])
                ],
            ) for c in doc["components"]
        ],
        photos=doc.get("photos", []),
    )
    save_bike_details(brand, model, resp)

    # save_bike_details swallows its own exceptions (logs a warning, rolls back),
    # so a successful return proves nothing — read it back instead.
    check = get_bike_details(brand, model)
    ok = check is not None and bool(check.components)
    return {
        "brand": brand, "model": model,
        "status": "stored" if ok else "failed",
        "verified": ok,
        "db_rows": {
            "bike_detail_component": sum(len(e.specs) or 1
                                         for c in (check.components if ok else [])
                                         for s in c.subcategories for e in s.elements),
            "bike_detail_photos": len(check.photos) if ok else 0,
        },
        "error": None if ok else "read-back failed after save_bike_details",
    }
```

Process `WRITE_REQUEST`s **strictly one at a time, in arrival order** — no concurrency, no
batching into a single transaction. Note for the coordinator: the constraint is *serial
writes*, not *serial messaging*. `WRITE_ACK`s can arrive well after the write itself has
landed, so a coordinator that blocks on each ACK before sending the next `WRITE_REQUEST`
will stall a full queue behind mailbox latency. Confirm a write by querying the DB and keep
feeding the writer an ordered manifest — one file at a time with read-back between each is
what the SQLite lock actually requires. After each: move the spool file to `done/` or
`failed/` (writing `<slug>.error.txt` beside a failure), then send exactly one `WRITE_ACK`
to `coordinator`. If three consecutive writes fail, stop and send a `STATUS` with
`state: "blocked"` rather than burning through the queue.

---

## 7. `coordinator` — instructions to embed in its prompt

You are `coordinator`. You are the hub: **every message in this system passes through
you**, and you originate all routing. You never do web research and you never write to the
database — you assign, validate, relay, and analyse.

Responsibilities:

1. **Dispatch.** On the lead's shard plan, send one `ASSIGN` per researcher (20 total).
   Hold back nothing — all 20 start at once.
2. **Validate every `RESULT` before it reaches `db-writer`.** Reject and re-assign if:
   - the spool file is missing or is not valid JSON;
   - `components` is not a JSON **array** of category objects;
   - fewer than 3 of the 8 required categories are present;
   - any spec value is `null`, `"N/A"`, `"unknown"`, or `"TBD"` (the contract is `""`);
   - `source_urls` is empty (an unsourced spec is a fabricated spec);
   - `brand`/`model` casing does not match the dataset row verbatim.
   On rejection send a fresh `ASSIGN` for that single bike to the **least-loaded**
   researcher, with the rejection reason in the payload. Re-assign at most twice, then
   record it as a permanent skip.
3. **Serialise the write path.** Forward validated results to `db-writer` one
   `WRITE_REQUEST` at a time, waiting for each `WRITE_ACK` before sending the next. Keep
   the backlog in an in-memory queue. This is the only correct way to feed one writer from
   twenty producers.
4. **Relay.** Any `QUERY` you receive gets answered by you if you know the answer, or
   forwarded as a `RELAY` to whoever does. The origin agent's identity travels in the
   payload. Never introduce two agents to each other — the answer comes back to you as an
   `ANSWER` and you pass it on.
5. **Analyse the flow.** Maintain a live tally: per-researcher throughput, skip reasons by
   category, validation-rejection rate, write success rate, spool-directory counts. Watch
   for the two failure modes that matter here — a researcher stuck on one bike (no
   `PROGRESS` across several other agents' updates) and a rising `no_source` rate, which
   means the shard is full of dataset rows that are not real complete bikes. Rebalance by
   re-assigning pending bikes from a stalled researcher to an idle one; send `STATUS_REQ`
   before concluding an agent is stuck.
6. **Report.** When every shard is `SHARD_DONE` and the write queue is empty, send
   `SHUTDOWN` to all workers, then report to the lead:
   - the table `brand | model | researcher | source url used | categories | spec rows | photos | status`
   - totals: assigned / researched / skipped (by reason) / rejected in validation / stored / failed
   - per-researcher throughput and anything you rebalanced
   - before/after DB counts:

```bash
python -c "import sqlite3;c=sqlite3.connect('cache.db');print({t:c.execute(f'select count(*) from {t}').fetchone()[0] for t in ('bike','bike_detail','bike_detail_component','bike_detail_photos')})"
```

---

## 8. Hard rules (all agents)

- Never fabricate component names, spec values, or photo URLs — `""` / `[]` instead.
- Never write to `bike_detail_component` or `bike_detail_photos` directly; go via
  `repository.save_bike_details`, and only from `db-writer`.
- **Only `db-writer` opens the database.** A researcher touching `cache.db` is a protocol
  violation — report it to the coordinator.
- **No direct agent-to-agent messages.** Everything routes through `coordinator`.
- **Every message is one JSON object**, no surrounding prose, matching the envelope above.
- Re-running the batch must be safe: an existing fresh row is skipped, never duplicated
  (`bike` has `UNIQUE(brand, model)`; re-saving deletes and rebuilds the detail subtree).
- Do not touch `search_cache`, `search_bike_rating_cache`, `bike_offer*`, or
  `endpoint_req_to_body_cache`.

## END PROMPT

---

## Notes

- `backend/cache.db` is the live DB (`models.get_engine()` → `backend/cache.db`). The
  backup step in §3 is not optional at 20-agent scale.
- `bike_detail.description` stores `BikeDescription` as JSON (`text` / `segments` /
  `citations`); `segments` and `citations` may be empty — the frontend renders `text`.
- Dataset coverage is skewed: Trek, Giant, Cube, Canyon and Merida are **absent**, so a
  brand-filtered run against those returns nothing. The 91 brands that carry models are
  mostly direct-to-consumer (Specialized, Salsa, State Bicycle, Lectric, …).
- Sizing: 20 researchers only pay off when `N` is well above 20 — at `N = 100` each shard
  is 5 bikes. For a quick 10-bike run, use the single-agent path instead; the coordination
  overhead exceeds the work.
- The spool directory is what makes this restartable. If the swarm dies mid-run, `inbox/`
  holds researched-but-unwritten bikes and `db-writer` can be re-run over it alone.
- **Tell researchers that a vanished `inbox/` file means success**, not loss (now stated in
  §5). `db-writer` moves consumed files to `done/`; on the trial run two of five
  researchers re-checked, found their file "missing" and rewrote it. Nothing was
  double-ingested (an existing row returns `skipped_fresh`), but it wastes a round trip and
  gets more common at 20-researcher scale.
- **Reconcile `inbox/` against `done/` before finishing a run.** A rewritten duplicate that
  the coordinator knows to be already-stored is marked do-not-write *in coordinator state
  only, not on disk* — so the next run's coordinator scans `inbox/*.json`, sees it as new
  work, and forces a needless delete-and-rebuild of a healthy detail subtree. Rename
  consumed duplicates to `*.json.superseded` (content preserved, invisible to a `*.json`
  scan) or have `db-writer` delete them outright.

### Trial-run results (2026-07-28, N = 20, 5 researchers)

19 of 20 stored and verified, 0 write failures, 0 validation rejections, 1 honest
`no_source` skip (Bike Friday Tikit — discontinued built-to-order, no model-level spec).
DB 73 → 92 `bike`, 12 → 31 `bike_detail`, 678 → 1544 `bike_detail_component`,
56 → 96 `bike_detail_photos`. ~7 minutes end to end.

Two caveats for anyone reading that as a green light:

- **The validation/re-assign path never fired** — all 19 files passed first time. It is
  therefore still untested. Do not assume it works.
- **`confidence: "high"` wikidata rows with no component data are usable.** Five of six
  became full 8-category entries because researchers treated the row as an identifier and
  went to find a real spec page. Only one became a skip.
- `backend/scratch/` should be gitignored — check before the first run.
