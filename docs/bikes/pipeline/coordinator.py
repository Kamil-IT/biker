"""Coordinator service (port 9101).

Owns the work queue (brand + model, read from bikes.txt), hands one bike at a
time to the research agents, aggregates both researchers' output, then drives
validator -> db_saver. All traffic is REST.

Run:  .venv/Scripts/python.exe -m uvicorn pipeline.coordinator:app --port 9101
"""
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from pipeline.common import BIKES_FILE, STATE, URL, key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("pipeline.coordinator")

app = FastAPI(title="backfill-coordinator")

QUEUE_FILE = STATE / "queue.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_queue() -> dict:
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    bikes = []
    if BIKES_FILE.exists():
        for line in BIKES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            # `brand | model` or `brand | model | product_url`. The URL comes from
            # the consolidated dataset and is authoritative, so it is seeded as a
            # hint: it removes the handle-guessing that dominated earlier rounds.
            parts = [p.strip() for p in line.split("|")]
            brand, model = parts[0], parts[1]
            bikes.append({"brand": brand, "model": model,
                          "url": parts[2] if len(parts) > 2 else ""})
    q = {
        "created": _now(),
        "items": {
            key(b["brand"], b["model"]): {
                "brand": b["brand"],
                "model": b["model"],
                "state": "pending",       # pending -> researching -> ready -> saved / failed
                "details": None,
                "photos": None,
                "attempts": 0,
                "notes": [],
                **({"hints": {"spec_urls": [], "product_url": b["url"],
                              "notes": ["dataset: authoritative product URL"]}}
                   if b.get("url") else {}),
            }
            for b in bikes
        },
    }
    _save_queue(q)
    return q


def _save_queue(q: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(q, indent=2, ensure_ascii=False), encoding="utf-8")


QUEUE = _load_queue()


class Submission(BaseModel):
    brand: str
    model: str
    payload: dict


@app.get("/health")
def health() -> dict:
    return {"service": "coordinator", "queued": len(QUEUE["items"])}


@app.get("/status")
def status() -> dict:
    counts: dict[str, int] = {}
    for item in QUEUE["items"].values():
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {"counts": counts, "total": len(QUEUE["items"])}


CLAIM_TTL = 900  # seconds; a claim older than this is treated as abandoned


def _claim_free(item: dict, role: str, worker: str) -> bool:
    """True if this worker may take this bike for this role.

    With more than one worker per role, `/next` would otherwise hand the same
    bike to both. A claim expires after CLAIM_TTL so a dead worker does not
    strand its bikes.
    """
    claim = item.get(f"{role}_claim")
    if not claim:
        return True
    if claim.get("worker") == worker:
        return True
    return (time.time() - claim.get("ts", 0)) > CLAIM_TTL


@app.get("/next")
def next_bike(role: str = "any", worker: str = "") -> dict:
    """Hand out the next bike needing research.

    `role` lets the details and photo researchers run CONCURRENTLY, the same way
    /v1/bike/details fans its finders out under asyncio.gather:
      role=details -> first bike whose details are still missing
      role=photos  -> first bike whose photos are still missing
      role=any     -> first unfinished bike (single-worker mode)
    Without this a details worker that finished bike A would keep being handed A
    back until the photo side caught up.
    """
    for k, item in QUEUE["items"].items():
        if item["state"] not in ("pending", "researching"):
            continue  # includes "skipped" and "failed"
        if role == "details" and item["details"] is not None:
            continue
        if role == "photos" and item["photos"] is not None:
            continue
        if role in ("details", "photos") and worker and not _claim_free(item, role, worker):
            continue
        item["state"] = "researching"
        if role in ("details", "photos") and worker:
            item[f"{role}_claim"] = {"worker": worker, "ts": time.time()}
        _save_queue(QUEUE)
        return {
            "found": True,
            "brand": item["brand"],
            "model": item["model"],
            "need_details": item["details"] is None,
            "need_photos": item["photos"] is None,
            "attempts": item["attempts"],
            "notes": item["notes"],
            "hints": item.get("hints"),
            "details_task": f"{URL['researcher_details']}/task?brand={item['brand']}&model={item['model']}",
            "photos_task": f"{URL['researcher_photos']}/task?brand={item['brand']}&model={item['model']}",
        }

    # Nothing claimable. Distinguish "queue drained" from "all claimed by someone
    # else, N still in flight" — a late-arriving worker needs to know whether to
    # exit or to wait for claims to expire, rather than guess.
    in_flight = 0
    for item in QUEUE["items"].values():
        if item["state"] not in ("pending", "researching"):
            continue  # includes "skipped" and "failed"
        if role == "details" and item["details"] is not None:
            continue
        if role == "photos" and item["photos"] is not None:
            continue
        in_flight += 1
    return {
        "found": False,
        "in_flight": in_flight,
        "drained": in_flight == 0,
        "retry_after": 0 if in_flight == 0 else 120,
    }


