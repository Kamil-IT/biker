"""Regex heuristic: does a component element name denote a product worth linking to?

`bike_component.is_linkable` tells the frontend whether an element's name
opens the equipment view (ISSUE-016). The on-demand searcher gets the answer from
the model (its prompt decides, this module is NOT consulted there); this heuristic
serves the two writers that have no model to ask:

- `scripts/migrate_component_linkable.py` — backfills the rows stored before the column existed
- the discovery processor (`webscraper/centrumrowerowe/product_parser.py`) — shop pages, no AI

Rule, in order:
1. Empty / too short, or the name merely repeats its subcategory ("Frame" under
   Frame, "Pedals" under Pedals) → False.
2. A "not supplied" phrase (None included, Not specified, n/a, brak w zestawie, …) → False.
3. Paperwork (owner's manual, quick start guide, warranty documentation, …) → False.
4. Otherwise True only when at least one token looks specific: a model code
   (letters + digits, not a bare measurement such as "180mm" or 9/16") or a word
   that is not in the generic vocabulary below (materials, part nouns, adjectives,
   Polish equivalents). "Giant Multi-Tool" → True (Giant), "Alloy Platform Pedals"
   → False, "Kona JS2" → True, "Hydraulic Disc Brake" → False.

Keep the vocabulary lower-case ASCII-folded where Polish letters are involved
(`_fold` strips diacritics before the lookup).
"""
from __future__ import annotations

import re
import unicodedata

_MIN_LEN = 2

