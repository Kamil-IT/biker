# Backfill pipeline — workflow

Five small REST services plus Claude Code agents. **No Anthropic API key is used**
— every LLM step runs on the Claude Code subscription, as an agent that pulls a
work order over REST and posts raw output back. Everything deterministic
(queueing, prompt assembly, JSON extraction, Playwright scraping, validation,
the DB write) lives in the services, so it is testable and cheap.

## Services

| Service | Port | Role |
|---|---:|---|
| `coordinator` | 9101 | Owns the queue (from `bikes.txt`). Hands out one bike at a time, aggregates both researchers, drives validator → db_saver. |
| `researcher_details` | 9102 | bike_detail + bike_detail_component. Mirrors `app/bike_details_finder.py`: 8 categories, same per-category prompts, same `extract_json` + tolerant `_parse_*` coercion. |
| `researcher_photos` | 9103 | bike_detail_photos. Mirrors `app/bike_photos_finder.py`: LLM finds the product URL, the service scrapes images itself with the same `_IMG_SRC`/`_SKIP` regexes. |
| `validator` | 9104 | Checks everything needed to save is present, and says **which side to re-fetch**. |
| `db_saver` | 9105 | The only writer. Goes through `repository.save_bike_details`, then reads the row back. |

## Flow

```
bikes.txt
    │
    ▼
coordinator ──GET /next──► agent
    │                        │
    │        ┌───────────────┴───────────────┐
    │        ▼                               ▼
    │  researcher_details :9102        researcher_photos :9103
    │  GET /task  → 8 work orders      GET /task → find product URL
    │  POST /submit (raw text)         POST /scrape (url) → Playwright
    │        │                               │
    │        └───────────────┬───────────────┘
    │                        ▼
    └──both done──► validator :9104 ──valid──► db_saver :9105 ──► cache.db
                          │
                          └─invalid─► targeted re-fetch (details or photos only)
```

The coordinator is the only component that talks to more than one other service.
Researchers never touch the DB; `db_saver` is the sole writer, because SQLite
takes a database-level write lock.

## Running

### STOP THE COORDINATOR *BEFORE* `round_prep.py` — order matters twice

`round_prep` deletes `state/queue.json` so the next coordinator start rebuilds
from the fresh `bikes.txt`. A **running** coordinator holds the old queue in
memory and re-saves it on any mutation, so a single late submission resurrects
the previous round's queue. Round 11 was dispatched to six agents against an
already-drained round-10 queue because of exactly this, and it looked like a
finished round (identical saved/skipped counts) rather than a failure.

There is a second ordering trap on the restart: `run_all.py` re-spawns a killed
child within ~1 s, so `kill → delete` loses the race and the new process reloads
the file before it is removed. **Delete, then kill.**

```bash
# correct sequence
kill the coordinator  ->  round_prep.py  ->  rm state/queue.json  ->  kill again to rebuild
# or, mid-session:     rm state/queue.json  &&  kill 9101      (delete FIRST)
```

Verify after every round change: `state/queue.json`'s `created` timestamp must be
new, and the first few brands must match the new `bikes.txt`. `queued: 40` on
`/health` proves nothing — a stale queue is also 40.

Run from `docs/bikes/` — **not** `backend/`. The pipeline was archived here but
its imports were never re-pointed, so every entry point resolved `pipeline.*`
against `backend/` and nothing started until round 6 fixed it.

```bash
cd docs/bikes
../../backend/.venv/Scripts/python.exe pipeline/round_prep.py 40   # close last round, refill
../../backend/.venv/Scripts/python.exe pipeline/run_all.py         # starts all five
curl http://127.0.0.1:9101/status
curl "http://127.0.0.1:9101/next?role=details&worker=d1"           # claim a bike
```

`cache.db` is unaffected by the working directory: `app/models.py` resolves it
relative to its own file, so it is always `backend/cache.db`.

### Submit endpoints — get these right in the agent prompt

Photos and details do **not** submit symmetrically, which cost two agents a
detour in round 6:

| Result | Endpoint |
|---|---|
| photos | `POST 9101/submit/photos` — on the **coordinator** |
| details | `POST 9102/submit` — on the **researcher** |
| skip | `POST 9101/skip` |

**Neither researcher service completes a bike.** `9102/submit` and `9103/scrape`
are *extractors*: they parse or render, hand the payload back, and write nothing
to the queue. Every completion goes through the coordinator. An agent that posts
only to a researcher gets a cheerful `{"ok":true}` and its bike is re-served by
`/next` forever — round 6 lost an agent to exactly that loop, because both
services advertised their own extractor as `submit_to`. Both briefings now
publish the coordinator URL as `submit_to` and the extractor separately as
`parse_check` / `extract_with`.

Details body nests the work under `payload`; photos body does not:

```
POST 9101/submit/details  {"brand","model","payload":{"components":[...],"description","source_urls":[...]}}
POST 9101/submit/photos   {"brand","model","photos":[...],"source_urls":[...]}
```

Then an agent performs the two work orders and posts results back. One round =
one pass through `bikes.txt`.

## Repair rather than restart

When validation fails the coordinator does **not** throw the bike away:

- `refetch: "details"` → only the details researcher runs again
- `refetch: "photos"` → only the photo researcher runs again
- `researcher_details /task?missing=frame,brakes` narrows the order to the
  categories that are actually missing, so a repair costs 2 searches, not 8

Three failed attempts marks the bike `failed` and moves on.

## Round log — update this every round

### Round 0 (design), 2026-07-28
Built from the lessons of two earlier agent-swarm runs on the same task:

- **Writes must not depend on agent messaging.** A 22-agent run researched 100
  bikes in ~10 min and wrote 2, because the write path stalled behind mailbox
  coordination. Here the write is a plain REST call in the coordinator's own
  process — there is no message for it to get stuck behind.
- **Schema validity ≠ truthfulness.** A researcher submitted a complete, schema-
  perfect spec tree for the Production Privée Dirty Bandit — a bike sold as a
  bare frame — transcribed from a stranger's custom build page. No contract
  check catches that. Open problem; see below.
- **`None` is not a placeholder.** "Suspension: None" on a rigid fork and
  "Front Derailleur: None" on a 1x are truthful. The validator's sentinel list
  deliberately excludes `none`; rejecting it sends researchers to redo correct work.
- **Never end an agent prompt with "wait for work".** A background agent with
  nothing to do completes as idle and never wakes. Agents here pull work
  themselves via `GET /next`, so there is nothing to wait for.
- **This DB has no `brand_norm`/`model_norm` columns.** `bike` is
  `UNIQUE(brand, model)` on raw strings, so near-duplicate model strings silently
  create separate bikes ("Blix Sol X Comfort Ebike" vs "Sol X Comfort Ebike").
  `scripts/migrate_bike_details.py` has never been run here.

### Round 1 — 2026-07-28 · 8 bikes · **8 saved, 0 failed, 0 validator rejections**

DB 174 → 179 bikes, 118 → 123 details. Every bike verified in `cache.db` with real
rows (62–92 components each, except Crust Dakar at 21, correctly, being frame-only).
Roughly 4 web calls per bike — the manufacturer-page-first method beat the 8-blind-
searches the work orders implied.