@app.post("/submit/details")
def submit_details(sub: Submission) -> dict:
    item = QUEUE["items"].get(key(sub.brand, sub.model))
    if item is None:
        return {"ok": False, "error": "unknown bike"}
    item["details"] = sub.payload
    item.pop("details_claim", None)
    _save_queue(QUEUE)
    logger.info("details received | %s %s", sub.brand, sub.model)
    return _maybe_finish(item)


@app.post("/submit/photos")
def submit_photos(sub: Submission) -> dict:
    item = QUEUE["items"].get(key(sub.brand, sub.model))
    if item is None:
        return {"ok": False, "error": "unknown bike"}
    item["photos"] = sub.payload
    item.pop("photos_claim", None)
    _save_queue(QUEUE)
    logger.info("photos received | %s %s", sub.brand, sub.model)
    return _maybe_finish(item)


def _maybe_finish(item: dict) -> dict:
    """Both researchers done -> validate -> save."""
    if item["details"] is None or item["photos"] is None:
        return {"ok": True, "state": "waiting_for_other_researcher"}

    aggregate = {
        "brand": item["brand"],
        "model": item["model"],
        "description": item["details"].get("description", ""),
        "components": item["details"].get("components", []),
        "photos": item["photos"].get("photos", []),
        "source_urls": sorted(set(
            (item["details"].get("source_urls") or [])
            + (item["photos"].get("source_urls") or [])
        )),
    }

    with httpx.Client(timeout=60) as c:
        verdict = c.post(f"{URL['validator']}/validate", json=aggregate).json()

    if not verdict["valid"]:
        item["attempts"] += 1
        item["notes"] = verdict["problems"]
        # Ask for a targeted re-fetch of only what is missing, rather than
        # re-researching the whole bike.
        if verdict["refetch"] == "details":
            item["details"] = None
        elif verdict["refetch"] == "photos":
            item["photos"] = None
        else:
            item["details"] = None
            item["photos"] = None
        if item["attempts"] >= 3:
            item["state"] = "failed"
        else:
            item["state"] = "researching"
        _save_queue(QUEUE)
        logger.warning("validation failed | %s %s | %s", item["brand"], item["model"], verdict["problems"])
        return {"ok": True, "state": item["state"], "problems": verdict["problems"]}

    with httpx.Client(timeout=120) as c:
        saved = c.post(f"{URL['db_saver']}/save", json=aggregate).json()

    item["state"] = "saved" if saved.get("stored") else "failed"
    item["notes"] = [] if saved.get("stored") else [saved.get("error", "save failed")]
    _save_queue(QUEUE)
    logger.info("saved | %s %s | %s", item["brand"], item["model"], saved)
    return {"ok": True, "state": item["state"], "saved": saved}


class Hint(BaseModel):
    brand: str
    model: str
    spec_urls: list[str] = []
    product_url: str = ""
    note: str = ""
    found_by: str = ""


@app.post("/hint")
def hint(req: Hint) -> dict:
    """Attach researched source URLs to a queued bike.

    The WebSearch budget is globally exhausted and free engines are blocked, so
    discovery collapsed to domain-guessing. A scout driving a real browser can
    still find spec pages; this is how it hands them to the spec workers without
    the two ever talking to each other.
    """
    item = QUEUE["items"].get(key(req.brand, req.model))
    if item is None:
        return {"ok": False, "error": "unknown bike"}
    hints = item.setdefault("hints", {"spec_urls": [], "product_url": "", "notes": []})
    for u in req.spec_urls:
        if u and u not in hints["spec_urls"]:
            hints["spec_urls"].append(u)
    if req.product_url:
        hints["product_url"] = req.product_url
    if req.note:
        hints["notes"].append(f"{req.found_by or 'scout'}: {req.note}")
    _save_queue(QUEUE)
    logger.info("hint | %s %s | %d spec urls | by=%s",
                req.brand, req.model, len(hints["spec_urls"]), req.found_by)
    return {"ok": True, "hints": hints}


