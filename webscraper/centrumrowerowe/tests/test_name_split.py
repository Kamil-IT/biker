import pytest

from name_split import split_name


@pytest.mark.parametrize("raw, bike_type, company, model", [
    ("Rower trekkingowy ROMET Wagant 3", "trekkingowy", "ROMET", "Wagant 3"),
    ("Rower MTB CENTURION Backfire Fit Pro 800.27 HP2", "MTB", "CENTURION", "Backfire Fit Pro 800.27 HP2"),
    ("Rower MTB damski KROSS Espera 5.0 27.5", "MTB", "KROSS", "Espera 5.0 27.5"),
    ("Rower miejski damski ROMET Art Deco Classic", "miejski", "ROMET", "Art Deco Classic"),
    ("Rower elektryczny HAIBIKE Lyke CF 10", "elektryczny", "HAIBIKE", "Lyke CF 10"),
    ("Rower dziecięcy OXFELD WEE 16", "dziecięcy", "OXFELD", "WEE 16"),
    ("Rower MTB STEVENS Devil&#180;s Trail", "MTB", "STEVENS", "Devil´s Trail"),
    ("Rower gravel GHOST Urban Asket ", "gravel", "GHOST", "Urban Asket"),
    ("Rower szosowy VAN RYSEL RCR Pro", "szosowy", "VAN RYSEL", "RCR Pro"),
    ("Rower trekkingowy Kross Trans 3", "trekkingowy", "Kross", "Trans 3"),      # mixed-case brand
    ("Rower ROMET Wagant 3", None, "ROMET", "Wagant 3"),                           # no type
    ("Gravel KROSS Esker 2.0", "Gravel", "KROSS", "Esker 2.0"),                   # no "Rower" prefix
    ("KROSS Trans 3", None, "KROSS", "Trans 3"),
])
def test_split(raw, bike_type, company, model):
    parts = split_name(raw)
    assert (parts.bike_type, parts.company, parts.model) == (bike_type, company, model)


@pytest.mark.parametrize("raw", ["", "   ", "Rower", "Rower MTB", "KROSS", "Rower trekkingowy", None])
def test_never_empty_never_raises(raw):
    parts = split_name(raw)
    assert parts.company and parts.model