**Zero rejections is not the same as a tested gate.** Both researchers said so
unprompted: the validator never fired, so its repair path is still unexercised.

#### What broke, and what was done about it

**Photos: only 1 of 8 scraped cleanly.** Four defects in the `_IMG_SRC` regex,
each confirmed against real page HTML rather than guessed:

| Defect | Effect | Fix |
|---|---|---|
| `https?://` required | Protocol-relative `//cdn/...` — the Shopify default — never matched. Crust returned 0. | `(?:https?:)?//`, prefix `https:` |
| Reads eager `src`, ignores `srcset` | Aventon returned 10px `w=10&blur=10` LQIP placeholders | Parse `srcset`, take the **largest** descriptor |
| No entity decoding | URLs carried literal `&amp;`; JS blobs used `\/` | `html.unescape()` + de-escape |
| `{width}` placeholder | Broke extension matching entirely | Rewrite `{width}x`→`1600x`, `_500x`→`_1600x` |

Now in `pipeline/photo_extract.py`, plus the highest-value change: **JSON-LD first**.
Shopify embeds clean absolute URLs in `application/ld+json`; regex is the fallback.
Added HEAD-verification (drops non-200 / sub-15KB — kills placeholders and 160px
review thumbs with no site-specific knowledge), a product-URL pre-check (round 1
spent a browser launch on a 404), `networkidle` + scroll for lazy galleries, and
`_SKIP` entries for Judge.me widgets, geometry charts, swatches and option chrome.

⚠️ **`app/bike_photos_finder.py` has all four defects too** — it is the live
`/v1/bike/details` photo path. Untouched here; needs its own change.

**Categories did not fit real bikes.** Both researchers hit this independently:
- E-bike motor/battery/charger/display had no home — one put motor under Drivetrain,
  the other under Frame. Same fact, different category, depending on who did it.
  → added a 9th **Electric / Powertrain** category (`bike_details_electric.md`),
  optional, returns `[]` for non-electric bikes.
- Bar Tape assumed drop bars; 5 of 8 were flat-bar and have grips. → work order now
  names Grips as the flat-bar alternative, and asks for Handlebar and Stem separately.
- The Accessories `Tool` subcategory was omitted 8 times out of 8 — no manufacturer
  publishes it. → explicitly optional.
- Lighting was empty on 5 of 8. → now optional in the validator alongside Electric.

**The per-category API shape fought the method that actually works.** The work order
asked for eight raw model outputs, but the recommended path — read one spec table,
answer everything from it — produces *one* source. `/submit` now also accepts a
whole-bike `blob`; `raw` remains for gap-filling. Both may be sent together.

**Fetch reliability is the bottleneck, not prompts.** 99spokes, roadbikedatabase,
bike24 and performancebike all return **403** to WebFetch, and they top nearly every
search. Manufacturer pages are often JS shells: Airdrop's spec page renders
"Loading...", Ari's comparison table never populates, Brooklyn's spec page serves
different content. What works: Vital MTB `/product/guide/`, mtbdatabase,
Tradeinn/Bikeinn, and Smartetailing dealer shops (two gave byte-identical tables for
the Brooklyn — a free cross-check). → codified as `SOURCE_LADDER` in `common.py`,
now shipped in every work order.

**Build-kit ambiguity was resolved per-researcher.** "Ari Bikes Empire" and "Chromag
Doctahawk" are platforms with a ladder of builds, not single products. Two researchers
would produce different trees. Bombtrack Arise SG **Rival** was easy precisely because
the queue named the build. → `BUILD_KIT_RULE` in `common.py`: default to the stock or
entry build and name it in the description; carry the build kit in the queue entry
where the source has one.

#### Process failure — mine

I replaced the sequential `worker` with parallel `w-details`/`w-photos` but never
stopped it, so it kept running and raced the same queue. Harmless here — the
`skipped_fresh` path meant the second writer found the row already stored, and all 8
bikes verified clean — but it wasted a full agent's research and made `worker`
report a bike it had not done. **Stop the old agent before starting its replacement.**

#### Weakest record this round

`Ari Bikes / Empire` — 62 components but thin, assembled from scattered secondary
mentions because the manufacturer's comparison table would not render and every
aggregator 403'd. Honest and marked as such in its description. Redo first if a
JS-executing fetch becomes available.

### Round 2 — 2026-07-28 · 10 bikes · **10 saved, 0 failed, 0 validator rejections**

53–102 component rows per bike, 9/9 categories parsed every time, no repair passes.

**`blob` beat per-category decisively.** Not a single `raw` entry was sent all round.
One spec table → one JSON array → one submit; 3–5 fetches per bike instead of 8
category searches. It also removed cross-category contradiction (rotor size differing
between Brakes and Wheels) and made sibling builds nearly free — Works-from-Core and
Current EXP-from-ADV were produced by patching the previous blob in ~90s each.

**Electric / Powertrain fitted cleanly** on all three e-bikes; Motor/Battery/Charger/
Display/Assist Class map 1:1 onto how dealers publish. Only friction: nominal vs peak
wattage is reported inconsistently (750W peak / 850W boost / 250W EU nominal), handled
by putting nominal in Power and peaks in Peak Power.

**Photos: validity fixed, relevance broken.** 10/10 scraped, zero hand-repairs, zero
empties (round 1: only 1 of 8 clean). Every URL live and full-size — the four round-1
defects are genuinely dead. But the failure mode moved from *broken URLs* to *wrong
product*, which is worse because it reports success:

| Symptom | Cause | Fix |
|---|---|---|
| Both Bombtrack pages carried the same 3 **Arise** images | JSON-LD flattened every Product in the document, incl. cross-sell blocks | Scope to the Product node whose `url`/`name` matches this page |
| Both Aventon bikes returned **byte-identical** 8-URL lists — battery closeup, PDF render, a garden hose — and reported "8 photos, HEAD-verified" | Site chrome, no relevance signal | Filename relevance ranking + cross-page fingerprint check (identical set across two products ⇒ suppress) |
| Buying-guide covers, lifestyle shots, a Lorimer photo on the Roebling page | `_SKIP` too narrow | Added `_page-\d{4}`, buying-guide, lifestyle patterns |
| Suspiciously thin results (1 photo) invisible | No reporting of drops | `/scrape` now returns a `rejects` list with per-URL reasons |

All six affected bikes were re-scraped through the fixed extractor and their photo rows
rewritten in place. Result: 8/8 filename-matched on every one. The Aventon pair went
from 8 identical junk images to 8 correct, per-bike product shots.

**Highest-yield discovery of the round — Shopify `.json`.** Appending `.json` to any
`/products/<handle>` URL returns the full factory spec table as plain JSON *even when
the rendered page is a "Loading..." JS shell*, plus the true product title (which is
how a distinct SKU gets told apart from a variant). Promoted to rung 1a of the ladder,
above everything except a working manufacturer page.

