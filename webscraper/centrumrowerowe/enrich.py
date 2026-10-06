"""Import every discovered bike and fill what is missing, 5 bikes at a time; stops at 80 % (5 h) / 85 % (7 days) of the subscription.

One loop, until nothing is left or the usage guard trips:
1. queue   - claim up to --batch pending bikes and process them (process_queue.process_row: shop page
             -> description, components, photos; no AI);
2. enrich  - take up to --batch bikes (discovery rows with a bike) that still miss something and fill,
             per bike, in this order:
             category  - bike.category from the discovery bike_type (Polish shop type -> English category via
                         app.bike_categories), only while NULL and the type is mapped (no AI);
             offer     - each centrumrowerowe listing as a bike_offer row (source centrumrowerowe.pl, no AI);
             photos    - POST {BACKEND}/v1/bike/photos/search, only when the bike has no photo   (paid);
             details   - POST {BACKEND}/v1/bike/details/search, only when the description text or the
                         components are missing (the AI result replaces the components)        (paid);
             short     - short_description: a two-sentence Polish summary of the description by Haiku
                         (`claude -p --model haiku`, no tools, subscription; ~$0.012 list)             (paid);
             review    - POST {BACKEND}/v1/bike/review/search, only when no bike_review row     (paid).

--since limits the enrichment to discovery rows updated at or after that moment (the bikes of this import;
older done/skipped bikes are left alone).

Usage guard: before every paid call the utilisation of this machine's Claude subscription is read
(GET https://api.anthropic.com/api/oauth/usage with the token in ~/.claude/.credentials.json - the same
account as the searcher's). At 5 h >= --stop-at (80) or 7 days >= --stop-at-week (85), when it cannot be read, or when the backend answers
400 (subscription limit), no further paid call starts and no new batch is claimed; calls already running
finish (the searcher writes atomically), the queue holds no in_progress row of ours, and the next run
resumes from the data itself (what is missing is read from the DB, never from a log).

A paid step that came back empty is recorded in --attempts (JSON) and not paid for again unless
--retry-empty. Writes need --allow-remote for Cloud SQL, like the other scripts.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import text

from db import BikeDiscovery, BikeDiscoveryListing, DONE, SKIPPED, SOURCE, check_target, ensure_table, models, session
from app.bike_categories import category_from_discovery
from app.schemas import BikeDescription
import process_queue
from bike_store import set_category_if_null

logger = logging.getLogger("enrich")

DEFAULT_BACKEND = "https://biker-backend-ggkzq7ysyq-lm.a.run.app"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS = Path.home() / ".claude" / ".credentials.json"
DEFAULT_ATTEMPTS = Path(__file__).resolve().parent / "runs" / "enrich_attempts.json"
PAID_TIMEOUT = 700.0  # backend waits up to 600 s for the searcher
PAID_STEPS = ("photos", "details", "short", "review")
SHORT_SYSTEM = ("Streszczasz opisy rowerów. Odpowiadasz wyłącznie dwoma zdaniami po polsku, które streszczają "
                "podany opis (nie przepisuj pierwszych zdań). Bez wstępu, bez cudzysłowów.")
SHORT_TIMEOUT = 120
USAGE_REFRESH = 60    # seconds between usage reads
USAGE_MAX_AGE = 300   # a reading older than this cannot stand in for a failed read
# The CLI must not think it runs inside this (or any) Claude Code session, nor use the API key.
_CLI_ENV_DROP = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
                 "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                 "ANTHROPIC_API_KEY")  # backend/.env puts the API key here; the CLI must bill the subscription


class Guard:
    """Trips once - at the threshold, on an unreadable usage, or on a subscription-limit answer."""

    def __init__(self, stop_at: float, stop_at_week: float):
        self.stop_at, self.stop_at_week, self.reason, self._lock = stop_at, stop_at_week, None, threading.Lock()
        self._at, self._used, self._week = None, 0.0, 0.0

    @property
    def tripped(self) -> bool:
        return self.reason is not None

    def trip(self, reason: str) -> None:
        with self._lock:
            if self.reason is None:
                self.reason = reason
                logger.warning("STOP | %s | no new paid call, no new batch", reason)

    def _read(self) -> tuple[float, float]:
        """(5 h %, 7 d %); a 429 is retried after Retry-After (or 30/60/90 s) - 4 tries, then it raises."""
        for attempt in range(4):
            token = json.loads(CREDENTIALS.read_text(encoding="utf-8"))["claudeAiOauth"]["accessToken"]
            r = httpx.get(USAGE_URL, timeout=20,
                          headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
            if r.status_code != 429 or attempt == 3:
                break
            wait = min(float(r.headers.get("retry-after") or 30 * (attempt + 1)), 120)
            logger.info("usage endpoint 429, retrying in %.0fs", wait)
            time.sleep(wait)
        r.raise_for_status()
        body = r.json()
        return float(body["five_hour"]["utilization"]), float(body["seven_day"]["utilization"])

    def allow(self) -> bool:
        """True when a paid call may start now.

        The usage endpoint rate-limits (429), so it is read at most every USAGE_REFRESH seconds and the
        reading is shared by all threads; a failed read keeps the last one while it is younger than
        USAGE_MAX_AGE, after that the guard trips.
        """
        with self._lock:
            if self.reason is not None:
                return False
            now = time.monotonic()
            if self._at is None or now - self._at >= USAGE_REFRESH:
                try:
                    self._used, self._week = self._read()
                    self._at = now
                    logger.info("usage 5h %.0f%% | 7d %.0f%%", self._used, self._week)
                except Exception as exc:
                    if self._at is None or now - self._at >= USAGE_MAX_AGE:
                        self.reason = f"usage unreadable ({type(exc).__name__}: {exc})"
                    else:
                        logger.info("usage read failed (%s), keeping the reading from %.0fs ago",
                                    type(exc).__name__, now - self._at)
            if self.reason is None and self._used >= self.stop_at:
                self.reason = f"5h usage {self._used:.0f}% >= {self.stop_at:.0f}%"
            if self.reason is None and self._week >= self.stop_at_week:
                self.reason = f"7d usage {self._week:.0f}% >= {self.stop_at_week:.0f}%"
            if self.reason is not None:
                logger.warning("STOP | %s | no new paid call, no new batch", self.reason)
                return False
            return True


class Attempts:
    """Paid steps that came back empty, kept across runs: {"<bike_id>:<step>": {"at": iso, "result": str}}."""

    def __init__(self, path: Path, retry_empty: bool):
        self.path, self.retry_empty, self._lock = path, retry_empty, threading.Lock()
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def gave_up(self, bike_id: int, step: str) -> bool:
        return not self.retry_empty and self.data.get(f"{bike_id}:{step}", {}).get("result") == "empty"

    def record(self, bike_id: int, step: str, result: str) -> None:
        with self._lock:
            self.data[f"{bike_id}:{step}"] = {"at": datetime.now(timezone.utc).isoformat(), "result": result}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")


def format_price(raw: Optional[str]) -> str:
    """Listing price '1099.00' -> '1 099 zł' (the format of the other offers); unparsable -> ''."""
    try:
        value = float((raw or "").replace(",", "."))
    except ValueError:
        return ""
    whole, cents = int(value), round((value - int(value)) * 100)
    text_ = f"{whole:,}".replace(",", " ")
    return f"{text_},{cents:02d} zł" if cents else f"{text_} zł"


def missing(bike_id: int, discovery_id: int) -> dict:
    """What the bike still lacks, read from the DB (the single source of truth for resuming)."""
    with session() as s:
        bike = s.get(models.Bike, bike_id)
        discovery = s.get(BikeDiscovery, discovery_id)
        desc_text = ""
        if bike.description:
            try:
                desc_text = BikeDescription.model_validate_json(bike.description).text.strip()
            except Exception:
                desc_text = ""
        listing_urls = [u for (u,) in s.query(BikeDiscoveryListing.details_link)
                        .filter_by(discovery_id=discovery_id) if u]
        have_urls = {u for (u,) in s.query(models.BikeOffer.url).filter(models.BikeOffer.url.in_(listing_urls))}
        return {
            # An unmapped bike_type stays NULL for good, so it does not keep the bike open.
            "category": bike.category is None and category_from_discovery(discovery.bike_type) is not None,
            "offer": any(u not in have_urls for u in listing_urls),
            "photos": s.query(models.BikeDetailPhoto.id).filter_by(bike_id=bike_id).first() is None,
            "details": not desc_text or s.query(models.BikeComponent.id).filter_by(bike_id=bike_id).first() is None,
            "short": not (bike.short_description or "").strip() and bool(desc_text),
            "review": s.query(models.BikeReview.id).filter_by(bike_id=bike_id).first() is None,
        }


def store_offers(bike_id: int, discovery_id: int) -> int:
    """One bike_offer per listing not stored yet (url is globally unique: a url under another bike stays there)."""
    added = 0
    with session() as s:
        for li in s.query(BikeDiscoveryListing).filter_by(discovery_id=discovery_id):
            if not li.details_link or s.query(models.BikeOffer.id).filter_by(url=li.details_link).first():
                continue
            s.add(models.BikeOffer(bike_id=bike_id, price=format_price(li.price), is_new=True,
                                   url=li.details_link, source=SOURCE, city=None))
            added += 1
        s.commit()
    return added


def haiku_short(description: str) -> str:
    """Two-sentence Polish summary of `description` by Haiku through the Claude Code CLI (subscription)."""
    env = {k: v for k, v in os.environ.items() if k not in _CLI_ENV_DROP}
    proc = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--max-turns", "1", "--output-format", "json",
         "--setting-sources", "", "--tools", "", "--system-prompt", SHORT_SYSTEM],
        input=description, capture_output=True, text=True, encoding="utf-8", env=env,
        timeout=SHORT_TIMEOUT, cwd=Path.home(),
    )
    try:
        body = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        body = {"is_error": True, "result": proc.stdout}
    if proc.returncode or body.get("is_error"):
        raise RuntimeError(f"claude exit {proc.returncode}: {(body.get('result') or proc.stderr or '')[:200]}")
    return " ".join((body.get("result") or "").split())


def fill_short(bike_id: int, company: str, model: str, ctx, refresh: bool = False) -> str:
    """short_description by Haiku, only while empty (always with refresh); returns ok / empty / error / stopped / no."""
    with session() as s:
        bike = s.get(models.Bike, bike_id)
        current = (bike.short_description or "").strip()
        desc = BikeDescription.model_validate_json(bike.description).text.strip() if bike.description else ""
    if not desc or (current and not refresh):
        return "no"
    if not ctx.guard.allow():
        return "stopped"
    try:
        short = haiku_short(desc)
    except Exception as exc:
        logger.warning("short | %s %s | %s: %s", company, model, type(exc).__name__, exc)
        return "error"
    if not short:
        return "empty"
    only_empty = "" if refresh else " AND short_description = ''"
    with session() as s:
        s.execute(text(f"UPDATE bike SET short_description = :v WHERE id = :id{only_empty}"),
                  {"v": short, "id": bike_id})
        s.commit()
    logger.info("short | %s %s | %s", company, model, short[:90])
    return "ok"


def is_empty(step: str, body: dict) -> bool:
    if step == "photos":
        return not body.get("photos")
    if step == "details":
        return not body.get("components") and not (body.get("description") or {}).get("text")
    # The searcher stores a review only when ref is non-empty AND sources_used >= 1.
    return not body.get("ref") or (body.get("sources_used") or 0) < 1


def paid(step: str, bike_id: int, company: str, model: str, ctx) -> str:
    """One searcher run through the backend; returns ok / empty / error / stopped."""
    if ctx.attempts.gave_up(bike_id, step):
        return "gave-up"
    if not ctx.guard.allow():
        return "stopped"
    path = {"photos": "/v1/bike/photos/search", "details": "/v1/bike/details/search",
            "review": "/v1/bike/review/search"}[step]
    started = time.monotonic()
    try:
        r = httpx.post(ctx.backend + path, json={"company": company, "model": model}, timeout=PAID_TIMEOUT)
    except httpx.HTTPError as exc:
        logger.warning("%s | %s %s | %s", step, company, model, exc)
        return "error"
    took = time.monotonic() - started
    if r.status_code == 400:
        ctx.guard.trip(f"subscription limit ({r.text[:200]})")
        return "stopped"
    if r.status_code != 200:
        logger.warning("%s | %s %s | HTTP %s %s", step, company, model, r.status_code, r.text[:200])
        return "error"
    result = "empty" if is_empty(step, r.json()) else "ok"
    ctx.attempts.record(bike_id, step, result)
    logger.info("%s | %s %s | %s in %.0fs", step, company, model, result, took)
    return result


def enrich_bike(discovery_id: int, bike_id: int, ctx) -> dict:
    with session() as s:
        bike = s.get(models.Bike, bike_id)
        company, model = bike.brand, bike.model
    need, out = missing(bike_id, discovery_id), {}
    if need["category"]:
        with session() as s:
            bike_type = s.get(BikeDiscovery, discovery_id).bike_type
        set_category_if_null(bike_id, bike_type)
        out["category"] = category_from_discovery(bike_type)
    if need["offer"]:
        out["offer"] = f"+{store_offers(bike_id, discovery_id)}"
    for step in ("photos", "details"):
        if need[step]:
            out[step] = paid(step, bike_id, company, model, ctx)
    if ctx.refresh_short or missing(bike_id, discovery_id)["short"]:  # re-read: a details run may have brought one
        out["short"] = fill_short(bike_id, company, model, ctx, refresh=ctx.refresh_short)
    if need["review"]:
        out["review"] = paid("review", bike_id, company, model, ctx)
    logger.info("enriched | %s %s | %s", company, model, out or "complete")
    return out


def to_enrich(limit: int, ctx, only: Optional[list[int]] = None) -> list[tuple[int, int]]:
    """Up to `limit` (discovery_id, bike_id) of done/skipped bikes that miss something (skips given-up steps)."""
    with session() as s:
        q = (s.query(BikeDiscovery.id, BikeDiscovery.bike_id)
             .filter(BikeDiscovery.status.in_((DONE, SKIPPED)), BikeDiscovery.bike_id.isnot(None))
             .order_by(BikeDiscovery.bike_id))
        if only:
            q = q.filter(BikeDiscovery.bike_id.in_(only))
        if ctx.since is not None:
            q = q.filter(BikeDiscovery.updated_at >= ctx.since)
        rows = q.all()
    picked = []
    for discovery_id, bike_id in rows:
        if bike_id in ctx.seen:
            continue
        need = missing(bike_id, discovery_id)
        need["short"] = need["short"] or ctx.refresh_short
        open_ = [k for k, v in need.items() if v and not (k in PAID_STEPS and ctx.attempts.gave_up(bike_id, k))]
        if open_:
            picked.append((discovery_id, bike_id))
            if len(picked) == limit:
                break
    return picked


def run(args) -> int:
    ctx = argparse.Namespace(backend=args.backend.rstrip("/"), guard=Guard(args.stop_at, args.stop_at_week),
                             attempts=Attempts(Path(args.attempts), args.retry_empty), seen=set(),
                             since=args.since, refresh_short=args.refresh_short)
    totals = {"queued": {}, "enriched": 0}
    while ctx.guard.allow():  # no new batch once the usage guard has tripped (the reading is cached)
        claimed_at = process_queue.utcnow()
        claimed = [] if args.no_queue else process_queue.claim_batch(args.batch, args.source, claimed_at)
        for i, row_id in enumerate(claimed):  # free: shop pages only
            try:
                outcome = process_queue.process_row(row_id, claimed_at=claimed_at)
            except KeyboardInterrupt:  # process_row released its own row; the rest still hold our lease
                process_queue.release_rows(claimed[i:], claimed_at)
                raise
            totals["queued"][outcome] = totals["queued"].get(outcome, 0) + 1
            time.sleep(args.delay)
        batch = to_enrich(args.batch, ctx, args.bike)
        if not claimed and not batch:
            break
        with ThreadPoolExecutor(max_workers=args.batch) as pool:
            list(pool.map(lambda pair: enrich_bike(*pair, ctx), batch))
        ctx.seen.update(b for _, b in batch)  # one pass per bike per run; a rerun picks up what is left
        totals["enriched"] += len(batch)
        if args.max_bikes and totals["enriched"] >= args.max_bikes:
            break
    print(f"queue: {totals['queued']} | enriched bikes: {totals['enriched']} | "
          f"stopped: {ctx.guard.reason or 'no'}")
    return 0


def since_arg(value: str) -> datetime:
    """ISO time -> naive UTC (the column is a naive UTC DateTime)."""
    dt = datetime.fromisoformat(value)
    return (dt.astimezone(timezone.utc) if dt.tzinfo else dt).replace(tzinfo=None)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--batch", type=int, default=5, help="bikes per batch (default 5)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between shop page fetches")
    ap.add_argument("--stop-at", type=float, default=80.0, help="5h usage %% at which to stop (default 80)")
    ap.add_argument("--stop-at-week", type=float, default=85.0, help="7-day usage %% at which to stop (default 85)")
    ap.add_argument("--since", type=since_arg, default=None,
                    help="only enrich discovery rows updated at/after this ISO time (UTC), e.g. 2026-10-02T12:00")
    ap.add_argument("--refresh-short", action="store_true", help="regenerate short_description even when set")
    ap.add_argument("--backend", default=DEFAULT_BACKEND, help="backend base URL for the paid searches")
    ap.add_argument("--attempts", default=str(DEFAULT_ATTEMPTS), help="JSON file of empty paid results")
    ap.add_argument("--retry-empty", action="store_true", help="pay again for steps that came back empty")
    ap.add_argument("--no-queue", action="store_true", help="only enrich, claim no pending bike")
    ap.add_argument("--bike", type=int, action="append", help="only this bike id (repeatable; implies --no-queue)")
    ap.add_argument("--max-bikes", type=int, default=0, help="stop after enriching this many bikes (0 = all)")
    ap.add_argument("--source", default=None, help=f"only bikes listed by this shop, e.g. {SOURCE}")
    ap.add_argument("--allow-remote", action="store_true", help="allow writing to a non-local database")
    args = ap.parse_args(argv)
    args.no_queue = args.no_queue or bool(args.bike)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.info("database: %s | backend: %s", check_target(args.allow_remote), args.backend)
    ensure_table()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("interrupted - rerun to resume (state is read from the DB)")
        return 130


if __name__ == "__main__":
    sys.exit(main())
