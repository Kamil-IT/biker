/* Wspólne dane dla trzech propozycji widoku wyników ze zdjęciem.
 *
 * Rowery, oceny, komponenty i adresy zdjęć pochodzą z lokalnej bazy biker-pg
 * (2026-10-03): `photo` = pierwsze zdjęcie z bike_detail_photos (display_order),
 * `rating` = bike_review.rating (null → karta pokazuje „?”), `accessories` =
 * te same trzy chipy co dziś (tylna przerzutka, klamka hamulca, materiał ramy).
 * `explanation` = krótki opis (bike.short_description); lokalnie ma go tylko
 * Marlin 4, pozostałe opisy to polskie streszczenia zapisanych opisów (EN).
 *
 * Zdjęcia celowo są różne, bo takie są w bazie: białe studio (Giant, Bombtrack —
 * kwadrat z dużym marginesem), jasnoszare (Canyon 16:9, Cannondale), czarne
 * studio (Trek Madone SL 6, FX 3, Marlin 4), przezroczysty PNG (Madone SL 5).
 * Checkpoint ALR 5 nie ma ani zdjęcia, ani opisu — tak wygląda większość
 * rowerów w bazie (594 z 723 ma zdjęcia, opis krótki mają pojedyncze).
 *
 * `photoBg` = kolor narożnika zdjęcia (null = przezroczyste tło albo brak zdjęcia).
 * W aplikacji liczyłby go searcher przy zapisie zdjęcia; tu wpisany ręcznie.
 *
 * Kolejność = jak w aplikacji po wczytaniu ocen: ocenione malejąco, bez oceny na końcu.
 */
window.BIKER_QUERY = 'uniwersalny rower na szuter i asfalt'

window.BIKER_RESULTS = [
  {
    brand: 'Giant',
    model: 'Revolt Advanced Pro',
    rating: 8.4,
    photo: 'https://images2.giant-bicycles.com/b_white%2Cc_pad%2Cq_80%2Cw_1000/x4eow23emboza1sutyr5/rev_adv_pro_tech.jpg',
    photoBg: '#FFFFFF',
    accessories: ['Shimano GRX RD-RX812 12-Speed', 'Shimano GRX BL-RX810', 'Carbon'],
    explanation: 'Wyścigowy gravel na lekkiej ramie kompozytowej Advanced, z geometrią dopracowaną razem z zawodnikami Giant. Szybki na szutrze i pewny na zmiennej nawierzchni.',
  },
  {
    brand: 'Trek',
    model: 'Madone SL 6',
    rating: 8.2,
    photo: 'https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/MadoneSL6Disc_20_28714_A_Portrait',
    photoBg: '#000000',
    accessories: ['Shimano Ultegra RX RD-RX805', 'Shimano Ultegra ST-R8170', 'Carbon (OCLV Carbon)'],
    explanation: 'Aerodynamiczna szosa na ramie OCLV Carbon serii 500 z rurami o profilu Kammtail. Dla kolarzy, którzy chcą prędkości bez rezygnacji z komfortu.',
  },
  {
    brand: 'Trek',
    model: 'Madone SL 5 Gen 8',
    rating: 8.0,
    photo: 'https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/MadoneSL5-25-46218-B-Primary',
    photoBg: null,
    accessories: ['Shimano Ultegra RD-R8100', 'Shimano Ultegra ST-R8170', 'Carbon (OCLV)'],
    explanation: 'Lekka szosa aero, która przenosi wyścigowe rozwiązania do niższej półki cenowej. Zwinna na sprintach i stabilna na szybkich zjazdach.',
  },
  {
    brand: 'Cannondale',
    model: 'Topstone Carbon 4',
    rating: 7.2,
    photo: 'https://embed.widencdn.net/img/dorelrl/7vurcowofz/800px@1x/C22_C15402U_Topstone_Crb_4_SBK_PD.jpg?color=f8f8f8&q=90',
    photoBg: '#F8F8F8',
    accessories: ['Shimano GRX RD-RX812', 'Shimano GRX BL-RX400', 'Carbon'],
    explanation: 'Gravel na karbonowej ramie BallisTec z tylnym zawieszeniem Kingpin, które tłumi drgania szutru. Napęd Shimano GRX 400 i hydrauliczne hamulce tarczowe.',
  },
  {
    brand: 'Trek',
    model: 'FX 3',
    rating: 6.5,
    photo: 'https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/FX3-24-40819-C-Portrait',
    photoBg: '#000000',
    accessories: ['Shimano Altus RD-M315', 'Tektro HD-M275', 'Aluminum'],
    explanation: 'Wszechstronny rower fitness na dojazdy i dłuższe wycieczki. Lekka aluminiowa rama, karbonowy widelec i prosty napęd 1×.',
  },
  {
    brand: 'Canyon',
    model: 'Grizl CF 7 ESC',
    rating: null,
    photo: 'https://dma.canyon.com/image/upload/w_543,c_fit/b_rgb:F2F2F2/f_auto/q_auto/v1750252663/2026_FULL_grizl_cf-7-escape_4142_R126_P01_afedsr',
    photoBg: '#F2F2F2',
    accessories: ['Shimano GRX RD-RX812 12-Speed', 'Carbon (CF)'],
    explanation: 'Gravel z linii Escape na długie wyprawy bikepackingowe, z napędem typu mullet. Kierownica Full Mounty daje wiele chwytów i miejsc na mocowania.',
  },
  {
    brand: 'Bombtrack',
    model: 'Arise SG Apex',
    rating: null,
    photo: 'https://cdn.shopify.com/s/files/1/0951/5384/8662/files/BT_MY24_Arise_SG_metallic_black_websquare_01.jpg?v=1781869359',
    photoBg: '#FFFFFF',
    accessories: ['SRAM Apex 1 (Clutch, Long Cage)', 'SRAM Apex Mechanical Double-Tap', '4130 Double-Butted Chromoly Steel'],
    explanation: 'Stalowy rower all-road na przygody i bikepacking. Rama z chromolibdenu 4130 z przesuwnymi hakami sprawdzi się na asfalcie, szutrze i z sakwami.',
  },
  {
    brand: 'Trek',
    model: 'Marlin 4',
    rating: null,
    photo: 'https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/Marlin4-24-41613-A-Portrait',
    photoBg: '#000000',
    accessories: ['Shimano ESSA', 'Tektro HD-M275', 'Aluminum'],
    explanation: 'Trek Marlin 4 to wszechstronny rower górski hardtail z aluminiową ramą i widelcem zawieszającym, idealny dla początkujących i zaawansowanych jeźdźców szukających uniwersalnego towarzysza do tras i dojazdów. Wyposażony w napęd 1×8 Shimano ESSA, hydrauliczne hamulce tarczowe Tektro i koła w rozmiarze 27,5 cala lub 29 cali, zapewnia niezawodną wydajność i kontrolę.',
  },
  {
    brand: 'Trek',
    model: 'Checkpoint ALR 5',
    rating: null,
    photo: null,
    photoBg: null,
    accessories: [],
    explanation: '',
  },
]
