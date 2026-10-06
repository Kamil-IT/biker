"""Closed list of bike categories (the `bike.category` column; NULL = unknown).

English values, stored as is. Nothing validates on write — this is the one place
the list lives. Dependency-free on purpose: the migration script and the discovery
scraper import it.
"""
from typing import Optional

BIKE_CATEGORIES = [
    "MTB", "Gravel", "Road", "Cyclocross", "Trekking", "Cross", "City", "Kids",
    "Youth", "Balance", "Triathlon", "Folding", "BMX", "Electric", "Electric cargo",
    "Hybrid/Commuter", "Touring", "Cruiser",
]

# centrumrowerowe.pl bike_type (Polish, looked up by strip().lower()) -> category.
# Keys are already lower-case.
POLISH_TO_CATEGORY = {
    "mtb": "MTB",
    "gravel": "Gravel",
    "szosowy": "Road",
    "przełajowy": "Cyclocross",
    "trekkingowy": "Trekking",
    "crossowy": "Cross",
    "miejski": "City",
    "dziecięcy": "Kids",
    "młodzieżowy": "Youth",
    "biegowy": "Balance",
    "jeździk dziecięcy": "Balance",
    "triathlonowy": "Triathlon",
    "składak": "Folding",
    "bmx": "BMX",
    "elektryczny": "Electric",
    "elektryczny cargo": "Electric cargo",
}


def category_from_discovery(bike_type: Optional[str]) -> Optional[str]:
    """Category for a discovery `bike_type`; '' / None / unknown -> None."""
    if not bike_type:
        return None
    return POLISH_TO_CATEGORY.get(bike_type.strip().lower())
