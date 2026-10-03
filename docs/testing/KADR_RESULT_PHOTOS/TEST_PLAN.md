# Kadr - zdjecia w kafelkach wynikow: plan testow i wyniki (2026-10-03)

Srodowisko: backend :8062 (biker-pg), vite :5192, Playwright/Chromium. Dane: Trek 34 rowery, tylko 6 ma zdjecie (FX 3, FX 3 Disc, Madone SL 5 Gen 8, Madone SL 6, Marlin 4, Marlin 5). Screenshoty poza repo: `.ai/cezar/tmp/<run>/qa/`.

| # | Przypadek | Wynik | Dowod |
|---|-----------|-------|-------|
| 1 | API search/by-id/popular: klucze `photo`, `photo_bg`, format `#RRGGBB`/null, zgodnosc z DB | PASS | 34/34 elementow ma oba klucze; 6 z URL, 5 z kolorem; Canyon 13/2, Romet 8/6, Kross 6/4 ze zdjeciem; by-id (14, 1, 39, 20) i popular (3) zgodne; URL = display_order 0 w `bike_detail_photos` dla 14, 19, 44, 651, 1 (bike 661: brak wiersza Portrait, okladka = Primary, bg null - zgodnie z DB) |
| 2 | /search?brand=Trek 1280: 3 kolumny, kolor sceny, plakietka, pasek, chipy, clamp, puste | PASS (uwagi D1, D2) | kolumny x=120/473/827, brak overflow; zdjecia 1080x810 bez bandow na czarnych/ciemnych; plakietka "8.2 / 10", "? bez oceny"; clamp 3 linii (Marlin 4); "Nie mamy jeszcze opisu..." ; `trek_1280.png` |
| 2b | "#n" a "Sortuj" | PASS | domyslnie #1..#3 po ocenie; "Nazwa: A-Z" -> #1 Allant+ 7, #2 Checkpoint ALR 5; powrot przywraca kolejnosc |
| 3 | 768 px / 390 px | PASS | 2 kolumny (x=24,394), 1 kolumna (x=16), brak poziomego overflow |
| 4 | Zepsuty obraz (route abort) | PASS | kafelek FX 3 pokazuje rysunek + "Brak zdjecia. Popros o nie w szczegolach roweru.", ocena 6.5 zachowana; `broken_tile.png` |
| 5 | Home: popularne | PASS | `bike_popular` ma 3 wiersze lokalnie (bez seedowania); 3 kafle ze zdjeciem, 3 kolumny, opis 3 linie; `home.png` |
| 6 | Nawigacja | PASS | klik -> `/bike/14`, Back -> `/search?brand=Trek` z 34 kafelkami; kafel to `<a href="/bike/{id}">` |
| 7 | Klawiatura | PASS | Tab trafia w `<a href=/bike/651>`; reguly `focus-visible:ring` w kodzie (pierścien nie zmierzony pikselowo - `focus.png`) |
| 8 | Loading | PASS | po wstrzymaniu `/v1/bike/search`: 3 szkielety LoadingCard z "- / 10", ta sama siatka; `loading.png` |
| 9 | Konsola | PASS | brak bledow konsoli/pageerror na wynikach i home; jedynie `ERR_ABORTED` na `/v1/bike/popular` (przerwany przy nawigacji, nie nowy kod) |

## Defekty / uwagi
- D1 (NAPRAWIONE: `pick_covers` omija miniatury `looks_like_thumbnail`; bike 19 ma 8 miniatur 200 px, wiec zostaje pierwsza) (niski, dane/obraz): bike 19 "FX 3 Disc" - okladka to 200x200 z bialym paddingiem (Cloudinary `c_pad`, `b_rgb:FFFFFF`): na kafelku czarne zdjecie w bialej ramce, rozmyte (powiekszone ze 200 px). `photo_bg` #FFFFFF jest poprawny (naroznik). Powod: `is_cover_candidate` przepuszcza miniatury `w_200`; sugestia: preferowac wieksze/niepadowane zdjecie (`backend/app/photo_cover.py`).
- D2 (NAPRAWIONE: domyslne tlo kafelka `#FFFFFF`) (kosmetyka): bike 661 (bg null) ma jasna scene #F4F1EC i bialo-szare zdjecie - subtelny prostokat; nie ma koloru, bo okladka nie ma wiersza z bg (`bg_color` NULL).
- D3 (NAPRAWIONE: jedna automatyczna ponowna proba - remount `<img>` - zanim pokaze sie "Brak zdjecia") (niepotwierdzony, 1 z ~7 uruchomien): przy 390 px po szybkim scrollu kafel #1 Madone SL 6 chwilowo pokazal "Brak zdjecia" mimo istniejacego URL; 6 kolejnych prob i test 1280 - zdjecie ladowalo sie poprawnie. Hipoteza: `onError` w `frontend/src/components/ResultCard.tsx` (ok. linii 102) trwale ustawia `failedPhoto` po jednorazowym bledzie lazy-load, bez ponowienia. Nie odtworzony.

## Nie testowano
- Brak przezroczystych PNG/gif/pdf w wynikach Trek na ekranie (logika filtra pokryta testami backendu, `test_photo_cover.py`, nie uruchamianymi tutaj).
- Szczegolowy pomiar pierscienia fokusu; Firefox/Safari; wyszukiwanie tekstem swobodnym (AI bez kredytow).
