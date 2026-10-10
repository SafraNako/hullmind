import pytest

from hullmind import hazmat as h
from hullmind import ship as s


def test_concentration_from_masses_and_from_a_stated_value():
    assert h.HazmatItem("B-3", "akü", 8000.0, substance_kg=7200.0).concentration() == pytest.approx(900000.0)
    assert h.HazmatItem("A-2", "kablo", 1500.0, concentration_mg_per_kg=80.0).concentration() == 80.0
    assert h.HazmatItem("A-1", "yalıtım", 1000.0, substance_kg=1.0).concentration() == pytest.approx(1000.0)  # 0.1 %


def test_listing_rule_at_the_thresholds():
    assert not h.is_listed("A-1", 1000.0) and h.is_listed("A-1", 1000.1)  # asbestos: above 0.1 %
    assert not h.is_listed("A-2", 50.0) and h.is_listed("A-2", 51.0)  # PCBs
    assert not h.is_listed("B-1", 100.0) and h.is_listed("B-1", 101.0)  # cadmium
    assert not h.is_listed("B-9", 10000.0) and h.is_listed("B-9", 10001.0)  # short-chain chlorinated paraffins, 1 %
    assert not h.is_listed("A-4", 2500.0) and h.is_listed("A-4", 2501.0)  # organotin anti-fouling
    for code in ("A-3", "B-8"):  # no threshold value: any quantity is listed
        assert h.is_listed(code, 1e-9) and not h.is_listed(code, 0.0)


def test_screening_and_removal_masses():
    ship = s.example_ship("dokme-yuk", 11500, 1998)
    findings = h.screen(list(ship.hazmat))
    flags = {f.entry.code: f.listed for f in findings}
    assert flags == {"A-1": True, "A-2": True, "A-3": True, "A-4": True, "B-3": True, "B-4": False}
    removal = h.removal_mass_by_code(findings)
    assert removal == {"A-1": 4000.0, "A-2": 1500.0, "A-3": 120.0, "A-4": 6000.0, "B-3": 8000.0}
    assert sum(f.removal_mass_kg for f in findings) == sum(removal.values())


def test_input_errors():
    with pytest.raises(h.HazmatError):
        h.entry("Z-9")
    with pytest.raises(h.HazmatError):
        h.HazmatItem("A-1", "x", 0.0, substance_kg=0.0).concentration()
    with pytest.raises(h.HazmatError):
        h.HazmatItem("A-1", "x", 10.0, substance_kg=20.0).concentration()
    with pytest.raises(h.HazmatError):
        h.HazmatItem("A-1", "x", 10.0).concentration()
    with pytest.raises(h.HazmatError):
        h.HazmatItem("A-1", "x", 10.0, concentration_mg_per_kg=-1.0).concentration()
    with pytest.raises(h.HazmatError):
        h.is_listed("A-1", -1.0)