**Ladder updated:** added `bikes.fan` (saved both Brooklyn bikes, whose own site
publishes only marketing prose), `opticycles.com`, and Shopify dealers `ezbike.ca` /
`bicyclewarehouse.com` (ezbike was the ONLY source with the full Aventon Current
table). Moved `mtbdatabase.com` to snippet-only — it 403s exactly like 99spokes.

⚠️ **WebSearch budget is per-session and finite** — round 2 exhausted 200/200 on the
last bike. The ladder now leads with *fetch first, search only when the URL is
unknown*; guessing a product URL and fetching it is free, searching for it is not.
This is the main constraint on long multi-round runs.

**Also added:** subcategories are a minimum, not a closed list — Rear Shock, Headset,
Shifter and Chainguide were added ad hoc and stored fine, and a full-suspension or
e-bike record is materially worse without them.

### Round 3 — 2026-07-28 · 10 bikes · **10 saved, 0 failed, 0 validator rejections**

67–104 component rows per bike. **Zero WebSearch calls for the entire round** — the
whole thing ran on guessed URLs plus `curl`. That removes the budget ceiling that
looked like the hard limit on long runs.

**How the search dependency was eliminated:**

| Technique | Why it matters |
|---|---|
| `<site>/products.json?limit=250` as a handle index, fetched once per brand | Handle guessing kept failing — `lasal` not `la-sal-peak`, `juice-2023`, `level-3-commuter-ebike`, everything Bombtrack prefixed `bombtrack-`. One fetch lists every handle and true title. |
| `curl` from Bash instead of WebFetch | Costs no budget, returns raw HTML rather than lossy markdown — which is what makes blob extraction possible at all. |
| Embedded spec blobs in page HTML | Richer than the JSON API: Ari ships `const data = [` with the entire build ladder (~29 fields per build); Aventon has `class='tech-spec-group'` divs with the full factory table including the e-bike block. |

**Shopify `.json` was a partial win, not the whole answer.** It reliably gives the true
title and handle, but the full spec table only on some brands (Bombtrack yes; Ari,
Aventon, Brooklyn and Chromag put marketing prose in `body_html` and keep the real
table in the rendered page).

**Photos: relevance improved again, and the failure mode moved up a level.** 10/10
scraped. Remaining junk was *sibling-variant* images — `Level4` on a Level 3 page, each
Beyond carrying the other's hero, `willow-7i` on a Willow 8i page — all of which the
filename ranker had counted as matches, so the "filename-matched" ratio was overstating
precision. Fixed by:

- **Positional variant detection** — only the number *following* a model word counts.
  Two bugs surfaced while building this and were caught before shipping: gallery
  sequence numbers (`_01`) and model years (`MY24`) were being read as variant numbers,
  which penalised the *correct* images.
- **Provenance floor** — Bombtrack's genuine galleries are named by EAN
  (`4055822531849_1.jpg`), scored 0 for having no words, and lost their slots to a
  worded cross-sell image. JSON-LD Product-node URLs now score positive regardless of
  filename; filename match breaks ties instead of gating admission.
- **Identity dedupe** — `_2048x.jpg` and `_1216x.progressive.jpg` were taking two slots
  on 3 of 10 bikes.
- **No regex merge when scoped JSON-LD is healthy** (≥4 images) — merging was
  re-importing the very cross-sell images the scoping had just excluded.

All five affected bikes were re-scraped: **0 junk remaining**. Counts dropped (7→5,
8→4) because siblings and duplicate renders were removed — fewer photos, all genuine.

**The fingerprint check correctly stayed silent** on all three sibling pairs, which is
why they were queued together. Suppression would have been wrong on every one: Level 3
vs ST share 3 images but have 5 distinct each, Beyond 1/2 each lead with their own
colourway, Juice/Lowdown have zero overlap.

**Global audit:** 141 detail rows, 4 with sibling-variant junk — all four from the
earlier swarm backfill, none from the pipeline.

**Judgement calls worth keeping:** Ari Nebo Peak's Fazua motor power was left blank
rather than asserting Fazua's published 250/450W, since neither Ari nor fazua.com
stated it for that build. Chromag Juice's frame weight is published as literally "TBD"
and was stored as `""`. Beyond 2 was fully rewritten rather than patched from Beyond 1
after diffing revealed a different drivetrain, hub, lights, tyres and rack — a blind
patch would have been badly wrong.

### Round 4 — 2026-07-28 · 10 bikes · **10 saved, 0 failed, 0 validator rejections**

Third consecutive round on **zero WebSearch calls**. Four sibling pairs, deliberately.

**Specs: the sibling diff mattered in both directions.** Level 4 ADV vs Step-Through
were byte-identical except frame style/rider height/sizes, so patching was right.
Minor Threat vs V2 was a real version bump — brakes G2 R → 4-piston Code RSC, shock
190x45 standard → 165x45 trunnion, different fork, GX→NX chain, a new third size — so a
blind patch would have been badly wrong. **Diff before patching** is now `SIBLING_RULE`.

**Photos: the biggest single improvement of the whole run — stop inferring, ask.**

Round 4 exposed that filename heuristics have a hard ceiling. The Chromag `Minor Threat`
page returned **7 of 8 images belonging to `Minor Threat V2`** and reported them 8/8
"filename-matched", because every V2 file contains `minor-threat` and carries no `v2`
token at all. Nine genuine V1 images were dropped. The "filename-matched" number was
meaningless as a precision signal: 8/8 on the worst bike of the round, 0/8 on one of the
best.

Fix: **`/products/<handle>.json` → `images[]` is authoritative.** Shopify declares each
product's own gallery, so there is nothing to infer — no cross-sell, no sizing charts,
no spec icons, no sibling contamination — and it needs no browser at all. Verified live:
`minor-threat` returns its own 10 images, `minor-threat-v2` its own 12.

Also fixed this round:
- **`product_type` distinguishes a complete bike from a frameset/spare/outlet/accessory.**
  Matching on title alone pulled "Arise Bearing Set" for `Arise` and "Explorer Peak
  Recommended Accessories" for `Explorer Peak`.
- Version markers (`v2`, `mk2`) rejected **asymmetrically** — a candidate carrying a
  marker the target lacks is a sibling, but not the reverse, since V2's real gallery
  carries no `v2` token.
- A variant number is only a variant when **followed by more tokens**; a trailing number
  is a gallery sequence (`bella-velio-1.jpg`).
- Fingerprint/dedupe keys on the CDN **path**, not the full URL — query-string variants
  were taking two slots each (6 distinct images in an 8-slot payload).
- `_IMAGEY` no longer matches `.js`/`.css` served from the same CDN, which had been
  polluting the `rejects` list and hiding real drops.
- A real UA plus one retry on the URL pre-check: bare httpx was refused on first request
  and served on retry, which read as a dead product URL and cost four wasted round-trips.

**Two bugs I introduced and had to repair**, both worth remembering:
1. Loose title matching rewrote 58 galleries and put a **seat clamp** on Beyond 1 and
   Beyond 2, a bearing set on Arise, and outlet screenshots on Kings Peak.
2. `NOT_COMPLETE` had an unanchored `rack\b` which matched "Bombt**rack**" and silently
   rejected that brand's entire catalogue. Every alternative is now `\b`-anchored on both
   sides.

