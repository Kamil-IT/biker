"""Polish → English dictionary for the centrumrowerowe.pl "Specyfikacja" table.

One entry per shop label (lower-cased, whitespace-collapsed). English names
follow backend/app/prompts/bike_details_*.md and frontend/src/specLabels.ts so
the UI can translate them back. Values are never translated.

Two kinds of entry:

- ``Component(category, subcategory)`` — the value is a part name
  ("Shimano Acera RD-M3020, 7s"), stored as a ComponentElement named by the
  value, like the AI tree does.
- ``Spec(category, subcategory, key, element=None)`` — the value is an
  attribute, stored as ``SpecItem(key, value)``. With ``element=None`` the
  spec is attached to the first element of that subcategory, or to a new
  element named after the subcategory when there is none.
"""
from __future__ import annotations

from typing import NamedTuple, Optional, Union

FRAME = "Frame"
DRIVETRAIN = "Drivetrain"
BRAKES = "Brakes"
WHEELS = "Wheels"
COCKPIT = "Cockpit"
SADDLE = "Saddle & Seatpost"
LIGHTING = "Lighting"
ACCESSORIES = "Accessories"
ELECTRIC = "Electric / Powertrain"  # must equal repository._ELECTRIC

# Category order of the finished tree (the AI finder's order, e-bike last).
CATEGORY_ORDER = (FRAME, DRIVETRAIN, BRAKES, WHEELS, COCKPIT, SADDLE, LIGHTING, ACCESSORIES, ELECTRIC)

# Where unmapped labels go: element named by the value, the Polish label as
# its description, so nothing the shop listed is lost.
UNKNOWN_SUBCATEGORY = "Other"


class Component(NamedTuple):
    category: str
    subcategory: str
    description: str = ""


class Spec(NamedTuple):
    category: str
    subcategory: str
    key: str
    element: Optional[str] = None


Mapping = Union[Component, Spec]

# Labels that are shop bookkeeping, or handled elsewhere by the parser.
SKIP_LABELS = frozenset({
    "kod produktu", "kod ean", "kod producenta", "dane producenta", "marka",
    "gwarancja", "producent",
})

# Whole sections that carry no bike data.
SKIP_SECTIONS = frozenset({"informacje handlowe"})

# Sections only an e-bike page has. Labels mapped to ELECTRIC are used as such
# only on an e-bike; on any other page they go to Accessories (a plain bike's
# "Wyświetlacz" is a bike computer, not a powertrain).
ELECTRIC_SECTIONS = frozenset({"silnik", "akumulator", "napęd elektryczny"})

# Values meaning "not present".
EMPTY_VALUES = frozenset({"", "-", "—", "n/d", "nd", "brak", "nie dotyczy", "nie"})

# Keys the parser fills specially (all variants, normalised wheel size).
FRAME_SIZE_LABEL = "rozmiar producenta"
FRAME_SIZE_INCH_LABEL = "rozmiar ramy"
WHEEL_SIZE_LABEL = "rozmiar koła"

SIZES_KEY = "Sizes"          # repository._match_frame_size reads Frame/Frame "sizes"
WHEEL_SIZE_KEY = "Wheel size"  # repository._match_wheel reads "wheel size" anywhere

