"""Shared config and helpers for the backfill pipeline services."""
import sys
from pathlib import Path

# This pipeline was archived to docs/bikes/pipeline/. The app it reads and
# writes (cache.db, app/models.py, app/prompts) still lives in backend/.
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

PIPELINE = Path(__file__).resolve().parent
STATE = PIPELINE / "state"
STATE.mkdir(exist_ok=True)

BIKES_FILE = PIPELINE / "bikes.txt"
ROUNDS_FILE = STATE / "rounds.json"

PORTS = {
    "coordinator": 9101,
    "researcher_details": 9102,
    "researcher_photos": 9103,
    "validator": 9104,
    "db_saver": 9105,
}
URL = {name: f"http://127.0.0.1:{port}" for name, port in PORTS.items()}

# The 8 component categories, mirroring bike_details_finder.DETAIL_CATEGORIES,
# plus a 9th added after round 1: motor/battery/charger/display had no home, so
# the same fact landed under Drivetrain on one e-bike and Accessories on another.
# It is OPTIONAL — a bike with no motor returns [] for it.
DETAIL_CATEGORIES = [
    ("Frame", "frame"),
    ("Drivetrain", "drivetrain"),
    ("Brakes", "brakes"),
    ("Wheels", "wheels"),
    ("Cockpit", "cockpit"),
    ("Saddle & Seatpost", "saddle"),
    ("Lighting", "lighting"),
    ("Accessories", "accessories"),
    ("Electric / Powertrain", "electric"),
]

# Round-1 finding: fetch reliability, not prompt quality, is the bottleneck.
# Five of eight manufacturer pages yielded no spec table.
SOURCE_LADDER = [
    "0. FETCH FIRST, SEARCH ONLY WHEN THE URL IS UNKNOWN. WebSearch budget is "
    "per-session and finite (round 2 exhausted 200/200). Guessing a product URL "
    "and fetching it is free; searching for it is not.",
    "1a. SHOPIFY HANDLE INDEX — fetch `<site>/products.json?limit=250` ONCE per "
    "brand and cache it. It lists every product's handle and true title, which "
    "ends handle-guessing: round 3 found `lasal` (not la-sal-peak), `juice-2023`, "
    "`level-3-commuter-ebike`, and a `bombtrack-` prefix on everything. Stop "
    "guessing after the first 404 and pull the index.",
    "1b. SHOPIFY .json — append `.json` to /products/<handle>. Always gives the "
    "true title/handle; gives the FULL spec table only on some brands (Bombtrack "
    "yes; Ari, Aventon, Brooklyn, Chromag put marketing prose in body_html and "
    "keep the spec table in the rendered page instead).",
    "1c. EMBEDDED SPEC BLOBS in the product page HTML — often richer than the JSON "
    "API. Grep the raw HTML for: `const data = [` (Ari — the entire build ladder, "
    "~29 fields per build), `class='tech-spec-group'` (Aventon — full factory "
    "table incl. the e-bike system block), or tag-strip a window around a known "
    "component string (Brooklyn, Chromag).",
    "1d. USE curl FROM BASH, NOT WebFetch, for all of the above. It costs no "
    "budget and returns raw HTML rather than a lossy markdown conversion — which "
    "is what makes the embedded-blob extraction above possible at all.",
    "1e. Manufacturer specification page (when it renders server-side).",
    "1f. WAYBACK for discontinued models — `archive.org/wayback/available?url=..`. "
    "Chromag archives retired bikes and strips the build list from the live page; a "
    "snapshot of the manufacturer's OWN page beats any third-party source. Free.",
    "1g. READ `product_type` FROM THE INDEX. It separates a complete bike from a "
    "frameset, spare part, outlet listing or accessory bundle before you fetch "
    "anything — Crust's `Frames` vs `Completes` flags a frame-only product up front, "
    "and it is what stops `Arise` matching `Arise Bearing Set`.",
    "2. bikes.fan/<brand>-<model>-<year>/ or bikes.fan/?s=<model> — fetches "
    "cleanly, carries the complete factory table. Saved both Brooklyn bikes whose "
    "own site publishes only marketing prose.",
    "3. Vital MTB /product/guide/ — full spec tables, fetches reliably.",
    "4. A stocking dealer's product page: Tradeinn/Bikeinn, Bicycle Habitat and "
    "other Smartetailing shops, opticycles.com, and Shopify dealers such as "
    "ezbike.ca and bicyclewarehouse.com (ezbike.ca was the ONLY source with the "
    "full Aventon Current table).",
    "5. A reputable review with a full spec table.",
    "SNIPPET-ONLY (403 to WebFetch — read the search snippet, do not spend a fetch): "
    "99spokes.com, roadbikedatabase.com, bike24.com, performancebike.com, mtbdatabase.com.",
    "NEVER as primary: forum or community custom-build pages. An earlier run "
    "produced a fully fabricated spec exactly this way.",
]

