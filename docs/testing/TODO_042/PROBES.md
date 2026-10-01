# TODO-042 — sondy promptów sprzętu przez `claude -p` (2026-10-01)

Cel: sprawdzić, czy stare prompty backendu (`backend/app/prompts/equipment_*.md`) działają w CLI tak, jak uruchamia je searcher, zanim je przeniesiemy.

## Ustawienia

- Wywołanie: `searcher.app.claude_cli.run_structured` zaimportowane wprost, model `claude-haiku-4-5-20251001`, timeout 400 s, subskrypcja (bez klucza API).
- Szczegóły: STARY prompt kategorii (`equipment_details_<slug>.md`) plus treść starego `equipment_description.md` doklejona jako dodatkowe pola. Schemat = `DETAILS_SCHEMA` searchera (`found`, `description`, `short_description`, `sources`, `components`). Narzędzia: WebSearch + WebFetch.
- Zdjęcia: stary `equipment_photos.md`, tylko WebSearch, schemat `{url}`.
- Uruchomienia po jednym na kategorię (2 równolegle), tylko prompty STAREGO backendu. Nowych promptów searchera (`searcher/app/prompts/equipment_details*.md`) nie sondowano.

## Wyniki

| Przebieg | Czas | Schemat | Podkat. / elem. / specs | Opis PL (5 zdań) | short_description | Linki sklepów w tekście |
|---|---|---|---|---|---|---|
| kaski, POC Octal MIPS | 99,8 s | ok | 3 / 3 / 14 | tak | 2 zdania PL | brak |
| lampy, Lezyne Macro Drive 1300XXL | 53,1 s | ok | 3 / 3 / 11 | tak | 2 zdania PL | brak |
| zapięcia, Kryptonite Evolution Mini-7 | 58,6 s | ok | 3 / 4 / 14 | tak | 2 zdania PL | brak |
| odzież, Castelli Perfetto RoS 2 | 52,3 s | ok | 3 / 5 / 20 | tak | DEFEKT (niżej) | brak |
| zdjęcia (URL), POC Octal MIPS | 19,3 s | ok | nie dotyczy | nie dotyczy | nie dotyczy | nie dotyczy |

Bez błędów CLI (ani limitu 400, ani timeoutu). `found` = true we wszystkich przebiegach, więc ścieżka `found=false` nie była testowana. Komponenty wracają jako lista z jedną kategorią, nazwy kategorii zgodne z nagłówkiem starego promptu ("Helmets", "Lights & electronics", "Locks & security", "Apparel, bags & accessories").

## Trzy defekty

1. **`short_description` odzieży** zawierał 2 zdania, pustą linię i etykietę "Description:" z całym 5-zdaniowym opisem. Prompt musi mówić "tylko te 2 zdania, nigdy opis ani etykieta", a `build_details` powinien mieć straż (np. odrzucić pole z `\n\n` albo dłuższe niż ok. 400 znaków).
2. **Opisy elementów po angielsku** w lampach (0 z 3 po polsku) i odzieży (0 z 5); kaski 3 z 3 i zapięcia 4 z 4 po polsku. Stare przykłady w promptach są angielskie. Trzeba polskich przykładów i reguły "element `description` po polsku".
3. **Sklep w `sources`**: excelsports.com w przebiegach kasków i odzieży. Stare prompty nic nie mówią o źródłach. Trzeba reguły "tylko strony producenta, specyfikacje, recenzje, fora; nigdy sklep, marketplace, porównywarka cen". W tekście wyników nie pojawiło się allegro, olx, ceneo, decathlon ani amazon.

## Zdjęcia

URL z sondy: `https://poc.com/en-us/product/octal-mips-cpsc-hydrogen-white-black`. To strona producenta (poc.com), nie sklepu. Stary `equipment_photos.md` działa bez zmian po przejściu na odpowiedź `{"url": ...}` (jak `bike_photos.md`).

## Werdykt

Stare prompty da się przenieść prawie bez zmian: opis (4–5 zdań PL, bez cen i sklepów), kategoria jako lista z jednym obiektem, dokładne angielskie nazwy kategorii i `found` działają. Do poprawy: trzy defekty wyżej. Nowy wspólny prompt searchera (`equipment_details.md` + cztery kategorie) ma już polskie przykłady elementów i zakaz sklepów w `sources`; brakuje mu wzmocnienia reguły `short_description` i straży w kodzie. Nie sondowano: nowych promptów, `found=false` dla nieznanego przedmiotu ani części generycznych ("Reflectors", "Bar Tape"). Warto puścić 1–2 przebiegi na nowych promptach przed uznaniem ich za sprawdzone. Koszt przebiegu nie został zapisany (wrapper loguje go tylko w logu searchera).

## Surowe wyniki (scratchpad, poza repo)

`C:\Users\KAMIL_~1\AppData\Local\Temp\claude\C--Users-kamil-wolny-Projects-biker\96bc0be7-f51f-45a7-aa7c-a15e34935e6f\scratchpad\probes\`
- `helmets.json`, `lights.json`, `locks.json`, `apparel.json`, `photos.json`
- `probe.py` (skrypt sondy), `an.py` (analiza)

## Re-sondy na nowych promptach

Dwa przebiegi przez `find_equipment_details` searchera, już na nowych promptach (`equipment_details.md` + kategorie), po poprawkach: linia w prompcie i straż w kodzie dla `short_description` (8 nowych testów, pytest searchera: 114 passed).

| Przebieg | Czas | Wynik |
|---|---|---|
| odzież, Castelli Perfetto RoS 2 | 72,2 s | `found` = true; `short_description` czysty, dokładnie 2 zdania PL; opisy elementów po polsku; źródła road.cc + bikeradar, bez sklepów |
| "Bar Tape" w Canyon Grizl CF 7 ESC (część generyczna) | 57,1 s | `found` = true; model rozpoznał realną część "Canyon Ergospeed Gel Bar Tape" ze strony canyon.com, specyfikacja ma pokrycie w źródle; kategoria rozstrzygnięta jako apparel, bo żadne słowo kluczowe nie pasowało; wiersz "Bar Tape" roweru został podlinkowany |

Defekty 1 i 2 z sekcji powyżej (short_description, język opisów elementów) i 3 (sklepy w źródłach) nie wystąpiły w tych przebiegach. Ścieżka `found=false` nadal nie była sprawdzana. Surowe wyniki w scratchpadzie `probes/`: `new-apparel.json`, `new-bartape.json`, skrypt `run_new_probe.py`.