_NOT_SUPPLIED = re.compile(
    r"""
    ^\s*(
        none | n/?a | no | null | nil | unknown | unspecified | nie | brak | nd | tbd | tba | -+ | –+ | —+
      | not\s+(specified|available|applicable|listed|included|supplied|provided|fitted|equipped|installed|stated)
      | nie\s+(dotyczy|okreslono|podano|dolaczono|zawiera)
      | brak\s+(danych|informacji|w\s+zestawie|w\s+komplecie)
      | bez\s+\w+
    )\s*[.!]?\s*$
    |
    \b(none|not|no|without|brak|bez)\b [^\n]* \b(
        included | supplied | provided | fitted | equipped | installed | specified | available | listed
      | w\s+zestawie | w\s+komplecie | zestawie | komplecie | dolaczon\w* | zalaczon\w* | dostepn\w*
    )\b
    |
    \b(sold|sprzedawan\w*)\s+(separately|osobno|oddzielnie)\b
    |
    \b(optional|opcjonaln\w*)\s*(extra|accessory|dodatek)?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_PAPERWORK = re.compile(
    r"""
    \b(manual|manuals|handbook|instrukcj\w*|podrecznik\w*)\b
    | \b(owner'?s?|user'?s?|rider'?s?|quick[\s-]*start|getting[\s-]*started|setup|set-up|assembly|instruction\w*|safety|service)\s+(guide|booklet|leaflet|card|sheet|manual)s?\b
    | \bwarrant(y|ies)\b | \bgwarancj\w* | \bkarta\s+gwarancyjna\b
    | \bdocument(s|ation)?\b | \bdokument(y|acja|acji)?\b | \bpaperwork\b
    | \bcertificate\b | \bcertyfikat\w*
    | \bregistration\s+(card|form)\b | \brejestracj\w*
    | \b(brochure|leaflet|booklet|catalogue|catalog|katalog|ulotk\w*|broszur\w*)\b
    | \b(stickers?|decals?|naklejk\w*)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Trailing-unit measurements are not model codes: 180mm, 27.5", 9/16", 2x12s, 500Wh, 2 amp.
_UNITS = r"mm|cm|m|g|kg|s|t|sp|speed|w|wh|v|ah|nm|a|amp|in|inch|cal|\"|”|''|'|%|x|rpm|km|km/h|mph|psi|bar|l"
_MEASUREMENT = re.compile(rf"^[\d.,/x×+-]*\d[\d.,/x×+-]*\s*({_UNITS})?\s*$", re.IGNORECASE)
# A unit standing alone after a number ("9x100 mm", "500 Wh") is not a specific word either.
_UNIT = re.compile(rf"^({_UNITS})$", re.IGNORECASE)

_GENERIC = frozenset("""
a an the and or of with for to by on in at from vs via plus i z ze do na w we oraz lub bez dla od po pod nad przy
alloy aluminum aluminium alu steel stainless stal stalowy stalowa stalowe carbon karbon karbonowy kompozyt kompozytowy
composite nylon plastic plastik resin polypropylene polypropylen rubber guma gumowy titanium tytan tytanowy chromoly cromo
cr-mo cromoly hi-ten hiten magnesium leather skora skorzany foam pianka silicone silikon fiberglass glass kevlar wood drewno
standard standardowy standardowa standardowe basic podstawowy generic ogolny oem stock default classic klasyczny
integrated zintegrowany zintegrowana zintegrowane built-in builtin internal external custom customised customized
designed design dedicated dedykowany branded brand reinforced wzmocniony wzmocniona high heavy duty impact strong solid
lightweight light lite lekki lekka lekkie heavy ciezki compact kompaktowy mini micro maxi large small medium big little
full semi half double single dual triple twin podwojny pojedynczy potrojny
platform platformowe platformowy flat plaskie plaski cage clip clipless spd toe strap straps
folding foldable skladany skladana skladane adjustable regulowany regulowana regulowane quick release qr thru axle thru-axle
bolt bolt-on bolted thread threaded through
painted lakierowany lakierowana powder coated anodized anodised black white silver grey gray red blue green czarny bialy
hydraulic hydrauliczny hydrauliczna hydrauliczne mechanical mechaniczny mechaniczna mechaniczne cable linkowy linkowe
disc disk tarczowy tarczowa tarczowe rim obreczowy v-brake vbrake u-brake cantilever coaster torpedo roller drum hub-brake
front rear przedni przednia przednie tylny tylna tylne przod tyl fr rr f r lewy prawy left right
pedal pedals pedaly pedalow pedalami rack racks bagaznik bagazniki carrier carriers fender fenders mudguard mudguards
blotnik blotniki kickstand stand nozka stopka podporka sidestand side centre center bell dzwonek dzwonki
chain lancuch chainguard chainguide guard guide protector protection oslona chainstay stay chainring chainrings
reflector reflectors odblask odblaski reflective reflex light lights lamp lampa lampka lampki lighting oswietlenie
headlight taillight tail head rear-light front-light led leds dynamo hub-dynamo battery-powered usb rechargeable
headset stery pump pompka lock zapiecie blokada basket koszyk mirror mirrors lusterko lusterka bottle bidon holder
saddle siodlo siodelko seat seatpost sztyca post clamp zacisk collar stem mostek handlebar handlebars kierownica bar bars
grips grip chwyty chwyt tape owijka riser drop flat-bar
tyre tyres tire tires opona opony wheel wheels wheelset kolo kola hub hubs piasta piasty rim rims obrecz obrecze spoke spokes
szprycha szprychy nipples tube tubes tubeless ready tlr
rotor rotors tarcza tarcze brake brakes hamulec hamulce hamulcowy hamulcowa hamulcowe lever levers klamka klamki dzwignia
caliper calipers pads pad klocki klocek cassette kaseta sprocket sprockets zebatka zebatki freewheel wolnobieg
crank cranks crankset korba korby korbowy derailleur derailleurs przerzutka przerzutki shifter shifters manetka manetki
trigger grip-shift twist bottom bracket suport bb fork widelec amortyzator suspension rigid sztywny shock damper
frame rama ramy motor silnik mid-drive mid drive hub-drive hub-motor battery bateria akumulator charger ladowarka
display wyswietlacz controller sterownik sensor czujnik torque cadence assist class pas electric elektryczny e-bike ebike
tool tools narzedzie narzedzia kit zestaw multi multitool multi-tool allen keys key hex wrench screwdriver
parking size sizes rozmiar rozmiary set system type typ model version wersja series seria edition
gearing gear gears biegi biegow speed speeds prędkości predkosci speed-count ratio range
included includes w zestawie komplet complete accessories accessory akcesoria dodatkowe other inne others
activated turn signals signal brake-activated indicator indicators horn klakson alarm
water resistant waterproof wodoodporny wodoszczelny
amp volt watt wat
sealed cartridge forged kuty cold hot press-fit pressfit bsa bb30 pf30 ita english italian square taper octalink isis
below above under over piece pieces czesciowy dwuczesciowy trojczesciowy telescoping teleskopowy step-thru step-through
low-step szybkozamykacz os osie sztywna sztywny sztywne boost nakretki nakretka nut nuts axles axle-nut
suspension-fork rigid-fork coil air spring sprezyna lockout remote travel skok offset tapered straight steerer
comfort komfortowy ergo ergonomic ergonomiczny lcd tft led-display threadless fitted frame-fitted wide narrow
all-season season sport sportowy city miejski trekking mtb road szosowy gravel urban touring
drivetrain naped napedu groupset transmission gearbox component components komponent komponenty part parts czesc czesci
equipment wyposazenie osprzet hardware mounting mount mounts bolts screws sruby
""".split())


def _fold(text: str) -> str:
    """Lower-case and strip diacritics so Polish words match the ASCII vocabulary."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).replace("ł", "l")


def _is_specific_token(token: str) -> bool:
    token = token.strip("\"'’”“().,;:!?[]{}")
    if not token:
        return False
    has_digit = any(ch.isdigit() for ch in token)
    has_alpha = any(ch.isalpha() for ch in token)
    parts = [p for p in re.split(r"[-/+&_]", token) if p]
    if has_digit:
        # A model code carries letters and digits (RD-M6000, JS2, FP-804, AL6061);
        # a bare number, a measurement with its unit (180mm, 9x100, 2x12s) or a
        # number glued to a generic word (3-piece, 8-speed) does not.
        if not has_alpha or _MEASUREMENT.match(token):
            return False
        alpha_parts = [p for p in parts if not any(ch.isdigit() for ch in p)]
        return not alpha_parts or any(p not in _GENERIC and not _UNIT.match(p) for p in alpha_parts)
    if not has_alpha:
        return False
    return any(len(p) >= _MIN_LEN and p not in _GENERIC and not _UNIT.match(p) for p in parts)


def is_linkable(name: str, subcategory: str = "") -> bool:
    """True when `name` looks like a specific, searchable product (see the module docstring)."""
    name = (name or "").strip()
    if len(name) < _MIN_LEN:
        return False
    folded = _fold(name)
    if subcategory and folded == _fold(subcategory.strip()):
        return False
    if _NOT_SUPPLIED.search(folded) or _PAPERWORK.search(folded):
        return False
    return any(_is_specific_token(tok) for tok in folded.split())