SPEC_MAP: dict[str, Mapping] = {
    # ── Informacje ────────────────────────────────────────────────────────
    "płeć": Spec(FRAME, "Frame", "Gender"),
    "kolor": Spec(FRAME, "Frame", "Color"),
    "rocznik modelowy": Spec(FRAME, "Frame", "Model Year"),
    "rocznik": Spec(FRAME, "Frame", "Model Year"),
    "waga produktu": Spec(FRAME, "Frame", "Bike Weight"),
    "waga": Spec(FRAME, "Frame", "Bike Weight"),
    "waga roweru": Spec(FRAME, "Frame", "Bike Weight"),
    "dopuszczalna waga": Spec(FRAME, "Frame", "Max Load"),
    "dopuszczalne obciążenie": Spec(FRAME, "Frame", "Max Load"),
    "maksymalne obciążenie": Spec(FRAME, "Frame", "Max Load"),
    "maksymalna waga użytkownika": Spec(FRAME, "Frame", "Max Rider Weight"),
    "wzrost użytkownika": Spec(FRAME, "Frame", "Rider Height"),
    "zalecany wzrost": Spec(FRAME, "Frame", "Rider Height"),
    "wiek dziecka": Spec(FRAME, "Frame", "Rider Age"),
    "przeznaczenie": Spec(FRAME, "Frame", "Intended Use"),
    # ── Rama ──────────────────────────────────────────────────────────────
    FRAME_SIZE_LABEL: Spec(FRAME, "Frame", SIZES_KEY),
    FRAME_SIZE_INCH_LABEL: Spec(FRAME, "Frame", "Frame Size"),
    "materiał ramy": Spec(FRAME, "Frame", "Material"),
    "rama": Spec(FRAME, "Frame", "Model"),
    "typ ramy": Spec(FRAME, "Frame", "Frame Type"),
    "geometria": Spec(FRAME, "Frame", "Geometry"),
    "widelec": Component(FRAME, "Fork"),
    "amortyzator": Component(FRAME, "Fork"),
    "skok widelca": Spec(FRAME, "Fork", "Travel"),
    "skok amortyzatora": Spec(FRAME, "Fork", "Travel"),
    "damper": Component(FRAME, "Rear Shock"),
    "amortyzator tylny": Component(FRAME, "Rear Shock"),
    "dampery": Component(FRAME, "Rear Shock"),
    "skok tylnego zawieszenia": Spec(FRAME, "Rear Shock", "Travel"),
    "skok dampera": Spec(FRAME, "Rear Shock", "Travel"),
    "stery": Component(COCKPIT, "Headset"),
    "zacisk sztycy": Component(FRAME, "Seatpost Clamp"),
    "obejma sztycy": Component(FRAME, "Seatpost Clamp"),
    "obejma siodła": Component(FRAME, "Seatpost Clamp"),
    # ── Napęd ─────────────────────────────────────────────────────────────
    "napęd": Spec(DRIVETRAIN, "Gearing", "Configuration"),
    "liczba biegów": Spec(DRIVETRAIN, "Gearing", "Gears"),
    "grupa osprzętu": Component(DRIVETRAIN, "Groupset"),
    "przerzutka przednia": Component(DRIVETRAIN, "Front Derailleur"),
    "przerzutka tylna": Component(DRIVETRAIN, "Rear Derailleur"),
    "manetki": Component(DRIVETRAIN, "Shifters"),
    "manetka": Component(DRIVETRAIN, "Shifters"),
    "klamkomanetki": Component(DRIVETRAIN, "Shifters"),
    "mechanizm korbowy": Component(DRIVETRAIN, "Crank"),
    "korba": Component(DRIVETRAIN, "Crank"),
    "zębatka": Component(DRIVETRAIN, "Chainring"),
    "kaseta/wolnobieg": Component(DRIVETRAIN, "Cassette"),
    "kaseta": Component(DRIVETRAIN, "Cassette"),
    "wolnobieg": Component(DRIVETRAIN, "Freewheel"),
    "łańcuch": Component(DRIVETRAIN, "Chain"),
    "pasek": Component(DRIVETRAIN, "Belt"),
    "wkład suportu": Component(DRIVETRAIN, "Bottom Bracket"),
    "suport": Component(DRIVETRAIN, "Bottom Bracket"),
    "osłona łańcucha": Component(DRIVETRAIN, "Chain Guard"),
    "piasta z przerzutką": Component(DRIVETRAIN, "Gear Hub"),
    # ── Hamulce ───────────────────────────────────────────────────────────
    "typ hamulców": Spec(BRAKES, "Brakes", "Type"),
    "rodzaj hamulców": Spec(BRAKES, "Brakes", "Type"),
    "hamulce p/t": Component(BRAKES, "Brakes"),
    "hamulce": Component(BRAKES, "Brakes"),
    "hamulec przedni": Component(BRAKES, "Brake Front"),
    "hamulec tylny": Component(BRAKES, "Brake Rear"),
    "tarcze hamulcowe": Component(BRAKES, "Brake Rotor"),
    "tarcze": Component(BRAKES, "Brake Rotor"),
    "średnica tarcz": Spec(BRAKES, "Brake Rotor", "Size"),
    "dźwignie hamulcowe": Component(BRAKES, "Brake Lever"),
    "dźwignie hamulca": Component(BRAKES, "Brake Lever"),
    "klamki hamulcowe": Component(BRAKES, "Brake Lever"),
    # ── Koła ──────────────────────────────────────────────────────────────
    WHEEL_SIZE_LABEL: Spec(WHEELS, "Wheelset", WHEEL_SIZE_KEY),
    "koła": Component(WHEELS, "Wheelset"),
    "obręcze": Component(WHEELS, "Rims"),
    "piasty": Component(WHEELS, "Hubs"),
    "piasta przednia": Component(WHEELS, "Hub (Front)"),
    "piasta tylna": Component(WHEELS, "Hub (Rear)"),
    "szprychy": Component(WHEELS, "Spokes"),
    "opony p/t": Component(WHEELS, "Tyres"),
    "opony": Component(WHEELS, "Tyres"),
    "opona przednia": Component(WHEELS, "Front Tyre"),
    "opona tylna": Component(WHEELS, "Rear Tyre"),
    "dętki": Component(WHEELS, "Tubes"),
    "rodzaj osi - przód": Component(WHEELS, "Axles", "Oś przednia"),
    "rodzaj osi - tył": Component(WHEELS, "Axles", "Oś tylna"),
    # ── Komponenty ────────────────────────────────────────────────────────
    "kierownica": Component(COCKPIT, "Handlebar"),
    "wspornik kierownicy": Component(COCKPIT, "Stem"),
    "mostek": Component(COCKPIT, "Stem"),
    "chwyty": Component(COCKPIT, "Grips"),
    "owijka": Component(COCKPIT, "Bar Tape"),
    "siodło": Component(SADDLE, "Saddle"),
    "siodełko": Component(SADDLE, "Saddle"),
    "wspornik siodła": Component(SADDLE, "Seatpost"),
    "sztyca": Component(SADDLE, "Seatpost"),
    "sztyca regulowana": Component(SADDLE, "Seatpost"),
    "oświetlenie": Component(LIGHTING, "Lights"),
    "oświetlenie przednie": Component(LIGHTING, "Front Light"),
    "lampka przednia": Component(LIGHTING, "Front Light"),
    "oświetlenie tylne": Component(LIGHTING, "Rear Light"),
    "lampka tylna": Component(LIGHTING, "Rear Light"),
    "odblaski": Component(LIGHTING, "Reflectors"),
    "pedały": Component(ACCESSORIES, "Pedals"),
    "bagażnik": Component(ACCESSORIES, "Rack"),
    "bagażnik tylny": Component(ACCESSORIES, "Rear Rack"),
    "bagażnik przedni": Component(ACCESSORIES, "Front Carrier"),
    "błotniki": Component(ACCESSORIES, "Fenders"),
    "nóżka": Component(ACCESSORIES, "Kickstand"),
    "stopka": Component(ACCESSORIES, "Kickstand"),
    "podpórka": Component(ACCESSORIES, "Kickstand"),
    "dzwonek": Component(ACCESSORIES, "Bell"),
    "koszyk": Component(ACCESSORIES, "Basket"),
    "zapięcie": Component(ACCESSORIES, "Lock"),
    "blokada": Component(ACCESSORIES, "Lock"),
    "lusterko": Component(ACCESSORIES, "Mirrors"),
    "pompka": Component(ACCESSORIES, "Pump"),
    "wyposażenie dodatkowe": Component(ACCESSORIES, "Included Items"),
    "wyposażenie": Component(ACCESSORIES, "Included Items"),
    "kółka boczne": Component(ACCESSORIES, "Included Items", "Kółka boczne"),
    # ── Silnik (e-bike) ───────────────────────────────────────────────────
    "model silnika": Component(ELECTRIC, "Motor"),
    "silnik": Component(ELECTRIC, "Motor"),
    "moc silnika": Spec(ELECTRIC, "Motor", "Power"),
    "maksymalny moment obrotowy": Spec(ELECTRIC, "Motor", "Torque"),
    "moment obrotowy": Spec(ELECTRIC, "Motor", "Torque"),
    "umiejscowienie silnika": Spec(ELECTRIC, "Motor", "Position"),
    "wyświetlacz / przełącznik": Component(ELECTRIC, "Display & Controls"),
    "wyświetlacz": Component(ELECTRIC, "Display"),
    "sterownik": Component(ELECTRIC, "Controller"),
    "czujnik": Component(ELECTRIC, "Sensors"),
    "tryby wspomagania": Spec(ELECTRIC, "Assist Modes", "Modes"),
    "prędkość maksymalna wspomagania": Spec(ELECTRIC, "Motor", "Top Speed"),
    "maksymalna prędkość": Spec(ELECTRIC, "Motor", "Top Speed"),
    # ── Akumulator (e-bike) ───────────────────────────────────────────────
    "model akumulatora": Component(ELECTRIC, "Battery"),
    "akumulator": Component(ELECTRIC, "Battery"),
    "pojemność akumulatora": Spec(ELECTRIC, "Battery", "Capacity"),
    "napięcie akumulatora": Spec(ELECTRIC, "Battery", "Voltage"),
    "napięcie": Spec(ELECTRIC, "Battery", "Voltage"),
    "umiejscowienie akumulatora": Spec(ELECTRIC, "Battery", "Position"),
    "zasięg": Spec(ELECTRIC, "Battery", "Range"),
    "ładowarka": Spec(ELECTRIC, "Charger", "Output"),
    "czas ładowania": Spec(ELECTRIC, "Charger", "Charging Time"),
}


def normalise_label(label: str) -> str:
    """'Rozmiar  ramy ' → 'rozmiar ramy' (lower-case, single spaces)."""
    return " ".join((label or "").replace("\xa0", " ").split()).lower()


def lookup(label: str) -> Optional[Mapping]:
    return SPEC_MAP.get(normalise_label(label))