@app.get("/unhinted")
def unhinted(limit: int = 25) -> dict:
    """Bikes still needing specs that have no hints yet — the scout's work list."""
    out = []
    for item in QUEUE["items"].values():
        if item["state"] not in ("pending", "researching"):
            continue
        if item["details"] is not None or item.get("hints"):
            continue
        out.append({"brand": item["brand"], "model": item["model"]})
        if len(out) >= limit:
            break
    return {"bikes": out, "count": len(out)}


class AddBikes(BaseModel):
    bikes: list[dict]  # [{"brand": ..., "model": ...}, ...]


@app.post("/add")
def add_bikes(req: AddBikes) -> dict:
    """Append bikes to the live queue.

    Growing the queue used to mean editing queue.json and restarting, which is
    how 20 bikes were silently lost: the still-running coordinator held the old
    queue in memory and rewrote the merged file on every save. Mutating through
    the owner process removes that race entirely.
    """
    added = skipped = 0
    for b in req.bikes:
        brand, model = (b.get("brand") or "").strip(), (b.get("model") or "").strip()
        if not brand or not model:
            continue
        k = key(brand, model)
        if k in QUEUE["items"]:
            skipped += 1
            continue
        QUEUE["items"][k] = {
            "brand": brand, "model": model, "state": "pending",
            "details": None, "photos": None, "attempts": 0, "notes": [],
        }
        added += 1
    _save_queue(QUEUE)
    logger.info("queue grown | added=%d already-present=%d total=%d",
                added, skipped, len(QUEUE["items"]))
    return {"ok": True, "added": added, "already_present": skipped, "total": len(QUEUE["items"])}


@app.get("/throughput")
def throughput() -> dict:
    """Counts for measuring whether adding workers actually helps."""
    counts: dict[str, int] = {}
    for item in QUEUE["items"].values():
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {
        "ts": time.time(),
        "counts": counts,
        "details_submitted": sum(1 for i in QUEUE["items"].values() if i["details"]),
        "photos_submitted": sum(1 for i in QUEUE["items"].values() if i["photos"]),
        "total": len(QUEUE["items"]),
    }


class Skip(BaseModel):
    brand: str
    model: str
    reason: str = ""
    role: str = ""


@app.post("/skip")
def skip(req: Skip) -> dict:
    """Retire a bike that cannot be resolved at all.

    Round 5: `Garelli | Basic` is not a real product — the brand's whole range is
    AUDAX/GRAVEL/IMAGO/VIRTUS, so no amount of research would find it. Without
    this the worker's own outstanding claim was re-served on every /next call and
    it could not reach any other bike. Bad queue data must be retirable, and the
    alternative — submitting an empty payload — would write a hollow row.
    """
    item = QUEUE["items"].get(key(req.brand, req.model))
    if item is None:
        return {"ok": False, "error": "unknown bike"}
    item["state"] = "skipped"
    item["notes"] = [req.reason or "skipped by worker"]
    item.pop("details_claim", None)
    item.pop("photos_claim", None)
    _save_queue(QUEUE)
    logger.warning("skipped | %s %s | %s", req.brand, req.model, req.reason)
    return {"ok": True, "state": "skipped"}


@app.post("/release")
def release(req: Skip) -> dict:
    """Give a claim back without retiring the bike, so another worker can try."""
    item = QUEUE["items"].get(key(req.brand, req.model))
    if item is None:
        return {"ok": False, "error": "unknown bike"}
    for role in (req.role,) if req.role else ("details", "photos"):
        item.pop(f"{role}_claim", None)
    _save_queue(QUEUE)
    logger.info("released | %s %s | %s", req.brand, req.model, req.reason)
    return {"ok": True, "released": req.role or "both"}


@app.post("/reset")
def reset() -> dict:
    """Rebuild the queue from bikes.txt (keeps already-saved bikes marked saved)."""
    global QUEUE
    saved = {k for k, v in QUEUE["items"].items() if v["state"] == "saved"}
    QUEUE_FILE.unlink(missing_ok=True)
    QUEUE = _load_queue()
    for k in saved:
        if k in QUEUE["items"]:
            QUEUE["items"][k]["state"] = "saved"
    _save_queue(QUEUE)
    return status()
