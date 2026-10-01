"""Shop / marketplace source filter (TODO-042) — the equipment UI shows no offer links, so its sources never may.

The prompt forbids shop sources, but a QA run still stored ebike24.com,
melbournepowered.com.au and elanusparts.com, so the build step drops them in
code. A source is a shop when (a) a host label is a marketplace, (b) the host
contains a shop token, or (c) the URL path looks like a shop listing — rule (c)
is skipped when the host contains the item's brand (a manufacturer product page
such as poc.com/en-us/product/… is kept). Review, forum and press sites
(road.cc, bikeradar.com) pass. Heuristic by design: a missed shop is a link,
a dropped manufacturer page only shortens the source list.
"""
import re
from urllib.parse import urlsplit

# (a) marketplaces / price comparison — matched against whole host labels ("www.amazon.de" -> "amazon").
MARKETPLACE_LABELS = frozenset({"allegro", "olx", "ceneo", "decathlon", "amazon", "ebay", "aliexpress", "empik"})

# (b) substrings of the host that mark a shop: generic shop words (EN/PL), the big online bike retailers, and two
# words QA saw in shop domains ("melbournepowered", "elanusparts"). A token with a dot is a domain: it must be the
# host or its suffix ("rei.com" does not hit "torei.com").
SHOP_HOST_TOKENS = (
    "shop", "store", "sklep", "outlet", "bikeshop", "cycling-shop", "powered", "parts",
    "bike24", "bike-discount", "bikediscount", "bike-components", "bikecomponents", "chainreaction", "wiggle",
    "rosebikes", "jensonusa", "competitivecyclist", "excelsports", "tredz", "merlincycles", "bikester",
    "probikeshop", "bikeinn", "tradeinn", "backcountry", "rei.com",
)

# (c) shop-listing paths.
SHOP_PATH = re.compile(
    r"/(?:product|products|shop|sklep|item|offer|oferta)/|/cart(?:[/?]|$)|/checkout|/p/\d|/dp/", re.IGNORECASE,
)


def _brand_token(name: str) -> str:
    """The item's brand as host text: its first word, letters and digits only ("POC Octal" -> "poc"); "" if < 3 chars."""
    first = (name or "").strip().split(" ", 1)[0].lower()
    token = re.sub(r"[^a-z0-9]", "", first)
    return token if len(token) >= 3 else ""


def is_shop_source(url: str, item_name: str = "") -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if any(label in MARKETPLACE_LABELS for label in host.split(".")):
        return True
    for token in SHOP_HOST_TOKENS:
        if "." in token:
            if host == token or host.endswith("." + token):
                return True
        elif token in host:
            return True
    brand = _brand_token(item_name)
    if brand and brand in host.replace("-", "").replace(".", ""):
        return False  # the manufacturer's own site: a product page is a spec source, not an offer
    return bool(SHOP_PATH.search(parts.path or ""))
