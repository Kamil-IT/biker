# Prompt: Extract image URLs from an Allegro offer

## Role
You are an extraction agent. Your task is to extract direct product/gallery image URLs from a single Allegro offer URL.

## Input
One Allegro offer URL, for example:

```text
https://allegro.pl/oferta/rower-mlodziezowy-indiana-rock-jr-24-cale-czarny-15516214705
```

## Output
Return **only** a valid JSON array of direct image URLs, with no prose, no markdown, and no comments.

Example output shape:

```json
[
  "https://a.allegroimg.com/s720/11ef96/2a2b661749b38f51ee9fb5dd25e8/ROWER-INDIANA-ROCK-JUNIOR-24",
  "https://a.allegroimg.com/s128/1105c3/3a5de9ba451b9bc1bccde32fc98b/ROWER-INDIANA-ROCK-JUNIOR-24-Rozmiar-ramy-13-cali"
]
```

## What to discover / how Allegro image URLs are exposed
On Allegro offer/product pages, the visible offer gallery contains links/images pointing to the domain:

```text
https://a.allegroimg.com/
```

The image URL pattern is usually:

```text
https://a.allegroimg.com/{size}/{short-id}/{image-hash}/{slug}
```

where `{size}` can be, for example:

```text
original
s720
s180
s128
```

For the example offer, the page redirects from the archived offer URL to a product page with a replacement active offer. The product gallery still contains the useful image URLs. The visible gallery had a main image and thumbnails such as:

```text
https://a.allegroimg.com/s720/11ef96/2a2b661749b38f51ee9fb5dd25e8/ROWER-INDIANA-ROCK-JUNIOR-24
https://a.allegroimg.com/s128/11ef96/2a2b661749b38f51ee9fb5dd25e8/ROWER-INDIANA-ROCK-JUNIOR-24
https://a.allegroimg.com/s128/11b1cf/4d26106740bdbf61482d8bf3a07b/ROWER-INDIANA-ROCK-JUNIOR-24-Stopien-zlozenia-zlozony-gotowy-do-jazdy
https://a.allegroimg.com/s128/1105c3/3a5de9ba451b9bc1bccde32fc98b/ROWER-INDIANA-ROCK-JUNIOR-24-Rozmiar-ramy-13-cali
```

## Extraction rules
1. Open the input URL and follow redirects.
2. If a cookies/privacy modal appears, continue using the accessible page content; do not let the modal block extraction.
3. Extract all URLs that match this regex:

```regex
https?:\\/\\/a\.allegroimg\.com\\/(?:original|s\d+)\\/[^\s"'<>\\)]+|https?://a\.allegroimg\.com/(?:original|s\d+)/[^\s"'<>\)]+
```

4. Decode escaped HTML/JSON forms:
   - `\\/` -> `/`
   - `&amp;` -> `&`
   - percent-encoded characters only when needed for comparison; preserve final URL as a normal browser-usable URL.
5. Keep only offer/product images. Exclude:
   - `assets.allegrostatic.com`
   - placeholders, SVGs, UI icons, payment logos, Allegro logos, rating stars, seller badges, warranty logos, delivery/payment icons
   - recommendation images unrelated to the current offer
   - review/user gallery images unless the user explicitly asks for review images
6. Prefer the main offer gallery near the product title / first product image section. On many Allegro pages, the relevant images have `alt` text similar to the offer title.
7. De-duplicate by image identity. Treat these as the same image if only the size segment differs:

```text
https://a.allegroimg.com/s720/11ef96/2a2b661749b38f51ee9fb5dd25e8/ROWER-INDIANA-ROCK-JUNIOR-24
https://a.allegroimg.com/s128/11ef96/2a2b661749b38f51ee9fb5dd25e8/ROWER-INDIANA-ROCK-JUNIOR-24
```

8. If both `original` and `s720` exist for the same image, prefer `s720` for consistency with the expected output. If only `s128` is present for thumbnails, keep `s128`.
9. Preserve gallery order: main image first, then thumbnails/details in the same order as shown on the offer page.
10. Return only the JSON array.

## Fallback strategy
If direct DOM extraction misses images:

1. Inspect embedded JSON blocks, especially scripts like `__NEXT_DATA__`, application state, JSON-LD, or other hydration/state scripts.
2. Search the raw HTML text for `a.allegroimg.com`.
3. Search decoded text again after replacing `\\/` with `/`.
4. If the offer is archived and redirects to a product page, extract from the redirected page's current product/offer gallery and still return direct image URLs.

## Test run for the provided example URL
Input:

```text
https://allegro.pl/oferta/rower-mlodziezowy-indiana-rock-jr-24-cale-czarny-15516214705
```

Observed useful output:

```json
[
  "https://a.allegroimg.com/s720/11ef96/2a2b661749b38f51ee9fb5dd25e8/ROWER-INDIANA-ROCK-JUNIOR-24",
  "https://a.allegroimg.com/s128/11b1cf/4d26106740bdbf61482d8bf3a07b/ROWER-INDIANA-ROCK-JUNIOR-24-Stopien-zlozenia-zlozony-gotowy-do-jazdy",
  "https://a.allegroimg.com/s128/1105c3/3a5de9ba451b9bc1bccde32fc98b/ROWER-INDIANA-ROCK-JUNIOR-24-Rozmiar-ramy-13-cali",
  "https://a.allegroimg.com/s128/11cbe9/5340493b457ea227349d80e0d4ac/ROWER-INDIANA-ROCK-JUNIOR-24-Rozmiar-kola-24",
  "https://a.allegroimg.com/s128/1135b2/6758043e416d9398c1d3303fd36d/ROWER-INDIANA-ROCK-JUNIOR-24-Liczba-biegow-5",
  "https://a.allegroimg.com/s128/11845b/1c7381d84d42827d97e08d884717/ROWER-INDIANA-ROCK-JUNIOR-24-Material-ramy-stal",
  "https://a.allegroimg.com/s128/114ac9/459f10844a7bb6e0168950c4842b/ROWER-INDIANA-ROCK-JUNIOR-24-Amortyzacja-przod",
  "https://a.allegroimg.com/s128/1100d4/7bb38e6f47c88f8aa57d39a0f38a/ROWER-INDIANA-ROCK-JUNIOR-24-Plec-nie-dotyczy",
  "https://a.allegroimg.com/s128/1145b8/a7a4b37c47c48bdb98ab480a731c/ROWER-INDIANA-ROCK-JUNIOR-24-Kod-producenta-RME24ME615"
]
```
