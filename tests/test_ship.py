import json

import pytest

from hullmind import checks, ship as s
from hullmind.cutting import CutParams


@pytest.mark.parametrize("kind", s.ship_types())
@pytest.mark.parametrize("ldt", [800.0, 11500.0, 53000.0])
def test_example_ships_are_consistent(kind, ldt):
    ship = s.example_ship(kind, ldt, 2005)
    ship.validate()
    assert sum(b.mass_t for b in ship.blocks) == pytest.approx(ldt, rel=1e-12)
    assert ship.steel_t() + ship.nonferrous_t() + ship.other_t() == pytest.approx(ldt, rel=1e-12)
    order = s.topological_order(ship)
    position = {n: i for i, n in enumerate(order)}
    assert sorted(order) == sorted(b.name for b in ship.blocks)
    for b in ship.blocks:
        for dep in b.after:
            if dep != s.PREP:
                assert position[dep] < position[b.name]


def test_steel_share_of_the_lightship_is_realistic_for_the_default_blocks():
    ship = s.example_ship("dokme-yuk", 11500, 1998)
    assert 0.90 <= ship.steel_t() / ship.ldt <= 0.95  # sources quote about 90 % and more of a ship as steel


def test_old_ships_carry_a_hazmat_survey_new_ones_do_not():
    assert s.example_ship(build_year=1998).hazmat and not s.example_ship(build_year=2010).hazmat


def test_json_round_trip(tmp_path):
    ship = s.example_ship("tanker", 20000, 1995, "TEST")
    path = tmp_path / "gemi.json"
    s.save(ship, path)
    assert json.loads(path.read_text(encoding="utf-8"))["ad"] == "TEST"
    assert s.load(path) == ship


def _block(name, mass=100.0, after=(), steel=0.9, nf=0.01):
    return s.Block(name, mass, 12.0, steel, nf, tuple(after))


def test_validation_errors():
    def ship(blocks, ldt=None):
        return s.Ship("t", "x", ldt if ldt is not None else sum(b.mass_t for b in blocks), 2000, tuple(blocks))

    ship([_block("a"), _block("b", after=("a",))]).validate()
    with pytest.raises(s.ShipError, match="benzersiz"):
        ship([_block("a"), _block("a")]).validate()
    with pytest.raises(s.ShipError, match="benzersiz"):
        ship([_block(s.PREP)]).validate()
    with pytest.raises(s.ShipError, match="bilinmeyen bağımlılık"):
        ship([_block("a", after=("yok",))]).validate()
    with pytest.raises(s.ShipError, match="döngü"):
        ship([_block("a", after=("b",)), _block("b", after=("a",))]).validate()
    with pytest.raises(s.ShipError, match="LDT"):
        ship([_block("a")], ldt=500.0).validate()
    with pytest.raises(s.ShipError, match="payları"):
        ship([_block("a", steel=0.9, nf=0.2)]).validate()
    with pytest.raises(s.ShipError):
        ship([]).validate()
    with pytest.raises(s.ShipError):
        s.example_ship("yelkenli")
    with pytest.raises(s.ShipError):
        s.from_dict({"ad": "x"})
    with pytest.raises(s.ShipError):
        s.load("/yok/gemi.json")


def test_mass_balance_closes_exactly_for_every_type_and_fuel():
    for kind in s.ship_types():
        ship = s.example_ship(kind, 17000, 1990)
        for fuel in ("asetilen", "propan"):
            mb = checks.mass_balance(ship, CutParams(fuel=fuel))
            assert mb["fark (LDT - toplam)"] == pytest.approx(0.0, abs=1e-9)
            assert mb["kerf kaybı"] > 0 and mb["çelik hurda"] + mb["kerf kaybı"] == pytest.approx(ship.steel_t())
    # propane's wider kerf burns away more steel than acetylene's
    ship = s.example_ship()
    assert checks.mass_balance(ship, CutParams(fuel="propan"))["kerf kaybı"] > checks.mass_balance(ship, CutParams())["kerf kaybı"]
