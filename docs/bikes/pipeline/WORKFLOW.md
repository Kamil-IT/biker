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

```bash
cd backend
.venv/Scripts/python.exe pipeline/run_all.py     # starts all five
curl http://127.0.0.1:9101/status
curl http://127.0.0.1:9101/next                  # claim a bike
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

## Known gaps to fix in a later round

1. **No truthfulness gate.** The validator checks shape, not whether the spec is
   real. Candidate: cross-check that `source_urls` contains a manufacturer domain
   matching the brand, and flag when the only source is a forum/community page.
2. **No duplicate-identity check.** Should compare brand+model case-insensitively
   against `bike`, and flag when one model string is a prefix/suffix of a stored
   one for the same brand (needs judgement — "Arise SG Apex" vs "Arise" are
   genuinely different bikes).
3. **No frameset detection.** A frameset produces an honest tree where every
   element reads "not included"; it should be skipped, not stored.