**Still unresolved:** `Arise SG Rival` has no complete-bike listing on the storefront,
and Crust sells framesets (`product_type: Frames`) rather than completes — correct
behaviour, not a defect.

**New ladder entries from d4:** Wayback (`archive.org/wayback/available?url=...`) for
discontinued models — Chromag archives retired bikes and strips the build list, and a
snapshot of the manufacturer's own page beats any third party. Also: read `product_type`
from the index routinely, and grep case-insensitively when probing HTML.

### Round 5 — 2026-07-28/29 · 98 bikes · **73 saved, 13 skipped, 12 unfinished, 0 validator rejections**

Scaled from 1 worker to 6 (4 spec + 1 photo + 1 browser scout). Ended when all four
spec agents hit the session token limit, not for any pipeline reason. DB 182 → 224
detail rows.

**Measured: parallelism helps, sub-linearly.**

| spec workers | throughput | speedup | efficiency |
|---:|---|---:|---:|
| 1 (rounds 1–3, consistent) | 0.50 bikes/min | 1× | 100% |
| 4 (measured over 9.5 min) | 1.05 bikes/min | 2.1× | 52% |

The gap is **per-brand** discovery cost paid repeatedly: paginating a catalogue and
finding where a brand hides its spec table costs the same whether you then do one bike
or five. Four agents on four brands pay it four times, and they cannot share a cache
(separate sessions; the shared scratchpad actively corrupted files). Photos scale far
better — one authoritative fetch each, no discovery, no browser.

**The browser scout changed the shape of the problem.** With the WebSearch budget
globally exhausted (200/200) and free engines blocked (DDG 202s, Mojeek captcha, Bing
JS shell), spec research had collapsed to domain-guessing. A scout driving real Chrome
confirmed Google is fully usable that way — but its more valuable finding was that it
mostly didn't need Google: **24 of 24 boutique bike brands serve an open
`products.json`**. That turned spec research from search-dependent to fetch-first.
Only romet.pl (Magento PWA), sparta.nl and specialized.com (Next.js) resisted.

**Discovery traps that each silently produced a wrong "not found" or a wrong bike:**
- `products.json` is NOT the whole catalogue — Rivendell's feed exposes 72 products,
  its sitemap 512. Fall back to `sitemap_products_*.xml`.
- **Missing `curl -L` silently empties a catalogue** — Raleigh 302-redirects to a
  locale path; without follow-redirects the body is empty, indistinguishable from
  "no products".
- Handles do not match titles: Marin is off by a year (`2024 DSX FS` → `/2023-dsx-fs`);
  Rocky Mountain has three products titled identically `Altitude Alloy 30`; Revel and
  Pure Cycles invert which variant gets the bare handle; Chromag keeps every model year
  live simultaneously.
- `product_type` is necessary but not sufficient — Chromag's Primer is typed `Bicycles`
  yet all nine variants are frame-only. Salsa's `Archived Bike` type still carries real
  galleries, so archived ≠ unresearchable.

**Duplicate identities found in the DB.** 30 near-duplicate pairs; most legitimately
distinct (Arise vs Arise SG Apex, Minor Threat vs V2). One class is a real defect: the
same physical bike stored twice under a bundle suffix — Lectric `...Glacier Blue` /
`...Glacier Blue eTrike`, Engwe `Engine X` / `Engine X Combo`, Priority `600ADX` /
`600ADX Adventure Bundle`. Selection now drops `combo|bundle|package|etrike`. **The
existing pairs were left in place** — deleting rows is the user's call.

**Two infrastructure bugs, both mine:**
1. `run_all.py` killed all five services whenever any one child exited, so restarting a
   single service to reload config took the pipeline down — twice — stranding every
   worker. It now restarts the dead child instead; verified by killing a service and
   watching it recover while the coordinator stayed up.
2. Growing the queue by editing `queue.json` and restarting silently lost 20 bikes: the
   still-running coordinator held the old queue in memory and rewrote the merged file on
   every save. Added `POST /add` so the owner process mutates its own state.

**New endpoints this round:** `/add`, `/skip`, `/release`, `/hint`, `/unhinted`,
`/throughput`, and `/next` now returns `in_flight`/`drained` so a late worker knows
whether to wait or exit. `/skip` closed a real deadlock — a worker holding an
unresolvable bike got it back on every `/next` call, and the only escape was submitting
a hollow payload.

**Agent judgement worth recording.** Every one of these was self-reported, unprompted:
- `p5` refused to submit an empty payload to escape a deadlock, and parked instead.
- `p5` later caught its own zero-photo submission, added a guard, and retired the bike
  with a reason explicitly superseding the bad record. Verified: it never reached the DB.
- `p5` found its batch runner had run 25 iterations against a dead coordinator and
  *looked like 25 successes* because the traceback went to stderr while only stdout was
  captured. Fixed to treat an unparseable `/next` body as service-down, not drained.
- `p5b` declined to substitute a neighbouring Specialized SKU after searching all 5170
  products, and skipped instead.
- `d5` reported a case-sensitive grep that twice returned "no spec table" on pages that
  had one, nearly costing two good records.

**Integrity at close:** 0 detail rows with no components, 0 with an empty description,
0 null spec values, 1 pre-existing exact-duplicate identity (`INDIANA`/`Indiana`, from
before this pipeline). Other tables untouched.

### Round 5 close-out — queue drained: **84 saved, 14 skipped, 0 unfinished**

Final DB: 296 bikes, 235 with details, 13,922 component rows, 1,112 photos.
Integrity: 0 detail rows without components, 0 empty descriptions, 0 null spec values,
1 pre-existing duplicate identity. Other tables untouched.

#### Techniques discovered in the final stretch — add these to the ladder

1. **Spec tables backed by a public Google Sheet.** Otso ships empty
   `<div id="tableDivFrameSpecs">` placeholders and fetches them at runtime via the gviz
   API. The sheet id and per-tab gids are in plain sight in an inline `<script>`:
   `curl "https://docs.google.com/spreadsheets/d/<id>/gviz/tq?tqx=out:json&headers=1&gid=<gid>"`
   returns the whole table. Turned a page with literally zero spec text into a complete
   frame spec plus geometry.
2. **Embedded spec JSON, not just JS templating.** Rocky Mountain's `body_html` is empty
   and the page looks JS-only, but the full 24-field factory spec is in the raw HTML as a
   JSON object. Grep for a known field name (`"Rear Derailleur"`), walk back to the
   enclosing brace, `json.loads`. Richer and faster than tag-stripping. **Do not write
   bikes.com off as JS-only.**
3. **Access-protected products are a distinct failure mode.** Otso's "1-All Hoot Steel
   Frames" returns HTTP 200 with a body reading "This content is protected…" — a
   dealer-gated listing, not a dead handle. The status code gives no clue. Fix is to find
   the equivalent public listing.
4. **`body_html` is a coin flip; the rendered page is the reliable source.** Only Early
   Rider and Pure Cycles put a real table in `body_html`. Heybike, Lectric, Murf, Pedego,
   Raleigh, Reilly, Knolly and Chromag all keep marketing prose there and the real table
   300k–1M bytes into the rendered HTML.