SHOPIFY_PITFALLS = [
    "ASSUME SHOPIFY FIRST. A browser scout probed 13 unrelated bike brands and all 13 "
    "served a live, unauthenticated products.json: knollybikes, aribikes, aventon, "
    "bombtrack, chromagbikes, crustbikes, earlyrider, engwe, konaworld, lectricebikes, "
    "linusbike, marinbikes, murfelectricbikes. Boutique and direct-to-consumer bike "
    "brands are overwhelmingly Shopify. `curl https://<domain>/products.json?limit=250"
    "&page=N` should be your FIRST move on any unknown brand — one request returns every "
    "product's title, handle, product_type and body_html (which often holds the factory "
    "spec table). No scraping, no 403.",
    "HANDLES DO NOT MATCH TITLES. Ari's 'Wire Peak 2.0' is at /products/wire-peak; "
    "Chromag's current 'Rootdown' is at /products/rootdown-2024 with NO bare "
    "/products/rootdown; Bombtrack spells out 'plus' as "
    "/products/bombtrack-beyond-plus-midtail. Never guess past one attempt — read the index.",
    "MODEL YEARS ARE SEPARATE PRODUCTS. Chromag keeps rootdown-2024, rootdown-2022, "
    "rootdown-21, rootdown-2020 and frames-rootdown-19 all live simultaneously. Picking "
    "the wrong one silently yields a wrong-year spec that looks perfectly valid.",
    "READ THE VARIANT LIST BEFORE ASSERTING A GROUPSET. Chromag sells frame-only and "
    "complete builds as VARIANTS OF ONE PRODUCT, so the product being a 'bike' does not "
    "mean the price you are looking at includes a drivetrain.",
    "FRAMESETS: product_type 'Frames' means there is no factory groupset or wheelset at "
    "all (Crust Evasion and Evasion Lite, for example). Filling in a build kit for one of "
    "these is fabrication, not research.",
    "product_type IS NOT ALWAYS SUFFICIENT. Chromag's Primer is product_type 'Bicycles' "
    "yet all nine of its variants are FRAME ONLY. On Chromag the variant list, not the "
    "type, is the frame-vs-complete signal. Check variants before asserting a groupset.",
    "A STALE HANDLE IS NOT A WRONG PRODUCT. Marin's '2024 DSX FS' lives at handle "
    "`2023-dsx-fs`. The TITLE is authoritative; the slug is legacy. Do not 'correct' a "
    "title/handle mismatch into picking a different product.",
    "BUNDLE AND REGIONAL LISTINGS: Lectric lists one trike under ~9 titles padded with "
    "'+ FREE Cargo Package ($455 Value)' plus `[CA]` duplicates. Always take the plain "
    "base listing, never a promo bundle.",
    "REGIONAL SPLITS CUT BOTH WAYS. Engwe's ENGINE PRO is US-only (engwe-bikes.com) and "
    "Engine X Combo is EU-only (engwe.com). Neither domain is 'the' catalog — absence "
    "from one storefront proves nothing.",
    "GREP CASE-INSENSITIVELY, ALWAYS (`grep -o -i -E`). Case-sensitive probes twice "
    "reported 'no spec table' on Heybike pages that had one, nearly costing two good "
    "records.",
    "LOOK FOR A SPEC SPREADSHEET BEFORE FALLING DOWN THE LADDER. Grep body_html for "
    "`.xlsx`, `.pdf` or `.csv` links — Detroit Bikes links 2020_Bike_Specs.xlsx with one "
    "column per model, which yielded a complete build after the live page had no spec "
    "text at all. A manufacturer's own spreadsheet beats every web page.",
    "THE SPEC BLOB'S CLASS NAME IS PER-THEME — GREP FOR THE WORDS, NOT THE MARKUP "
    "(round 6, the most reusable finding so far). `tech-spec-group` is Aventon-specific "
    "and `const data = [` is Ari-specific; the same trick reappears under a different "
    "name on every theme (Kinesis `metafield-single_line_text_field`, Murf `tsd__item-text`, "
    "Pedego `Specs-value` in an off-canvas drawer, Aventon `techSpecs.data`). Do not "
    "collect class names — grep the RENDERED html for the literal words 'Specifications', "
    "'Motor', 'Battery', 'Frame:' with `grep -aob`, then `dd` a window around the byte "
    "offset. This finds the table on themes nobody has catalogued yet.",
    "A VERSION SUFFIX CAN MEAN A DIFFERENT PRODUCT, NOT A REVISION (round 10, Engwe). "
    "M20 (engwe.com) and 'M20 2.0' (engwe-bikes.com) read as a model and its update, but "
    "diffing the tables showed iron vs aluminium frame, 750W/1200W peak vs 250W motor, "
    "75 vs 55 Nm, hydraulic vs mechanical brakes, 52V15.6Ah vs 48V13Ah. Note the REGIONAL "
    "DOMAIN SPLIT is the tell — the same nameplate is used for different bikes in "
    "different markets. Together with the Lectric 750/500 case: a name difference is never "
    "evidence of a spec relationship in EITHER direction. Diff the tables, every time.",
    "AN INTERNALLY CONTRADICTORY MANUFACTURER TABLE IS NOT THE SAME AS TWO SOURCES "
    "DISAGREEING (round 10, Marin Rift Zone E XR: the 'front hub' row lists 148x12mm with "
    "an XD driver and the 'rear hub' row lists 110x15mm — the rows are transposed). "
    "Record it AS PUBLISHED and flag it loudly in the description. Do NOT silently "
    "un-transpose it: you would be publishing a guess as a manufacturer spec, and if the "
    "guess is wrong nobody can tell, because the source now disagrees with the record.",
    "FRAME-VS-COMPLETE: NO SINGLE FIELD IS RELIABLE — CORROBORATE. The title lies "
    "(Kinesis 'Racelight T2 Bike' is product_type 'Bicycle Frame'). **product_type lies "
    "too**: round 10's Kinesis 'Racelight T3 Bike' is product_type 'Bicycle' and is still "
    "a frameset — same brand, adjacent model, opposite value. Chromag's Primer is "
    "product_type 'Bicycles' with nine frame-only variants. The signals that actually "
    "held up: a **$0.00 / single 'Default Title' variant**, a **frame-only weight** "
    "(~2.9 kg), body_html that **describes only tubeset/geometry** or calls the thing a "
    "'frame'/'frameset' outright, and **no groupset named anywhere**. Take two before "
    "deciding. Watch for portmanteaus: Otso's 'Voytek Frankset' is Frameset + Crankset.",
    "THE SPEC MAY LIVE ON A SEPARATE /pages/ SUB-PAGE, NOT THE PRODUCT PAGE (round 9, "
    "Pure Cycles). `/products/original-21154` carries no spec at all — not even marketing "
    "body_html — while `/pages/pure-fix-original-specs` has the full build. Before "
    "concluding a brand publishes nothing, search the site for a `/pages/...spec` route. "
    "An empty product page is not proof of an empty catalogue.",
    "A FETCH FAILURE IS NEVER A REASON TO SKIP — 'not researchable by me right now' is "
    "not 'not a bike'. Round 10 skipped the Otso Warakin Stainless, a real complete bike, "
    "because Otso's page is client-rendered — on a brand ALREADY KNOWN to be Shogun, with "
    "two proven routes in this very list (dealer spec page, /pages/<model>-overview). "
    "Skip means the product is a frameset, a part, a deposit, an archive listing or not a "
    "bicycle. If you simply cannot reach the spec, exhaust the chain (region prefix -> "
    "regional subdomain -> dealer -> WebSearch -> Wayback) and, if it still fails, say so "
    "in the skip reason using the words 'client-side' / 'could not fetch' so the "
    "coordinator knows to re-queue it rather than retiring it permanently.",
    "A REGIONAL STOREFRONT MAY SERVER-RENDER WHAT THE MAIN DOMAIN DOES NOT — TRY THE "
    "SUBDOMAIN BEFORE A DEALER (round 10, Chromag). chromagbikes.com returns no component "
    "text at all for some products (genuinely empty, not even a Shogun mount div), while "
    "**us.**chromagbikes.com server-renders the full 'Builds & Specs' section for the SAME "
    "/products/<handle> path — a complete build for zero search spend. Same principle as "
    "the region-prefix rule, one level up: keep the path, change the host. Storefronts are "
    "built per region and they do not always share a rendering strategy. Try "
    "`us.`/`eu.`/`uk.` and other regional hosts before falling to a dealer or WebSearch.",
    "AN AUTHORIZED RESELLER'S SHOPIFY .json CAN RESCUE A CLIENT-RENDERED SITE (round 9, "
    "Linus Mixte 3i). When the manufacturer runs Shogun/JS-only and no spec exists "
    "on-site at all, a dealer selling the IDENTICAL SKU often runs plain Shopify — e.g. "
    "bikesonwheels.com/products/mixte-3i.json carried the full breakdown. Confirm the SKU "
    "matches, and say in the description that the spec came from a reseller. Better than "
    "a forum post: it is a structured product record, not someone's recollection. A "
    "dealer's plain HTML spec page works the same way (Campfire Cycling for Otso Voytek). "
    "THIS IS NOW THE DEFAULT MOVE for a client-rendered brand — try a dealer before "
    "WebSearch, since Shogun/JS-only sites recur per BRAND, not per product. It is also "
    "the LAST RESORT when a manufacturer is genuinely unreachable — an authorized reseller "
    "(e-bikeshop.co.uk) carried full spec tables for a Raleigh SKU when raleigh.co.uk "
    "404'd. Note the manufacturer access failure in the description when you do this. "
    "BUT VERIFY 'UNREACHABLE' FIRST — AND DO NOT TRUST ONE AGENT'S REGION RESULT. Raleigh "
    "produced THREE conflicting reports on the same brand within one round: every pattern "
    "404s (-> reseller), `en-int` serves the full spec, `en-gb` serves it while `en-int` "
    "was not tried. Confirmed dead in all reports: bare `www.raleigh.co.uk` and `en-nl`. "
    "Confirmed working in at least one report each: `en-gb`, `en-int`. Conclusion: which "
    "region answers is NOT stable across bikes or time, so **iterate the whole prefix "
    "list** (`en-gb`, `en-int`, `en-us`, none) rather than reusing the one that worked "
    "last time, and treat 'this site is dead' as a claim needing all of them tried. A "
    "reseller is a transcription; the manufacturer is the source.",
    "A MANUFACTURER PAGE CAN DESCRIBE A DIFFERENT MODEL — TEMPLATE COPY-PASTE IS REAL "
    "(round 8, Priority). The Brilliant Carmen page's '03' feature card literally reads "
    "'the Cooper's diamond frame' — leftover body copy from the sibling Brilliant Cooper "
    "template. 'Record what the manufacturer publishes' assumes the page is ABOUT this "
    "model; when a line names another model, that line is contamination, not a spec. "
    "Drop it and verify that component on its own product page. Brands that share a "
    "template across a family (Priority) are where this happens.",
    "IF `.json` 404s, TRY THE CANONICAL HOST BEFORE GIVING UP — drop or add `www.` "
    "(round 8, Kinesis). Two 404s that looked like missing products were host-redirect "
    "artefacts with real content behind them.",
    "A 404 ON A HANDLE THAT products.json LISTS IS PROBABLY A REGIONAL BLOCK, NOT A DEAD "
    "PRODUCT (round 8, Marin Pine Mountain 2). Shopify Markets serves 404 out-of-region. "
    "IN ORDER: (1) try another REGION PREFIX — `/en-int/`, `/en-nl/`, `/en-gb/`, no "
    "prefix. Round 9's Raleigh Motus 404'd on www, en-gb AND en-nl, but `en-int` served "
    "the full live spec table. Confirm the handle first via `<region>/products.json`, "
    "which answers even when the product page does not. (2) Only if every region fails, "
    "fall back to Wayback. A live regional storefront beats a snapshot — it is current, "
    "and the snapshot may predate the model year you are recording.",
    "PHOTOS: IF `/products/<handle>.json` 404s, PULL images[] FROM THE BULK "
    "`products.json` INSTEAD (round 8, Marin Pine Mountain 1). The bulk index carries the "
    "same image records and is often served when the per-product endpoint is not.",
    "TRY body_html TEXT BEFORE THE RENDERED-HTML GREP — IT IS ONE FETCH, NOT TWO. "
    "Bombtrack and Kinesis publish a genuinely complete flat spec list in `.json` "
    "body_html (Kinesis as a metafield-single_line_text_field array). Only fall through "
    "to fetching and grepping the rendered page when body_html is marketing prose.",
    "ELECTRONIC SHIFTING IS NOT AN E-BIKE. Shimano Di2 / SRAM AXS have a battery and a "
    "charger but no motor. Do NOT populate 'Electric / Powertrain' for them — that "
    "category means pedal-assist. Put the Di2/AXS battery and charger under Drivetrain "
    "and say so in the description. A Knolly Chilcotin 155 XT Di2 is a mechanical MTB.",
    "SOME BRANDS PUBLISH NO TABLE AT ALL — READ THE NARRATIVE CARDS (round 7, Priority). "
    "On Priority's 600HXT and APOLLO GRAVEL the entire drivetrain/brake/suspension spec "
    "lives only in numbered marketing cards: grep `class=\"bike-feature_card-text\"` and "
    "read the surrounding <h4>/<p> pairs. Twice now on this brand. 'No <table> found' is "
    "not the same as 'no spec published' — check the prose layout before falling back to "
    "search. Knolly by contrast uses plain `<table class=\"responsive-table\">` blocks.",
    "PEDEGO-STYLE FACTORY SPEC PDF: the same drawer often links a downloadable sheet at "
    "`.../cdn/shop/files/FS22_-_<slug>.pdf`. Like the .xlsx case, the manufacturer's own "
    "document beats the page.",
    "LIVE GOOGLE SHEET BEHIND AN ACCORDION (round 6, Otso/Heybike/Pedego). When the spec "
    "is neither in body_html nor a static JS blob, the page may fetch it at runtime from "
    "a public sheet. Grep the RENDERED html for a spreadsheet id and fetch "
    "`docs.google.com/spreadsheets/d/<id>/gviz/tq?tqx=out:json&tq&gid=<gid>` directly — "
    "that is the authoritative table, costs no search budget, and skips WebFetch entirely.",
    "USE A REAL BROWSER UA WHEN GREPPING RENDERED HTML (`curl -sL -A Mozilla/5.0...`). "
    "Several hosts 301 or serve nothing at all to a bare curl, which reads as 'no spec "
    "table' when the table is right there.",
    "SHOGUN PAGE BUILDER = CLIENT-SIDE ONLY, GIVE UP EARLY (round 6, otsobikes.com). "
    "body_html and the rendered description are an empty `shogun-root` mount div, and the "
    "JSON-LD FAQ answers for 'Build Specs'/'Frame Specs' are empty strings. Neither curl "
    "nor WebFetch can ever see the spec. Recognise the empty mount div and go straight to "
    "search / a launch article citing the manufacturer's sheet — do not keep re-fetching.",
    "SPEC-AS-IMAGE is a distinct failure mode from 'no source' (Engwe, partly Heybike). "
    "When the spec exists only inside a graphic, guess `bikes.fan/<brand>-<model>-<year>/` "
    "— it returned 200 first try for Engwe and carried motor torque and fork travel.",
]

