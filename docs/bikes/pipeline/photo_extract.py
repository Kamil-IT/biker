"""Product-image extraction, round 2.

Round 1 scraped 8 bikes and only 1 came out right without hand-repair. The
defects below were each confirmed against real page HTML by the w-photos agent,
not guessed. This module replaces the bare `_IMG_SRC` regex from
app/bike_photos_finder.py; that file has the same defects and should get the
same treatment once this is proven.

Strategy, in order:
  1. JSON-LD Product `image` block — Shopify and most storefronts embed clean,
     absolute, full-size URLs there. Highest-value source by far.
  2. srcset / data-srcset, taking the LARGEST descriptor, not the first.
  3. src / data-src / data-image / data-zoom / data-large_image.
Then normalise, filter and (optionally) HEAD-verify.
"""
import html
import json
import logging
import re
from urllib.parse import urljoin

logger = logging.getLogger("pipeline.photo_extract")

# Round 4: bare httpx was intermittently refused on the first request and served
# on an immediate identical retry, which looked like a dead product URL. Sending
# a real UA fixed it.
_UA = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "accept": "*/*",
}

# `(?:https?:)?//` — protocol-relative `//host/path` is the Shopify default and
# was invisible to the old pattern. Extension is optional because CDN URLs carry
# {width} placeholders and query strings instead.
_URL_IN_ATTR = re.compile(
    r'(?:src|data-src|data-image|data-zoom|data-large_image)\s*=\s*["\']'
    r'((?:https?:)?//[^\s"\'<>]+?)["\']',
    re.IGNORECASE,
)
_SRCSET_ATTR = re.compile(
    r'(?:srcset|data-srcset)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
# `/cdn/` alone matched .js and .css assets served from the same CDN, which then
# got mislabelled in `rejects`. Require an actual image extension, or a known
# image-transform path.
_IMAGEY = re.compile(
    r"\.(?:jpg|jpeg|png|webp)(?:[?#]|$)|/image/upload/|/cdn/shop/(?:files|products)/",
    re.I,
)
_NOT_IMAGE = re.compile(r"\.(?:js|css|json|svg|woff2?|ttf|mp4|webm|ico)(?:[?#]|$)", re.I)

# Commerce chrome and third-party widgets. Judge.me review thumbnails alone
# accounted for most of the junk on two of eight bikes in round 1.
_SKIP = re.compile(
    r"/(?:awards?|logos?|icons?|avatars?|badges?|payments?|flags?|arrows?|spinners?)[/._-]"
    r"|[/_-](?:nav|banner|sale|promo|klarna|paypal|affirm|truemed|logo|icon|badge|award)[_.\-]"
    r"|(?:klarna|paypal|affirm|truemed|logo\.png|logo\.svg)"
    r"|judge\.?me|judgeme|review[-_]images?"
    r"|options?[-_]x[-_]close|top[-_]cap|ride[-_]wrap|labour|swatch|artboard"
    r"|geometry|geo[-_]chart|size[-_]chart"
    # round 2: PDF page renders and marketing collateral scraped as product shots
    r"|_page-\d{4}|buying[-_]guide|bike_buying|lifestyle[-_]"
    # round 4: UI/spec icon sheets and sizing charts that matched the model name
    r"|icons?[-_]?\d|[-_]icons?[-_.]|sizing[-_]?chart|size[-_]?chart|sizingchart"
    r"|\.gif$|\.svg$"
    r"|/static/.*?/(?:default|icons?)/",
    re.IGNORECASE,
)
# A width token under ~300px means a thumbnail or an LQIP placeholder.
_SMALL = re.compile(r"[?&_](?:w|width)=([0-9]{1,3})\b|_([0-9]{1,3})x[.\-_]", re.I)


def _normalise(url: str, base: str = "") -> str:
    """Unescape, de-slash-escape, absolutise, and upgrade width tokens."""
    u = html.unescape(url.strip()).replace("\\/", "/")
    if u.startswith("//"):
        u = "https:" + u
    elif u.startswith("/") and base:
        u = urljoin(base, u)
    # Shopify {width} placeholder -> a real size
    u = u.replace("{width}x", "1600x").replace("{width}", "1600")
    # imgix / Next.js LQIP placeholders: w=10&blur=10 -> full size
    u = re.sub(r"([?&])w=\d{1,3}\b", r"\g<1>w=1600", u)
    u = re.sub(r"&?blur=\d+", "", u)
    u = re.sub(r"([?&])width=\d{1,3}\b", r"\g<1>width=1600", u)
    # Shopify _500x.jpg -> _1600x.jpg
    u = re.sub(r"_\d{2,3}x(\.[a-z]{3,4})", r"_1600x\1", u, flags=re.I)
    return u


def _dedupe_key(url: str) -> str:
    """Collapse URLs differing only by size/version so one image counts once.

    Round 4: `?crop=center&height=1600&v=..&width=1600` vs `?v=..&width=1600` on
    the same CDN path took two slots each — 6 distinct images in an 8-slot
    payload. Drop the query string entirely and key on the path.
    """
    k = re.sub(r"[?#].*$", "", url)
    # Shopify size suffixes: _1600x.jpg, _1024x1024.jpg, _500x600.jpg
    k = re.sub(r"_\d{2,4}x(?:\d{2,4})?", "", k, flags=re.I)
    # Round 3: the same image at two renders took two slots on 3 of 10 bikes —
    # `_2048x.jpg` vs `_1216x.progressive.jpg`, and `.png` vs `_large.png`.
    k = re.sub(r"\.progressive", "", k, flags=re.I)
    k = re.sub(r"_(?:large|medium|small|grande|compact|master)(\.[a-z]{3,4})", r"\1", k, flags=re.I)
    k = re.sub(r"\.(jpe?g|png|webp)$", "", k, flags=re.I)
    return k.rstrip("?&_-")


def _node_images(n: dict) -> list[str]:
    img = n.get("image")
    if isinstance(img, str):
        return [img]
    if isinstance(img, list):
        return [i for i in img if isinstance(i, str)] + [
            i["url"] for i in img if isinstance(i, dict) and isinstance(i.get("url"), str)
        ]
    if isinstance(img, dict) and isinstance(img.get("url"), str):
        return [img["url"]]
    return []


def _from_jsonld(page_html: str, page_url: str = "", model: str = "") -> list[str]:
    """Images from the JSON-LD Product node **for this page only**.

    Round 2 defect: flattening every Product in the document pulled in
    related-products / cross-sell blocks — both Bombtrack Audax pages came back
    carrying the same three Arise images. So prefer the Product whose `url`
    matches the page being scraped, or whose `name` matches the model, and fall
    back to a lone Product only when there is exactly one.
    """
    products: list[dict] = []
    for block in _JSONLD.findall(page_html):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph") if isinstance(node.get("@graph"), list) else [node]
            for n in graph:
                if isinstance(n, dict) and "product" in str(n.get("@type", "")).lower():
                    products.append(n)

    if not products:
        return []

    page_path = re.sub(r"[?#].*$", "", page_url).rstrip("/").lower()
    slug = _slugify(model)

    def matches(n: dict) -> bool:
        u = str(n.get("url") or "").rstrip("/").lower()
        if u and page_path and (u.endswith(page_path.rsplit("/", 1)[-1]) or page_path.endswith(u.rsplit("/", 1)[-1])):
            return True
        if slug and _slugify(str(n.get("name") or "")).find(slug) >= 0:
            return True
        return False

    scoped = [n for n in products if matches(n)]
    if not scoped and len(products) == 1:
        scoped = products
    if not scoped:
        logger.info("json-ld: %d Product nodes, none matched this page — falling back to regex",
                    len(products))
        return []

    out: list[str] = []
    for n in scoped:
        out.extend(_node_images(n))
    return out


def _largest_from_srcset(value: str) -> str:
    """srcset='a 320w, b 1600w' -> b. The first entry is the smallest."""
    best, best_w = "", -1
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        w = -1
        if len(bits) > 1:
            m = re.match(r"(\d+)[wx]", bits[1])
            if m:
                w = int(m.group(1))
        if w > best_w:
            best, best_w = url, w
    return best


def shopify_images(product_url: str, timeout: float = 20.0) -> tuple[list[str], str]:
    """Authoritative per-product gallery from `/products/<handle>.json`.

    Round 4 proved every other strategy is guesswork by comparison: the Chromag
    `Minor Threat` page returned 7 of 8 images belonging to `Minor Threat V2`,
    and reported 8/8 "filename-matched" while doing it, because every V2 filename
    contains `minor-threat` and no `v2` token. Shopify declares each product's
    own images, so there is nothing to infer — no cross-sell, no sizing charts,
    no spec icons, and no sibling contamination. It also needs no browser.

    Returns ([], "") when the URL is not a Shopify product.
    """
    import httpx

    m = re.match(r"(https?://[^/]+/products/[^/?#]+)", product_url)
    if not m:
        return [], ""
    endpoint = m.group(1) + ".json"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=_UA) as c:
            r = c.get(endpoint)
        if r.status_code != 200:
            return [], ""
        product = r.json().get("product") or {}
    except Exception as exc:
        logger.info("shopify .json unavailable | %s | %s", endpoint, exc)
        return [], ""

    urls = []
    for img in product.get("images") or []:
        src = img.get("src") if isinstance(img, dict) else None
        if isinstance(src, str):
            urls.append(_normalise(src))
    title = str(product.get("title") or "")
    if urls:
        logger.info("shopify images[] | %d images for %r", len(urls), title)
    return urls, title


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _split_tokens(s: str) -> list[str]:
    """Tokenise, splitting letter/digit boundaries so `Level4` -> ['level','4']."""
    s = re.sub(r"([a-z])(\d)", r"\1 \2", (s or "").lower())
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def _tokens(s: str) -> list[str]:
    return [t for t in _split_tokens(s) if len(t) > 2]