5. **Grep for a distinctive VALUE, not a label.** Searching "Derailleur"/"Fork" lands in
   Shopify's product-recommendations JSON. Searching `Shimano`, `Tektro`, `48V`, `Nm`,
   `tech-spec-group` or `specs-table` goes straight to the block. On Murf, "Derailleur"
   returned zero hits while the spec block was present under different labels — **a zero
   result for a label does not mean there is no table.**

#### The validator earned its keep at the very end

It rejected a submission carrying `'N/A'` for front derailleur type — copied verbatim from
Otso's own page. The correct value was `"None"`: the frame genuinely has no FD provision.
**A manufacturer's own "N/A" must be translated, not passed through.**

#### Reliability lesson: persist the payload between the two POSTs

Both services flapped repeatedly during this round (my supervisor bug, since fixed). Two
agents independently lost a completed research pass because `:9102` accepted the build and
`:9101` was down a second later, with the payload only in memory. Both independently built
the same fix — cache the built payload to disk before the queue POST, then retry (one
recovered on attempt 8). **Ship that as the default submit path** rather than letting each
agent rediscover it. Artefacts: `d5c_submit2.py`.

#### Data conflicts resolved rather than passed through — the right instinct

- Ragley's own Frame Specifications block says 6061 alloy while its component table and
  body copy say 4130 chromoly. Recorded steel, documented the contradiction.
- Early Rider publishes the Belter rear sprocket as both AL6061 and AL7075 on one page —
  grade omitted rather than guessed.
- Kona lists two different bikes both titled "Dew DL" (current CUES 29er at `dew-dl-37`,
  older 650b at `dew-dl`). Specced the current one, described the other in the record.
- Pure Cycles "8-Speed" is a derailleur over a 12–32T freewheel, NOT an internally geared
  hub — **a speed count in a model name is not evidence of hub gearing.**

#### Sibling-diffing vindicated one last time

Linus Dutchi 1 vs 3i look like trim variants but differ in braking — coaster hub only, no
hand brakes at all, versus dual-pivot calipers front and rear — plus chainguard material,
wheel size per frame size, crank length and rack fitment. A blind patch would have been
wrong on the most safety-relevant spec on the bike.

#### Known-thin records, flagged honestly

Murf, Heybike and Raleigh publish marketing-level figures with no component table; those
records are honest but thin and no additional fetching will improve them. The single
weakest is `sixthreezero 16" Foldable` — fully client-rendered site, no motor/battery/brake
text even with a browser UA, Wayback rate-limiting at the time. Stored only what the
manufacturer's title and product_type state, everything else blank, with a description
noting it needs a browser-rendered re-research. It passed the validator but should be
revisited.

#### More sources found at the close — all previously unlisted

- **Public Google Sheets via the gviz endpoint.** Found independently by two agents. Grep
  product HTML for `docs.google.com/spreadsheets` before giving up on a JS-rendered spec
  tab.
- **Manufacturer spec spreadsheets on the CDN.** Detroit Bikes links a
  `2019_Bike_Specs.xlsx` with every model as a column — the whole range in one 18 KB file.
- **Owner's-manual PDFs** for cheap e-bikes whose product pages are pure marketing:
  Engwe's `ENGINE_Pro_Manual.pdf` (found via a Wayback snapshot, still live on the CDN)
  carried the real spec table. Note: PyMuPDF (`fitz`) is installed, `pypdf` is not.
- **Museum/heritage APIs for pre-1900 entries.** "Fredrik Runstedt | The Vrigstad bike" is
  an 1868 Michaux-pattern boneshaker, not a modern bicycle. The Nordiska museet catalogue
  (free `api.dimu.org` solr endpoint, `api.key=demo`) describes the surviving object
  component by component — producing a real sourced record instead of a skip. Non-product
  research is sometimes the correct answer.
- **Two more embedded-blob patterns** beside Ari's `const data = [`: Rocky Mountain
  (bikes.com) has null `body_html` and a JS spec tab but the full build table inline as
  flat `"Frame":"...","Fork":"..."` pairs; Marin does the same with escaped markup. Both
  look unresearchable and are not.

#### A validator behaviour that costs two round-trips per frameset

A frameset whose only content is `Lighting: "None"` and `Accessories: Pedals: "None
included"` is rejected as "only N of 8 categories present". The cause is the
`spec_count == 0` guard — categories whose elements carry no `specs` entries contribute no
spec rows, so a genuinely minimal frameset reads as empty. The workaround used was to add
a real Wheels category from the frameset's published thru-axle specs. **This should be
fixed properly**: count a category as present when it has elements, whether or not those
elements carry spec rows.

#### Operational notes for next time

- archive.org returns **429** under parallel agents — rate-limit Wayback access.
- Stop each round's agents when the round ends. Nine agents from finished rounds were
  still alive at close, consuming the shared token pool and contributing to four spec
  agents hitting their session limit.
- Have the scout report **frameset vs complete bike** in its hints — it changes the whole
  record shape, and agents had to determine it themselves three times.

### Round 6 — 2026-07-30 · 40 bikes · source switched to the consolidated index

**The pipeline did not start.** Archiving it to `docs/bikes/` moved the package
but not the import path: `run_all.py` launched uvicorn with `cwd=backend/` and
targets like `pipeline.coordinator:app`, so all five failed on
`ModuleNotFoundError: No module named 'pipeline'`. `db_saver` had a second,
separate failure — it is the only service that reaches into `app.*` without
importing anything from `pipeline.common`, so it never got the `sys.path`
bootstrap the other four inherit as a side effect. Both fixed. **A relocation
that leaves imports behind fails silently until the next run, which was two
days later.**

#### The product URL is the round's real change

`bikes_to_save.json` (3,491 bikes) carries an authoritative product URL per bike;
`round_prep.py` now sources from it and seeds `hints.product_url` into the queue.
Effect: **photo research drained all 40 before spec research reached halfway**,
and photo yield roughly doubled (~10/bike vs ~6). Every store was Shopify, so
every photo job became a direct `<product_url>.json` → `images[]` read with no
rendering and no search. Handle-guessing and scouting — the dominant per-bike
cost in rounds 1–5 — disappeared entirely.

#### The URL is also a filter the model name cannot be

The first pick list wasted ~8 of 40 slots on non-bikes that read as bikes. Only
the URL exposed them:

- Canfield `BALANCE` → `balance-frameset-...` (frameset)
- Chromag `Samurai` and `Samurai 2020` → **the same URL** `frames-sam65`
- Esker `2026 Titanium Pre-Order Deposit` (a payment), `Portage Dropout - UDH` (a part)
- Lectric `...Special Offer` → `special-launch-bundle` (duplicate of the base model)
- 6 × Garelli/Helkama/KhVZ/LMZ/Monark → wikidata.org, where no component table exists

Added `URL_REJECT_RX`, `NON_PRODUCT_HOST_RX`, `PART_EXTRA_RX`, and URL-level
de-duplication. **Two rows sharing one product URL are one bike under two names.**