SIBLING_RULE = (
    "Sibling builds (Beyond 1/2, Level 3 / Level 3 Step-Through) are cheap to "
    "produce by patching a previous blob — but DIFF THE REAL SPEC TABLES FIRST. "
    "Round 3: the Aventon ST differs only in rider height, frame style and an IPX "
    "rating, so patching was right; Bombtrack Beyond 2 differs in drivetrain, "
    "hub, lights, tyres and rack, so a blind patch would have been badly wrong. "
    "ROUND 8, THE SHARPEST CASE YET: 'Lectric XP Trike2 750 Stratus White' and "
    "'Lectric XP Trike2 Stratus White' differ ONLY by a '750' in the title and look "
    "like the same bike under a naming variant. They are different motor tiers — "
    "750W/1310W peak/85Nm/torque sensor/840Wh/70mi at $1799 versus 500W/1092W/65Nm/"
    "cadence sensor/624Wh/50mi at $1499 — sharing frame, brakes, wheels and tyres. "
    "Patching one from the other would have produced a confidently wrong record. "
    "TEST: treat two listings as the same spec ONLY when the PRICE and the rendered "
    "Specifications section both match exactly. A missing number in a title is a "
    "spec difference until the page proves otherwise."
)

EXTRA_SUBCATEGORIES_RULE = (
    "The subcategories named in each category prompt are a MINIMUM, not a closed "
    "list. Add whatever the bike actually has — Rear Shock and Headset under Frame, "
    "Shifter and Chainguide under Drivetrain, and so on. A full-suspension or "
    "e-bike record is materially worse without them, and they store fine."
)

BUILD_KIT_RULE = (
    "If the model name does not identify a single build (e.g. a frame sold with a "
    "ladder of build kits), spec the manufacturer's STOCK or ENTRY complete build "
    "and name which build you specced in the description. Do not mix parts from "
    "different build kits. If the product is genuinely frame-only, submit the Frame "
    "category (plus the fork it is designed around, noting it is sold separately) "
    "and leave the other categories empty — never reconstruct a build from someone's "
    "personal bike."
)

# Category prompts live in the app; the 9th category (Electric / Powertrain) was
# added by this pipeline and travelled with it, so look in the local overlay first
# and fall back to the app's own prompt directory.
APP_PROMPTS = BACKEND / "app" / "prompts"
LOCAL_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def prompt_path(name: str) -> Path:
    """Resolve a prompt file: local overlay wins, app directory is the fallback."""
    local = LOCAL_PROMPTS / name
    return local if local.exists() else APP_PROMPTS / name


PROMPTS_DIR = APP_PROMPTS  # kept for callers that only need the app directory


def key(brand: str, model: str) -> str:
    return f"{brand.strip().lower()}|{model.strip().lower()}"