def _relevance(url: str, brand: str, model: str, provenance: str = "regex") -> int:
    """Higher = more likely to actually be this bike.

    Round 2: filename matching separates a product shot from page decoration.
    Round 3 refinements:
      * NEGATIVE scoring — `Level4-...jpg` on a Level 3 page shares the token
        "level" and scored as a match. A variant number the target does not have
        is now a penalty, which also kills `Beyond_2` on a Beyond 1 page and
        `willow-7i` on a Willow 8i page.
      * PROVENANCE FLOOR — Bombtrack's real galleries are named by EAN
        (`4055822531849_1.jpg`), scored 0 for having no words, and lost their
        slots to a cross-sell image that did have words. A URL from this page's
        own JSON-LD Product node is on-product regardless of filename, so
        filename match now breaks ties rather than gating admission.
    """
    # Strip query string and extension: `.jpg` counted as a trailing token and
    # turned every trailing sequence number into a false "variant".
    name = url.rsplit("/", 1)[-1].lower()
    name = re.sub(r"[?#].*$", "", name)
    name = re.sub(r"\.(?:jpe?g|png|webp|gif)$", "", name)
    name_tokens = set(_split_tokens(name))
    model_tokens = _tokens(model)
    model_nums = {t for t in _split_tokens(model) if t.isdigit()}

    score = 2 if provenance == "json-ld" else 0  # provenance floor

    for t in model_tokens:
        if t in name_tokens or t in name:
            score += 3
    for t in _tokens(brand):
        if t in name_tokens or t in name:
            score += 1

    # VERSION MARKERS (v2, mk2, gen2). Round 4: the `Minor Threat` page returned
    # 7 of 8 images belonging to `Minor Threat V2` and scored them 8/8, because a
    # V2 filename contains `minor-threat` and the positional check had no number
    # to compare. A version marker on one side but not the other is decisive.
    # Asymmetric on purpose. A candidate carrying a version marker the target
    # lacks is a sibling. The reverse is NOT true: Chromag's real `Minor Threat
    # V2` gallery is named `chromag-bikes-minor-threat-complete-*` with no `v2`
    # token anywhere, so rejecting unmarked files on a V2 target would throw away
    # that product's entire genuine gallery.
    cand_ver = set(re.findall(r"\b(?:v|mk|gen)\s?(\d{1,2})\b", name))
    model_ver = set(re.findall(r"\b(?:v|mk|gen)\s?(\d{1,2})\b", (model or "").lower()))
    if cand_ver - model_ver:
        return -1

    # A different variant number = a sibling product. Judge this POSITIONALLY:
    # only the number immediately following a model word counts. A set-based test
    # mistook gallery sequence numbers (`_01`) and model years (`MY24`) for
    # variant numbers and penalised the correct images.
    seq = _split_tokens(name)
    for i, tok in enumerate(seq[:-1]):
        if tok in model_tokens:
            nxt = seq[i + 1]
            if nxt.isdigit() and len(nxt) <= 2 and not nxt.startswith("0"):
                # Round 4: `Beyond 1` / `Beyond 2` images landed on the
                # `Beyond AL Apex` page. The target has no digit at all, so a
                # digit-vs-digit test had nothing to compare — but a candidate
                # carrying a variant number the target lacks is still a sibling.
                #
                # Only when the number is FOLLOWED by more tokens, though: a
                # trailing number is a gallery sequence (`bella-velio-1.jpg`,
                # `scrambler-1.jpg`), whereas a variant number sits mid-name
                # ahead of a colourway (`Beyond_1_metallic_black_01`).
                trailing = seq[i + 2:]
                if nxt not in model_nums and trailing:
                    return -1

    return score