Deliberate throughput choice: Wikidata/Wikipedia marques are now skipped rather
than researched. Round 5 spent a full cycle on each for thin records or skips
(one exception: an 1868 boneshaker via a museum API). With 3,400+ manufacturer
pages queued they are a poor use of a slot — reversible if coverage matters more.

#### A listing title became a bike's name

`Kinesis | - Bicycle - R1 - Pebble Discontinued` was stored verbatim. Because
**the model string IS the display casing in this schema**, that garbage would
have been the bike's name everywhere in the app. Repaired to `R1` (and
`G2 Bicycle` → `G2`); `LISTING_RX` now rejects `discontinued`, `bicycle`, and a
leading dash. The attached specs and photos were correct — only the name was wrong.

#### A service that lies about its own contract costs more than a bug

Both researchers advertised `submit_to` pointing at their own extractor. p2
submitted Marin Kentfield 1 to `9102/submit`, got `{"ok":true}` with the parsed
blob echoed back, and watched `/next` re-serve the same bike with `attempts:0`.
The success response was real — the parse *had* succeeded — it just meant
nothing. **An `{"ok":true}` that does not correspond to a state change is worse
than an error**, because a careful agent has no reason to doubt it. Fixed at the
source: `submit_to` now names the coordinator on both services.

Worth noting the two agents who hit this both diagnosed it by checking `/status`
and `/next` rather than trusting the response, and reported it upward instead of
working around it silently. That is the behaviour that turned a silent throughput
leak into a one-line fix.

#### The single most reusable finding: grep for the words, not the markup

Rounds 3–5 catalogued spec-blob class names one theme at a time —
`tech-spec-group` (Aventon), `const data = [` (Ari). Round 6 showed that is the
wrong abstraction: the same trick reappears under a different name on every
theme (Kinesis `metafield-single_line_text_field`, Murf `tsd__item-text`, Pedego
`Specs-value` in an off-canvas drawer, Aventon also `techSpecs.data`). **Grep the
rendered HTML for the literal words** — `Specifications`, `Motor`, `Battery`,
`Frame:` — with `grep -aob`, then `dd` a window around the byte offset. That
finds the table on themes nobody has catalogued yet, which the class-name list
by construction never will. Now in `SHOPIFY_PITFALLS`.

#### A skip is a research result, and it was being thrown away every round

`pick()` excluded only what the **DB** contained. A skip writes nothing to the
DB — so every correctly-rejected bike came back the next round and was
re-investigated to the identical conclusion. Round 7 spent 2 of 40 slots
re-skipping Chromag Samurai and Crust Geared Wombat, both settled in round 6.
Unfixed this compounds: the re-skip tax grows with every round's rejections.

Now persisted to `state/skipped.json` (brand, model, reason) by `log_round`, and
excluded by `pick()`. Seeded with the four known skips from rounds 6–7. All four
were framesets or archive listings, and all four were **correct** — the waste was
in re-deciding them, not in the decisions.

#### A thin record is not always thin research

`Production Privee Mini Shan Limited Explorer` came back with 19 spec rows
against a ~60 typical, which read as a weak record. It is not: it is a 12" kids
push bike with four published facts (6061 T6 frame, rigid fork, 12" wheels,
disc-mount-ready rear hub) and **no drivetrain or brakes to record**. The agent
recorded exactly that and invented nothing. Spec count is a signal to look, not
a quality metric — judge against what the bike actually has.

#### Identical `product_id` does not prove same model

p2 found the Linus Dutchi 7i gallery carrying three `Dutchi_3i` filenames under
an unchanged `product_id`, and excluded them. Shopify colorway/variant galleries
can leak sibling images without any id change — **filename is evidence the id is
not.** Related: the Marin hint slug read `2023-fairfax-2` while the page title
read `2024 Fairfax 2`. Trust the page's own title over the slug.

### Round 7 — 2026-07-30 · 40 bikes · **36 saved, 4 skipped, 0 validator rejections**

All four skips correct (framesets + a 2017 archive listing). Ran clean: no agent
hit the submit-endpoint dead end, because the corrected `submit_to` now ships in
the briefing. Photos again finished well ahead of specs.

#### Listing facets became product names — a separator class was the whole bug

`LISTING_RX` already had `ex\s*display`, but **"Ex-Display" is hyphenated and
`\s*` cannot match a hyphen**, so `Lyfe EBike Large Ex-Display` was stored as a
model name. Alongside it: `Hoot Ti - Large - SRAM XO T-Type - Fancy Show Bike!`,
`2022 Switch 6 Pro, Large, Norlando Grey, Custom`, `Mars 3.0 (VIP only)`. Size,
colourway and promo qualifiers are listing facets, never identity. Now
`ex[\s_-]*display` plus a size/promo/`!` clause; four names repaired in place.

**Generalise:** when a filter targets a two-word phrase, use a separator class,
not `\s*`. Vendors hyphenate.

#### A duplicate can form inside a single batch

Round 7 queued both `Mars 3.0` and `Mars 3.0 (VIP only)` under **different URLs**,
so neither the URL dedupe nor the stored-identity check saw them — both were
researched and both stored. `pick()` now also dedupes on identity with
parentheticals stripped. Deliberately conservative: real build variants
(`Chilcotin 155 XT` vs `... GX Transmission`) differ outside the brackets and
stay distinct. Verified against both sets before shipping.

#### Two brands publish no spec table at all

Priority's 600HXT and APOLLO GRAVEL keep the entire drivetrain/brake/suspension
spec in numbered marketing cards (`class="bike-feature_card-text"`, `<h4>`/`<p>`
pairs) with no `<table>` anywhere — twice on this brand now. **"No table found"
is not "no spec published."** Knolly by contrast uses plain
`<table class="responsive-table">`. Both in `SHOPIFY_PITFALLS`.

#### Judgement calls the agents got right

- **Lectric XP Trike2 Stratus White** — a pure colour sibling of round 6's Phoenix
  Red. d1 verified the spec text was byte-identical before patching brand/model
  only. That is the sibling rule applied correctly: diff first, then patch.
- **Kinesis Lyfe Ex-Display** — the ex-display page carries only condition copy,
  so d4 took the spec from the full-price sibling listing and said so in the
  description.
- **Otso Hoot Ti "Fancy Show Bike"** — a one-off showpiece, but a real complete
  purchasable bike with a published parts list, so recorded rather than skipped.
  The skip rule is for framesets and non-products, not for unusual listings.

### Round 8 — validator fixed: a gate that rewarded fabrication

The `MIN_CATEGORIES = 3` floor was flagged in the round-5 close-out as costing
"two round-trips per frameset". Round 7 showed it is worse than a cost. d2's
Production Privee Shan GT frameset was rejected with *"only 1 of 8 categories
present"*, and the way through the gate was to **add material that is not
components**. Round 5's workaround invented a Wheels category outright; round 7's
spread the frame's own published standards (BB92, Boost 12×148, 30.9 seatpost)
across Drivetrain/Wheels/Saddle labelled "standard, not included". The second is
defensible and the first is not — but a validator whose easiest path is padding
is the wrong validator, in a pipeline whose first rule is never invent a
component.

