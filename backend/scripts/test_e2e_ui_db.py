"""End-to-end UI <-> DB tests.

Drive the REAL frontend (Vite dev server on :5173) with a real browser
(patchright / Playwright), then query cache.db directly to prove every UI action
persisted to the correct table. This is the "do something in the UI, then check
the DB" style of e2e the project asked for.

Cases
-----
  E1  Search (brand + type, NO model)  -> search_cache + search_bike_rating_cache
      + bike. The card count / scores on screen must equal the rows written.
      No model is supplied on purpose so the DB-first branch (needs brand AND
      model) is skipped and the AI/generic path actually writes the tables.

  E3  Open the top result   -> bike_detail + bike_detail_component (+ photos)
  E4  Spec-tree round-trip  -> #spec rows rendered == #non-NULL spec rows in DB
  E5  Expert review         -> endpoint_req_to_body_cache '/v1/bike/review'
                               (only cached when refs/sources exist -> so if the
                               UI shows sources, the row MUST be there)
  E6  Offers (4 sources)    -> endpoint_req_to_body_cache offer endpoints; every
                               cached offer response is non-empty (empty is never
                               cached) and every stored price shows on the page.

  E2  DB-first short-circuit -> re-search with the top bike's brand+model+a huge
      price_max. That MISSES the generic cache (new key) yet must NOT add a new
      '/v1/bike/search' row -> proves it returned from search_cache, skipping AI.

  E8  Cascade delete        -> delete the test bike row; all children gone and
      PRAGMA foreign_key_check clean (proves cache.py's PRAGMA foreign_keys=ON).

Prerequisites (this script does NOT start them):
  backend   uvicorn app.main:app --reload --port 8000
  frontend  npm run dev                    (:5173, proxies /v1 -> :8000)

Run
---
  .venv/Scripts/python scripts/test_e2e_ui_db.py
  .venv/Scripts/python scripts/test_e2e_ui_db.py --brand Trek --type MTB --headed
  .venv/Scripts/python scripts/test_e2e_ui_db.py --no-details   # E1/E2 only, fast
  .venv/Scripts/python scripts/test_e2e_ui_db.py --skip-cascade # keep test data

NOTE: a cold run hits the live Anthropic API (search scoring + 8 detail web
searches + review + 4 offer searches) — minutes of wall-clock and real spend. A
warm cache.db serves most of it instantly; the assertions validate UI<->DB
consistency either way.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import urllib.request
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "cache.db"

OFFER_ENDPOINTS = ("/v1/bike/offer", "/v1/bike/ceneo", "/v1/bike/decathlon", "/v1/bike/used")

# card / details / component selectors (verified against the frontend source)
SEL_CARD = "button[aria-label^='View specifications for']"
SEL_SUBMIT = "button[type='submit']"
SEL_CAT_SECTION = "section[aria-labelledby^='cat-']"
SEL_CAT_HEADER = "h2[id^='cat-']"
SEL_SPEC_ROW = "section[aria-labelledby^='cat-'] dl > div"
SEL_ELEMENT = "button[aria-label^='View equipment details for ']"
SEL_REVIEW_SCORE = "span[aria-label^='Review score ']"
SEL_REVIEW_SRC = "a span[aria-label$='out of 5 stars']"
SEL_DETAILS_ERROR = "div[role='alert']"


# ── tiny assertion harness ──────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []  # (case, level, status, detail)

    def hard(self, case: str, ok: bool, detail: str) -> bool:
        self.rows.append((case, "HARD", "PASS" if ok else "FAIL", detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {case}: {detail}")
        return ok

    def soft(self, case: str, ok: bool, detail: str) -> None:
        self.rows.append((case, "SOFT", "PASS" if ok else "WARN", detail))
        print(f"  [{'PASS' if ok else 'WARN'}] {case}: {detail}")

    def failed(self) -> list[tuple[str, str, str, str]]:
        return [r for r in self.rows if r[1] == "HARD" and r[2] == "FAIL"]

    def summary(self) -> None:
        hard = [r for r in self.rows if r[1] == "HARD"]
        passed = sum(1 for r in hard if r[2] == "PASS")
        warns = sum(1 for r in self.rows if r[2] == "WARN")
        print("\n" + "=" * 60)
        print(f"HARD checks: {passed}/{len(hard)} passed   |   soft warnings: {warns}")
        for c, _lvl, st, d in self.failed():
            print(f"  FAIL {c}: {d}")
        print("=" * 60)


# ── db helpers (fresh connection per read; WAL => sees latest commit) ────────
def rows(sql: str, params: tuple = ()) -> list[tuple]:
    with closing(sqlite3.connect(str(DB_PATH))) as con:
        con.execute("PRAGMA foreign_keys=ON")
        return con.execute(sql, params).fetchall()


def scalar(sql: str, params: tuple = ()):
    r = rows(sql, params)
    return r[0][0] if r else None


def norm(s: str) -> str:
    return s.strip().lower()


def nfields(company: str, model: str) -> str:
    """Replicate cache._normalise({'company':.., 'model':..})."""
    return json.dumps(
        {"company": company.strip().lower(), "model": model.strip().lower()},
        sort_keys=True,
        separators=(",", ":"),
    )


def build_enriched(brand=None, model=None, bike_type=None, price_max=None) -> str:
    """Replicate SearchRequest.enriched_query() for the fields we set (in order)."""
    parts = []
    if brand:
        parts.append(f"Brand: {brand}")
    if model:
        parts.append(f"Model: {model}")
    if bike_type:
        parts.append(f"Type: {bike_type}")
    if price_max is not None:
        parts.append(f"Max price: {price_max} PLN")
    return ", ".join(parts)


def offer_row_count(endpoint: str) -> int:
    return scalar(
        "SELECT COUNT(*) FROM endpoint_req_to_body_cache WHERE endpoint=?", (endpoint,)
    ) or 0


# ── ui helpers ──────────────────────────────────────────────────────────────
def open_filters(page) -> None:
    # The toggle reads "Filters" when closed; click it only if the brand field
    # isn't already visible.
    if page.locator("#bike-brand").count() == 0 or not page.locator("#bike-brand").is_visible():
        page.get_by_role("button", name="Filters").first.click()
        page.wait_for_selector("#bike-brand", state="visible", timeout=5000)


def do_search(page, base_url, *, brand=None, model=None, bike_type=None,
              price_max=None, timeout_ms) -> int:
    """Fill the search form and submit. Returns the number of result cards."""
    page.goto(base_url, wait_until="domcontentloaded")
    open_filters(page)
    if brand:
        page.fill("#bike-brand", brand)
    if model:
        page.fill("#bike-model", model)
    if bike_type:
        page.select_option("#bike-type", bike_type)
    if price_max is not None:
        page.fill("#bike-price-max", str(price_max))
    page.click(SEL_SUBMIT)
    # Wait for either results or the inline error alert.
    page.wait_for_selector(f"{SEL_CARD}, section[aria-label='Bike recommendations'] div[role='alert']",
                           timeout=timeout_ms)
    return page.locator(SEL_CARD).count()


def card_scores(page) -> list[float]:
    els = page.locator(SEL_CARD)
    out: list[float] = []
    import re
    for i in range(els.count()):
        label = els.nth(i).get_attribute("aria-label") or ""
        m = re.search(r"match score ([\d.]+) out of 10", label)
        if m:
            out.append(round(float(m.group(1)), 1))
    return sorted(out)


# ── the cases ───────────────────────────────────────────────────────────────
def case_search(page, base_url, rep: Report, args) -> tuple[str, str] | None:
    print("\n── E1  Search -> search_cache / search_bike_rating_cache / bike ──")
    enriched = build_enriched(brand=args.brand, bike_type=args.type)
    n_cards = do_search(page, base_url, brand=args.brand, bike_type=args.type,
                        timeout_ms=args.search_timeout)
    if not rep.hard("E1.cards", n_cards > 0, f"{n_cards} result card(s) rendered"):
        return None

    row = rows("SELECT id, time_stored FROM search_cache WHERE query=?", (norm(enriched),))
    if not rep.hard("E1.search_cache", bool(row),
                    f"search_cache row for query {enriched!r}"):
        return None
    sid = row[0][0]

    n_ratings = scalar(
        "SELECT COUNT(*) FROM search_bike_rating_cache WHERE search_cache_id=?", (sid,))
    rep.hard("E1.rating_count", n_ratings == n_cards,
             f"search_bike_rating_cache rows={n_ratings} vs cards={n_cards}")

    db_scores = sorted(round(r[0], 1) for r in rows(
        "SELECT rating FROM search_bike_rating_cache WHERE search_cache_id=?", (sid,)))
    ui_scores = card_scores(page)
    rep.hard("E1.scores", db_scores == ui_scores,
             f"DB ratings {db_scores} == card scores {ui_scores}")

    # Every displayed bike must resolve to a canonical `bike` row via the FK.
    n_bikes = scalar(
        "SELECT COUNT(*) FROM search_bike_rating_cache r JOIN bike b ON b.id=r.bike_id "
        "WHERE r.search_cache_id=?", (sid,))
    rep.hard("E1.bike_fk", n_bikes == n_ratings,
             f"{n_bikes}/{n_ratings} rating rows join to a bike row")

    top = rows(
        "SELECT b.brand, b.model FROM search_bike_rating_cache r JOIN bike b ON b.id=r.bike_id "
        "WHERE r.search_cache_id=? ORDER BY r.display_order, r.id LIMIT 1", (sid,))
    top_bike = (top[0][0], top[0][1]) if top else None
    rep.soft("E1.top_bike", bool(top_bike), f"top result = {top_bike}")
    return top_bike


def case_details(page, rep: Report, top_bike, args) -> None:
    brand, model = top_bike
    print(f"\n── E3/E4  Open details for {brand} {model!r} ──")
    page.locator(SEL_CARD).first.click()
    try:
        page.wait_for_selector(f"{SEL_CAT_SECTION}, {SEL_DETAILS_ERROR}",
                               timeout=args.details_timeout)
    except Exception as exc:  # noqa: BLE001
        rep.hard("E3.loaded", False, f"details view never settled: {exc}")
        return
    if page.locator(SEL_CAT_SECTION).count() == 0:
        rep.hard("E3.loaded", False, "details returned an error alert, no spec tree")
        return

    # bike_detail row for this bike
    bd = rows(
        "SELECT bd.id FROM bike_detail bd JOIN bike b ON b.id=bd.bike_id "
        "WHERE LOWER(b.brand)=? AND LOWER(b.model)=?", (norm(brand), norm(model)))
    if not rep.hard("E3.bike_detail", bool(bd), f"bike_detail row for {brand} {model}"):
        return
    bdid = bd[0][0]

    n_comp = scalar(
        "SELECT COUNT(*) FROM bike_detail_component WHERE bike_detail_id=?", (bdid,))
    rep.hard("E3.components", (n_comp or 0) > 0,
             f"bike_detail_component rows = {n_comp}")

    # UI category names must all exist in the DB category set.
    # The category header carries a Tailwind `uppercase` class, so inner_text()
    # comes back upper-cased while the DB keeps title-case — compare case-folded.
    db_cats = {r[0].lower() for r in rows(
        "SELECT DISTINCT category FROM bike_detail_component WHERE bike_detail_id=?", (bdid,))}
    ui_cats = [page.locator(SEL_CAT_HEADER).nth(i).inner_text().strip()
               for i in range(page.locator(SEL_CAT_HEADER).count())]
    missing = [c for c in ui_cats if c.lower() not in db_cats]
    rep.hard("E3.categories", not missing,
             f"UI categories {ui_cats} all present in DB (missing={missing})")

    n_photos = scalar(
        "SELECT COUNT(*) FROM bike_detail_photos WHERE bike_detail_id=?", (bdid,)) or 0
    rep.soft("E3.photos", True, f"bike_detail_photos rows = {n_photos}")

    # E4  round-trip fidelity: rendered spec rows == non-NULL spec rows in DB.
    db_specs = scalar(
        "SELECT COUNT(*) FROM bike_detail_component "
        "WHERE bike_detail_id=? AND spec_key IS NOT NULL", (bdid,)) or 0
    ui_specs = page.locator(SEL_SPEC_ROW).count()
    rep.hard("E4.spec_roundtrip", db_specs == ui_specs,
             f"DB spec rows={db_specs} == UI spec rows={ui_specs}")

    db_elems = scalar(
        "SELECT COUNT(DISTINCT component_order || '-' || element_order) "
        "FROM bike_detail_component WHERE bike_detail_id=?", (bdid,)) or 0
    ui_elems = page.locator(SEL_ELEMENT).count()
    rep.soft("E4.elements", db_elems == ui_elems,
             f"DB elements={db_elems} vs UI element links={ui_elems}")


def case_review_offers(page, rep: Report, top_bike, args) -> None:
    brand, model = top_bike
    key = nfields(brand, model)
    print(f"\n── E5/E6  Review + offers for {brand} {model!r} ──")

    # Give the parallel review/offer fetches a chance to settle.
    for sel in (SEL_REVIEW_SCORE, "text=Offers"):
        try:
            page.wait_for_selector(sel, timeout=args.settle_timeout)
        except Exception:  # noqa: BLE001 — either may legitimately never appear
            pass
    html = page.content()
    # The DOM renders prices with non-breaking spaces; stored JSON uses plain
    # ones. Strip ALL whitespace from both sides before substring-matching.
    html_sqz = "".join(html.split())

    # E5 review ---------------------------------------------------------------
    rev = rows(
        "SELECT response FROM endpoint_req_to_body_cache WHERE endpoint='/v1/bike/review' "
        "AND request=?", (key,))
    ui_src_rows = page.locator(SEL_REVIEW_SRC).count()
    if rev:
        refs = json.loads(rev[0][0]).get("ref", [])
        rep.hard("E5.review_cached_nonempty", bool(refs),
                 f"cached review has {len(refs)} ref(s) (empty is never cached)")
        import urllib.parse as up
        shown = [r for r in refs if up.urlparse(r).hostname
                 and up.urlparse(r).hostname.replace("www.", "") in html]
        rep.hard("E5.review_on_page", len(shown) == len([r for r in refs if r]),
                 f"{len(shown)}/{len(refs)} review source hosts visible on page")
    elif ui_src_rows > 0:
        rep.hard("E5.review_consistency", False,
                 f"UI shows {ui_src_rows} review sources but no cached review row")
    else:
        rep.soft("E5.review", True, "no review shown and none cached (allowed)")

    # E6 offers ---------------------------------------------------------------
    total_offers = 0
    for ep in OFFER_ENDPOINTS:
        r = rows(
            "SELECT response FROM endpoint_req_to_body_cache WHERE endpoint=? AND request=?",
            (ep, key))
        if not r:
            continue
        offers = json.loads(r[0][0]).get("offers", [])
        rep.hard(f"E6.nonempty[{ep}]", len(offers) > 0,
                 f"cached {ep} response has {len(offers)} offer(s) (empty never cached)")
        total_offers += len(offers)
        for o in offers:
            price = (o.get("price") or "").strip()
            if len(price) >= 3:  # skip trivial/blank prices
                rep.soft(f"E6.price_on_page[{price}]", "".join(price.split()) in html_sqz,
                         f"offer price {price!r} visible on page")
    offers_header = "Offers" in html and page.locator("text=Offers").count() > 0
    if offers_header:
        rep.hard("E6.offers_backed", total_offers > 0,
                 f"UI shows Offers section; DB has {total_offers} cached offer(s)")
    else:
        rep.soft("E6.offers", True, f"no Offers section shown (DB cached {total_offers})")


def case_db_first(page, base_url, rep: Report, top_bike, args) -> None:
    brand, model = top_bike
    print(f"\n── E2  DB-first short-circuit for {brand} {model!r} ──")
    before = offer_row_count("/v1/bike/search")
    n = do_search(page, base_url, brand=brand, model=model, price_max=9_999_999,
                  timeout_ms=args.search_timeout)
    after = offer_row_count("/v1/bike/search")
    rep.hard("E2.no_ai_write", after == before,
             f"/v1/bike/search generic rows {before}->{after} (unchanged => DB-first, no AI)")
    rep.hard("E2.cards", n > 0, f"{n} card(s) served from DB")


def case_cascade(rep: Report, top_bike, args) -> None:
    brand, model = top_bike
    print(f"\n── E8  Cascade delete {brand} {model!r} ──")
    bid = scalar("SELECT id FROM bike WHERE LOWER(brand)=? AND LOWER(model)=?",
                 (norm(brand), norm(model)))
    if bid is None:
        rep.soft("E8.cascade", True, "test bike already absent; nothing to delete")
        return

    # Backup cache.db (+ WAL/SHM) before the destructive delete.
    scratch = Path(args.backup_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(DB_PATH) + suffix)
        if src.exists():
            shutil.copy2(src, scratch / (src.name + ".e2e_bak"))
    print(f"  (backed up cache.db* -> {scratch})")

    children = {
        "bike_detail": "SELECT COUNT(*) FROM bike_detail WHERE bike_id=?",
        "bike_detail_component": "SELECT COUNT(*) FROM bike_detail_component WHERE bike_detail_id "
                                 "IN (SELECT id FROM bike_detail WHERE bike_id=?)",
        "bike_detail_photos": "SELECT COUNT(*) FROM bike_detail_photos WHERE bike_detail_id "
                              "IN (SELECT id FROM bike_detail WHERE bike_id=?)",
        "bike_offer": "SELECT COUNT(*) FROM bike_offer WHERE bike_id=?",
        "search_bike_rating_cache": "SELECT COUNT(*) FROM search_bike_rating_cache WHERE bike_id=?",
    }
    before = {name: (scalar(sql, (bid,)) or 0) for name, sql in children.items()}
    print(f"  children before: {before}")

    with closing(sqlite3.connect(str(DB_PATH))) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("DELETE FROM bike WHERE id=?", (bid,))
        con.commit()

    after = {name: (scalar(sql, (bid,)) or 0) for name, sql in children.items()}
    all_gone = all(v == 0 for v in after.values())
    rep.hard("E8.children_cascaded", all_gone, f"children after delete: {after}")

    fk = rows("PRAGMA foreign_key_check")
    rep.hard("E8.fk_check", not fk, f"foreign_key_check => {fk or 'clean'}")


# ── preflight ───────────────────────────────────────────────────────────────
def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E UI<->DB tests for the biker app")
    ap.add_argument("--base-url", default="http://localhost:5173")
    ap.add_argument("--backend-url", default="http://localhost:8000/docs")
    ap.add_argument("--brand", default="Trek")
    ap.add_argument("--type", default="MTB", help="bike_type option value (Road/MTB/Gravel/...)")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--no-details", action="store_true", help="run E1/E2 only (skip E3-E6)")
    ap.add_argument("--skip-cascade", action="store_true", help="do not run the destructive E8")
    ap.add_argument("--search-timeout", type=int, default=240_000)
    ap.add_argument("--details-timeout", type=int, default=360_000)
    ap.add_argument("--settle-timeout", type=int, default=180_000)
    ap.add_argument("--backup-dir",
                    default=str(Path(__file__).resolve().parent.parent / ".e2e-backups"))
    args = ap.parse_args()

    # Windows consoles default to cp1252; our output has box-drawing chars and
    # Polish price strings (zł). Force UTF-8 so printing never crashes the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — older/exotic streams lack reconfigure
            pass

    if not DB_PATH.exists():
        print(f"cache.db not found at {DB_PATH}", file=sys.stderr)
        return 2
    if not reachable(args.base_url):
        print(f"Frontend not reachable at {args.base_url} - run `npm run dev` in /frontend",
              file=sys.stderr)
        return 2
    if not reachable(args.backend_url):
        print(f"Backend not reachable at {args.backend_url} - run "
              f"`uvicorn app.main:app --port 8000` in /backend", file=sys.stderr)
        return 2

    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        print("patchright not installed (pip install patchright)", file=sys.stderr)
        return 2

    rep = Report()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 2200})
        page = ctx.new_page()
        try:
            top_bike = case_search(page, args.base_url, rep, args)
            if top_bike and not args.no_details:
                case_details(page, rep, top_bike, args)
                case_review_offers(page, rep, top_bike, args)
            if top_bike:
                case_db_first(page, args.base_url, rep, top_bike, args)
                if not args.skip_cascade:
                    case_cascade(rep, top_bike, args)
                else:
                    print("\n── E8  skipped (--skip-cascade) ──")
        finally:
            browser.close()

    rep.summary()
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