def extract_images(
    page_html: str,
    base_url: str = "",
    limit: int = 8,
    brand: str = "",
    model: str = "",
) -> tuple[list[str], str, list[dict]]:
    """Return (urls, source, rejects).

    `rejects` records every dropped candidate and why — without it a page can
    report success while containing no picture of the bike, which is exactly
    what happened in round 2.
    """
    # (url, provenance) — provenance matters for scoring and for deciding whether
    # regex candidates are needed at all.
    candidates: list[tuple[str, str]] = []
    source = "regex"
    rejects: list[dict] = []

    jsonld = _from_jsonld(page_html, base_url, model)
    if jsonld:
        candidates.extend((u, "json-ld") for u in jsonld)
        source = "json-ld"

    # Round 3: when scoped JSON-LD already yields a real gallery, merging regex
    # candidates re-imports the cross-sell images the scoping just excluded
    # (Arise Tour kept reappearing on the Bombtrack Beyond pages). Only fall back
    # to page-wide regex when JSON-LD is thin.
    if len(jsonld) < 4:
        for value in _SRCSET_ATTR.findall(page_html):
            pick = _largest_from_srcset(value)
            if pick:
                candidates.append((pick, "regex"))
        candidates.extend((u, "regex") for u in _URL_IN_ATTR.findall(page_html))

    seen: dict[str, int] = {}
    kept: list[tuple[int, str]] = []
    for raw, prov in candidates:
        url = _normalise(raw, base_url)
        if not url.startswith("http"):
            continue
        if _NOT_IMAGE.search(url):
            continue  # .js/.css served from the same CDN — not a candidate at all
        if not _IMAGEY.search(url):
            continue
        if _SKIP.search(url):
            rejects.append({"url": url, "reason": "skip-pattern"})
            continue
        m = _SMALL.search(url)
        if m and int(next(g for g in m.groups() if g)) < 300:
            rejects.append({"url": url, "reason": "width<300"})
            continue
        k = _dedupe_key(url)
        if k in seen:
            rejects.append({"url": url, "reason": "duplicate render of an image already kept"})
            continue
        seen[k] = 1
        kept.append((_relevance(url, brand, model, prov), url))

    # Rank filename-matching images first; keep the rest as fallback rather than
    # discarding them, since plenty of legitimate CDN names carry no model token.
    kept.sort(key=lambda p: -p[0])
    # A negative score means a sibling-variant filename (Level 4 on a Level 3
    # page). Drop those outright rather than letting them fill slots.
    positive = [(s, u) for s, u in kept if s >= 0]
    for s, u in kept:
        if s < 0:
            rejects.append({"url": u, "reason": f"sibling-variant filename (relevance {s})"})
    result = [u for _, u in positive[:limit]]
    for score, u in positive[limit:]:
        rejects.append({"url": u, "reason": f"over limit (relevance {score})"})

    matched = sum(1 for s, _ in positive[:limit] if s > 0)
    logger.info("extracted %d images via %s (%d filename-matched, %d rejected)",
                len(result), source, matched, len(rejects))
    return result, source, rejects


def verify(urls: list[str], min_bytes: int = 15000, timeout: float = 10.0) -> list[str]:
    """HEAD each URL; drop non-200 and anything too small to be a product shot.

    This is the catch-all: it rejects 10px LQIP placeholders and 160px review
    thumbnails without needing to know anything site-specific.
    """
    import httpx

    keep: list[str] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        for u in urls:
            try:
                r = c.head(u)
                if r.status_code != 200:
                    r = c.get(u, headers={"Range": "bytes=0-2048"})
                ctype = r.headers.get("content-type", "")
                clen = int(r.headers.get("content-length") or 0)
                if r.status_code in (200, 206) and "image" in ctype and (clen == 0 or clen >= min_bytes):
                    keep.append(u)
                else:
                    logger.info("dropped %s (status=%s type=%s len=%s)", u, r.status_code, ctype, clen)
            except Exception as exc:
                logger.info("dropped %s (%s)", u, exc)
    return keep