Fixed: a frameset now clears the floor on its Frame category alone, provided that
category carries `>= FRAMESET_MIN_FRAME_SPECS` (6) spec rows. This removes the
*pressure to fabricate*; it does not decide whether framesets should be stored at
all, which is still open (see known gaps). The threshold is set so
it cannot become a shortcut for a lazy complete-bike record — verified against
three cases before shipping: a real frameset with 8 frame specs now passes, a
thin Frame-only record with 2 still fails, and a normal 3-category bike is
unchanged.

This closes known gap 3 (frameset handling) from the round-5 list.

Round 8 result: **33 saved, 7 skipped, 0 validator rejections.** All 7 skips
audited and honest — 5 framesets, a buyer-choice build, and an Orange
deposit-only listing. Chromag's `frames-<model>` handle convention is now in
`URL_REJECT_RX`; `frameset` alone missed it and cost 3 slots.

#### The sharpest near-miss so far: a missing number is a spec difference

`Lectric XP Trike2 750 Stratus White` and `Lectric XP Trike2 Stratus White`
differ only by a `750` in the title and read as one product under a naming
variant. They are **different motor tiers**: 750W/1310W peak/85Nm/torque
sensor/840Wh/70mi at $1799 versus 500W/1092W/65Nm/cadence sensor/624Wh/50mi at
$1499 — while sharing frame, brakes, wheels and tyres, which is exactly what
makes a patch look safe. d1 caught it on price and rebuilt the Electric /
Powertrain category from the real page.

The sibling rule now carries a concrete test: **treat two listings as the same
spec only when the PRICE and the rendered Specifications section both match
exactly.** Everything mechanical matching is not evidence — on an e-bike the
powertrain is where the tiers differ, and it is the part a lazy patch destroys.

#### "Record what the manufacturer publishes" assumes the page is about this model

Priority's Brilliant Carmen page has a feature card that literally reads *"the
Cooper's diamond frame"* — leftover body copy from the sibling Brilliant Cooper
template. d3 dropped the line and verified the Cooper's frame on its own page.

This is the first source hazard that defeats the pipeline's core heuristic. Every
other rule assumes manufacturer copy is authoritative *about the product it sits
on*; a shared family template breaks that silently, and the wrong spec arrives
with the strongest possible provenance. **When a line names another model, it is
contamination, not a spec.** Brands that template a whole family are where to
expect it.

#### A 404 can be a regional block

Marin Pine Mountain 2 returned 404 on a handle a fresh `products.json` listed.
Not stale, not rate-limited — Shopify Markets serving 404 out-of-region. A
Wayback snapshot had the full spec. **Do not conclude a product is gone because
its own store 404s it.**

#### Also encoded this round

- **Electronic shifting is not an e-bike.** Di2/AXS have a battery and charger but
  no motor. `Electric / Powertrain` means pedal-assist; the Di2 battery belongs
  under Drivetrain. d2 got this right unprompted on the Chilcotin 155 XT Di2.
- **Try `body_html` text before the rendered-HTML grep** — one fetch instead of
  two. Bombtrack and Kinesis publish complete flat spec lists there.
- **Do not record aftermarket accessories as shipped.** Pedego lists lights,
  fenders and rack as "available aftermarket" on its own spec sheet; d2 left them
  out rather than recording them as included. Same call from d4 on the Pashley
  Courier: an electric-assist kit sold as an optional accessory does not make the
  base bike an e-bike, so `Electric / Powertrain` stayed empty.
- **`.json` 404? Try the canonical host** — drop or add `www.` before concluding
  the product is missing (d4, Kinesis: two such 404s had real content behind them).
- **`[-/]frames?$` added to `URL_REJECT_RX`** — Production Privee's
  `shan-gt-ti-frame` reached the queue and had to be reasoned out by an agent;
  `frameset` and `frames-` both miss a handle that *ends* in `-frame`.
- Contradictions recorded rather than resolved, per the rules: Linus Lil' Dutchi
  20" marketing copy says steel, the spec table says 6061 aluminum (table won);
  Kinesis Racelight Aithein shows a $0.00 legacy variant beside a full real build.

### Round 9 — 2026-07-31 · 40 bikes · **36 saved, 4 skipped, 0 validator rejections**

