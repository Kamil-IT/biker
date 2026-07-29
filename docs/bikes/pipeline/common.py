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
    "SPEC-AS-IMAGE is a distinct failure mode from 'no source' (Engwe, partly Heybike). "
    "When the spec exists only inside a graphic, guess `bikes.fan/<brand>-<model>-<year>/` "
    "— it returned 200 first try for Engwe and carried motor torque and fork travel.",
]

SIBLING_RULE = (
    "Sibling builds (Beyond 1/2, Level 3 / Level 3 Step-Through) are cheap to "
    "produce by patching a previous blob — but DIFF THE REAL SPEC TABLES FIRST. "
    "Round 3: the Aventon ST differs only in rider height, frame style and an IPX "
    "rating, so patching was right; Bombtrack Beyond 2 differs in drivetrain, "
    "hub, lights, tyres and rack, so a blind patch would have been badly wrong."
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
