import json
import time
from urllib.parse import urlparse

import httpx

URL = "http://localhost:8000/v1/bike/review"

# Curated tier list (TODO-018 / backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md).
# Domains not in this map are unranked and ignored by the ordering check below —
# the model may legitimately cite an outlet outside the curated list.
_DOMAIN_TIER = {
    "bikeradar.com": 1,
    "cyclingweekly.com": 1,
    "bikeperfect.com": 1,
    "pinkbike.com": 2,
    "bikemag.com": 2,
    "gcn.com": 2,
    "mtbr.com": 3,
    "reddit.com": 3,
    "forumrowerowe.org": 3,
    "bikestats.pl": 3,
}


def _tier_of(url: str) -> int | None:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, tier in _DOMAIN_TIER.items():
        if host == domain or host.endswith("." + domain):
            return tier
    return None
# Use a widely-reviewed mainstream model: a niche variant can legitimately have
# no reviews, which would make this smoke test flaky for the wrong reason.
payload = {"company": "Trek", "model": "Marlin 5"}

print(f"POST {URL}")
print(f"Body: {json.dumps(payload)}\n")

resp = httpx.post(URL, json=payload, timeout=120)

print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
print()

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

data = resp.json()

# The graceful fallback ({"score":0,"explanation":"Review unavailable.",...})
# satisfies every type/range check, so assert we did NOT get it — otherwise a
# totally non-functional endpoint still passes this smoke test.
assert data["explanation"] != "Review unavailable.", "got the fallback, not a real review"

assert isinstance(data["score"], int), "score must be int"
assert 1 <= data["score"] <= 10, "score must be 1–10 for a real review"
assert isinstance(data["explanation"], str), "explanation must be a string"
assert data["explanation"].count(".") >= 3, "explanation must be several sentences"
assert "<cite" not in data["explanation"], "explanation must not leak citation markup"
assert isinstance(data["ref"], list) and data["ref"], "ref must be a non-empty list"

# TODO-018: ref must be ordered best-tier-first (Tier 1 -> 2 -> 3). Unknown
# domains (not in the curated list) are excluded from the check — they carry
# no rank guarantee — but ranked domains must appear in non-decreasing tier
# order relative to each other.
ranked_tiers = [t for t in (_tier_of(u) for u in data["ref"]) if t is not None]
assert ranked_tiers == sorted(ranked_tiers), (
    f"ref must be ordered Tier 1 -> 2 -> 3 among curated domains, got tiers {ranked_tiers} "
    f"for ref={data['ref']}"
)

# TODO-014: aggregate rating fields
assert "rating" in data, "response must include rating"
assert isinstance(data["rating"], (int, float)), "rating must be a number"
assert 0 < data["rating"] <= 10, "rating must be > 0 and <= 10 for a real review"
assert "sources_used" in data, "response must include sources_used"
assert isinstance(data["sources_used"], int), "sources_used must be int"
assert data["sources_used"] >= 1, "sources_used must be >= 1 for a real review"

print("OK — real review returned: score + rating + sources_used all non-fallback")

# Second call should hit the cache and return the same rating.
t = time.perf_counter()
resp2 = httpx.post(URL, json=payload, timeout=120)
elapsed2 = time.perf_counter() - t
assert resp2.status_code == 200, f"Expected 200 on 2nd call, got {resp2.status_code}"
data2 = resp2.json()
assert data2["rating"] == data["rating"], "cached rating must match first call"
assert data2["sources_used"] == data["sources_used"], "cached sources_used must match"
print(f"OK — 2nd call consistent (cache) in {elapsed2:.2f}s")