All 4 skips honest (3 framesets + Otso's "Frankset"). The briefing is now doing
the work it was built for: agents cited pitfalls **by number** in their reports,
and d4 applied the Di2-is-not-an-e-bike rule — d2's finding from round 8 —
without rediscovering it. A rule written once is now applied by everyone.

#### "Empty product page" kept meaning "look somewhere else on the same site"

Three separate recoveries this round, all from the same wrong assumption:

- **A separate `/pages/` route.** Pure Cycles' `/products/original-21154` has no
  spec at all — not even marketing body_html — while
  `/pages/pure-fix-original-specs` carries the full build.
- **An authorized reseller's Shopify `.json`.** Linus runs Shogun, so the Mixte 3i
  has no spec anywhere on Linus's site; a dealer selling the identical SKU
  (`bikesonwheels.com/products/mixte-3i.json`) had the whole breakdown. Better
  than the WebSearch prose we had been settling for — a structured product record,
  verifiable by SKU.
- **A dealer's plain HTML spec page** (Campfire Cycling for Otso Voytek).

Generalised into the briefing: **client-rendered sites recur per BRAND, not per
product**, so once a brand is known Shogun/JS-only, go to a dealer immediately
rather than re-fetching or falling to search. This is now the default move, not a
last resort.

#### Two more identity traps

- **"Bike" in the title does not mean complete bike.** Kinesis "Racelight T2 Bike"
  is `product_type: Bicycle Frame`, $0.00 single variant, prose-only body_html —
  the second Kinesis listing to set this trap. `product_type` and the variant list
  beat the title.
- **`Frankset`** = frameset + crankset (Otso), stated outright in its own
  body_html. A portmanteau no generic part-noun list would contain; it reads as a
  model name until the page is open. Added to `PART_EXTRA_RX`.

#### A live regional storefront beats a Wayback snapshot

Round 8 handled a Shopify Markets 404 with Wayback. Round 9 did better: Raleigh
Motus 404'd on `www`, `en-gb` **and** `en-nl`, but `en-int` served the full live
spec table. The handle was confirmed first via `<region>/products.json`, which
answers even when the product page does not.

Pitfall reordered accordingly — **try every region prefix before Wayback**. A
snapshot is not just second-best; it may predate the model year being recorded,
so it can be quietly wrong in a way a live page cannot.

#### The frameset inconsistency recurred, as predicted

p1 stored Production Privee SHAN 6 as a Frame-only record (correctly: product_type
"Frames", shock-only variants, fork noted sold-separately, all other categories
left empty). In the same round, other workers `/skip`ped their framesets. The
validator fix means the Frame-only submission now saves cleanly instead of
bouncing — so both behaviours "work", and the corpus keeps acquiring some
framesets and rejecting others at random depending on who drew the item.
**This is a product decision that has now gone three rounds undecided.**

#### Operational: a stale claim can idle the whole team

The round's last item (Raleigh Motus) had photos in and a details claim held by a
worker that had already gone idle. `/next` reported `in_flight` to everyone else,
so all six workers sat idle waiting on one item whose owner was gone. The 900 s
`CLAIM_TTL` would have cleared it eventually; `POST /release` cleared it at once.
**Second time the round tail has gone quiet this way** — worth an automatic
release when a claim's worker has been idle, rather than waiting out the TTL.

### Round 10 — 2026-07-31 · 40 bikes · **33 saved, 7 skipped, 0 validator rejections**

#### The skiplist turned a bad fetch into permanent data loss

The round-7 skip-persistence fix had a flaw I did not see when writing it. A skip
was treated as a settled fact about the product — but round 10 skipped **Otso
Warakin Stainless**, a genuine complete bike, purely because Otso runs a
client-rendered Shogun page. Persisting that would have excluded a real bike from
**every future round**, permanently, on the strength of one failed fetch.

The distinction the original design missed: *"this is not a complete bike"* is a
fact about the product and safe to remember forever; *"I could not fetch the
page"* is a fact about one attempt and must expire. `RETRYABLE_SKIP_RX` now sends
the second kind back to the queue and prints what it withheld. Audited all 15
previously-persisted skips — all genuinely settled, so nothing had been lost yet.

**Generalise: any cache of negative results has to distinguish "false" from "not
determined".** Caching the second as the first is silent, permanent, and grows.

Note the agent's skip was defensible on its own terms — the guidance said skip
non-researchable items, and it explained itself precisely enough that the reason
text made the fix possible. The bug was mine.

#### Related: the agent should not have had to skip it at all

Otso is the *known* Shogun brand, with two proven routes already in the briefing
(dealer spec page, `/pages/<model>-overview`) found on earlier Otso bikes in
rounds 8 and 9. The per-brand guidance existed; it just did not reach this item.
Worth stating outright in the briefing: **for a brand already known to be
client-rendered, a fetch failure is not grounds to skip — the dealer route is.**

#### `product_type` lies too — a rule written in round 9 corrected in round 10

Round 9 concluded "`product_type` beats the title" after Kinesis "Racelight T2
Bike" turned out to be `product_type: Bicycle Frame`. Round 10 broke it: Kinesis
**"Racelight T3 Bike" is `product_type: Bicycle` and is still a frameset** — same
brand, adjacent model, opposite value. (Chromag's Primer was already a known case:
`product_type: Bicycles`, nine frame-only variants.)

Replacing one unreliable field with another is not a fix. The rule is now
**corroborate, take two signals**, and the ones that have actually held are:
$0.00 / single "Default Title" variant · frame-only weight (~2.9 kg) · body_html
describing only tubeset/geometry or saying "frame" outright · no groupset named
anywhere. d1 caught the T3 on price + body_html wording after `product_type` said
"Bicycle".

#### Two new listing patterns

- `oldermodels-` handle prefix (Knolly) = archive listing, like Chromag's
  `Bike Archive` tag.
- **A trailer is not a bicycle.** Pashley's Euroload is `product_type: Carrier
  Cycle` but has no frame, drivetrain or wheels of its own. `product_type` is a
  strong signal, not proof of being a bike.

### Round 11 (final) — 2026-07-31 · 40 bikes

#### Both of this round's fixes were validated by the next round's work

Rare to get this cleanly, so it is worth recording as evidence rather than hope:

- **The "corroborate, don't trust one field" rule prevented a false skip.**
  Chromag Wideangle showed $0.00 and a `[Bike Archive]` SKU — two of the frameset
  tells — and under the old single-signal rule would plausibly have been skipped.
  Its **14.49 kg weight contradicted the ~2.9 kg frame-only pattern** and the page
  carried a real "G2 Build" component table, so it was correctly stored as an
  archived complete bike. Kinesis Tripster ACE went the same way: $0.00 listing,
  but a real "Bike Build List" naming a full groupset. **The signal that resolved
  both was weight** — the cheapest, most decisive one, and it was only in the rule
  because the round-10 falsification forced a rewrite.
- **The retryable-skip fix returned the bike it was written for.** Otso Warakin
  Stainless — mis-skipped in round 10 by my own tooling, which would have retired
  it permanently — came back in round 11 and was researched properly via the
  known-good `/pages/warakin-overview` sub-page, without re-fetching the Shogun
  product page. The fix worked end to end: not persisted, re-queued, resolved.

#### Template bleed confirmed on a second brand

d3 found it on Priority (a Carmen page describing "the Cooper's diamond frame").
d4 hit it on Chromag: the Wideangle build table lists 29" Phase30 rims while the
page's own copy calls it a 27.5" bike — Rootdown-sibling bleed. Recorded as
published and flagged, not silently resolved. **Two unrelated brands means this is
a category of hazard, not a Priority quirk.**

#### Raleigh: three agents, one brand, three different answers

`www` and `en-nl` dead in all reports; `en-gb` and `en-int` each served the full
spec in at least one. Which region answers is **not stable across bikes or time**.
The rule is to iterate the whole prefix list, not to reuse last round's winner —
after I twice encoded a specific answer ("unreachable, use a reseller", then
"works via en-int") and was corrected both times.

## Known gaps to fix in a later round

1. **No truthfulness gate.** The validator checks shape, not whether the spec is
   real. Candidate: cross-check that `source_urls` contains a manufacturer domain
   matching the brand, and flag when the only source is a forum/community page.
2. **No duplicate-identity check.** Should compare brand+model case-insensitively
   against `bike`, and flag when one model string is a prefix/suffix of a stored
   one for the same brand (needs judgement — "Arise SG Apex" vs "Arise" are
   genuinely different bikes).
3. **Frameset policy is still undecided — the validator no longer forces the issue.**
   Round 8 removed the harm (a well-documented frameset is no longer bounced, so
   nobody has to pad one to save it), but it did NOT decide whether framesets
   *should* be stored. Current agent behaviour is unchanged: they `/skip`. The two
   are now at least coherent rather than contradictory.

   The inconsistency is real and visible in the data: round 7 stored Chromag
   Stylus as a frame-only record while round 8 skipped Stylus 2018 and 2019.
   Same brand, same product family, opposite outcomes. **This needs a product
   decision, not a pipeline default** — framesets are real products people search
   for, but a frame-only record in a bike-search app may read as a broken bike.
   Whichever way it goes, the rule that must never bend is: no reconstructing a
   build for a frameset.
4. **Duplicate rows already in the DB are still there.** Round 7 found two pairs
   stored under listing-variant names — `Engwe EP-2 Pro` / `EP-2 Pro (Battery
   Pack)` (34 vs 64 spec rows) and `Heybike Mars 3.0` / `Mars 3.0 (VIP only)`
   (80 vs 46). New ones are prevented by the identity dedupe, but merging these
   loses data and the *better* record is the badly-named one in the Engwe pair,
   so it needs a human decision. Left for the user.
5. **`migrate_bike_details.py` has never been run on this DB.** There are no
   `brand_norm`/`model_norm` columns, so nothing structurally prevents duplicate
   identities — every guard above is in `round_prep.py`, i.e. advisory. A bike
   inserted by any other path can still mint a duplicate.
