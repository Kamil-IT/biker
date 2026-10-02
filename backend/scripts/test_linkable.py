"""Unit tests for app/linkable.py — the regex heuristic behind bike_component.is_linkable
(ISSUE-016) used by scripts/migrate_component_linkable.py and the discovery scraper.
No server, no network, no AI. Run: cd backend && pytest   (collected via pytest.ini)"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.linkable import is_linkable  # noqa: E402


@pytest.mark.parametrize("name", [
    "Giant Multi-Tool",
    "Shimano Deore RD-M6000",
    "Kona JS2",
    "FP-804",
    "SDG Bel-Air V3",
    "Tektro Hydraulic Disc Brake",
    "Sturmey Archer Hub Brake",
    "Maxxis Minion DHF (Front)",
    "Early Rider CNC'd AL6061 Platform Pedals",
    "Lectric Aluminum Pedals",
    "Bosch Performance Line Gen.3",
    "Cane Creek 40",
    "Shimano",
])
def test_specific_products_are_linkable(name):
    assert is_linkable(name) is True


@pytest.mark.parametrize("name", [
    "", " ", "-", "x",
    "None", "None included", "Not included", "No tool included", "Pedals not included",
    "Not specified", "Not Specified", "n/a", "N/A", "Unknown",
    "brak", "brak w zestawie", "Brak danych", "nie dotyczy", "bez pedałów",
    "Sold separately",
])
def test_not_supplied_phrases_are_not_linkable(name):
    assert is_linkable(name, "Pedals") is False


@pytest.mark.parametrize("name", [
    "Owner's Manual", "User Manual", "Quick Start Guide", "Warranty Documentation",
    "Warranty card", "Registration card", "Instrukcja obsługi", "Karta gwarancyjna", "Dokumentacja",
    "Reflective stickers",
])
def test_paperwork_is_not_linkable(name):
    assert is_linkable(name, "Included Items") is False


@pytest.mark.parametrize("name", [
    "Pedals", "Alloy Pedals", "Alloy Platform Pedals", "Nylon Platform Pedals", "Composite Platform Pedals",
    "Standard pedals", "Rear Rack", "Integrated rear rack", "Custom Designed Rear Rack", "Fenders",
    "Polypropylene Fenders", "Kickstand", "Folding Kickstand", "Bell", "Aluminum Bell", "Multi-tool",
    "Basic Tool Kit", "Hydraulic Disc Brake", "Coaster Brake", "Standard Reflectors", "Reflector Set",
    "Sealed Cartridge Bottom Bracket", "Forged Aluminum Crankset", "3-piece crankset", "BSA",
    "Steel Fork", "Aluminum Seatpost", "Frame-Fitted Pump", "Chainstay Protector", "Chain Guard",
    "LCD Display", "Threadless Headset", "Comfort Saddle", "Standard 2 amp charger",
    "Szybkozamykacz (QR) 9x100 mm", "Sztywna oś (Boost) 12x148 mm", "Nakrętki 9x135 mm",
    "Brake-activated rear light with turn signals",
])
def test_generic_parts_without_a_brand_are_not_linkable(name):
    assert is_linkable(name, "Accessories") is False


@pytest.mark.parametrize("name,sub", [
    ("Frame", "Frame"), ("Gearing", "Gearing"), ("Wheelset", "Wheelset"), ("Charger", "Charger"),
    ("tool", "Tool"), ("Seatpost Clamp", "Seatpost Clamp"),
])
def test_name_repeating_its_subcategory_is_not_linkable(name, sub):
    assert is_linkable(name, sub) is False


@pytest.mark.parametrize("name", ["180mm Rotor", "27.5\" Wheels", "9/16\" Composite Platform Pedals",
                                  "8-Speed Freewheel", "602 Hydraulic Brake Lever", "34.9mm Seat Clamp",
                                  "500Wh battery", "2x12s drivetrain"])
def test_measurements_do_not_count_as_model_codes(name):
    assert is_linkable(name) is False


def test_polish_letters_fold_onto_the_vocabulary():
    assert is_linkable("Błotniki stalowe") is False
    assert is_linkable("Łańcuch KMC X9") is True


def test_subcategory_is_optional():
    assert is_linkable("Kona JS2") is True
    assert is_linkable("Pedals") is False
