import math

import numpy as np
import pytest

from hullmind import checks, cutting as c
from hullmind.data import ACETYLENE_ASF, PROPANE_PRC, STEEL_DENSITY_KG_M3


def test_model_reproduces_every_tabulated_speed_and_kerf():
    for fuel, table in (("asetilen", ACETYLENE_ASF), ("propan", PROPANE_PRC)):
        m = c.CuttingModel(fuel)
        for t, (v, k_lo, k_hi) in table.items():
            assert m.speed_mm_min(float(t)) == pytest.approx(v, rel=1e-12)
            assert m.kerf_mm(float(t)) == pytest.approx(0.5 * (k_lo + k_hi), rel=1e-12)


def test_loglog_interpolation_by_hand():
    m = c.CuttingModel()
    # between 10 mm (710) and 15 mm (630): speed = 710 * (t/10)^b with b = ln(630/710)/ln(1.5)
    b = math.log(630 / 710) / math.log(1.5)
    assert m.speed_mm_min(12.0) == pytest.approx(710 * 1.2**b, rel=1e-12)
    # and always between the neighbours, decreasing
    ts = np.linspace(3, 300, 400)
    speeds = [m.speed_mm_min(float(t)) for t in ts]
    assert all(a >= b - 1e-9 for a, b in zip(speeds, speeds[1:]))


def test_no_extrapolation_outside_the_table():
    m = c.CuttingModel()
    for t in (2.0, 301.0):
        with pytest.raises(c.CuttingError):
            m.speed_mm_min(t)
    assert m.clamp(2.0) == (3.0, True) and m.clamp(500.0) == (300.0, True) and m.clamp(20.0) == (20.0, False)
    with pytest.raises(c.CuttingError):
        c.CuttingModel("plazma")


def test_leave_one_out_interpolation_error_is_a_few_percent():
    e = checks.speed_interpolation_error("asetilen")
    assert e["n"] == 23 and e["max_abs"] < 0.07 and e["rms"] < 0.025 and e["median_abs"] < 0.012
    e2 = checks.speed_interpolation_error("propan")
    assert e2["n"] == 7 and e2["max_abs"] < 0.05
    errors = c.leave_one_out_errors()
    assert max(errors, key=lambda k: abs(errors[k])) == 200.0  # the sparsest part of the table (170 between 150 and 230)


def test_cut_length_per_tonne_formula_and_a_grid_of_pieces():
    t_mm, a = 14.0, 1.5
    assert c.cut_length_m_per_tonne(t_mm, a) == pytest.approx(2000 / (STEEL_DENSITY_KG_M3 * 0.014 * a))
    assert c.cut_length_m_per_tonne(t_mm, a, 1.3) == pytest.approx(1.3 * c.cut_length_m_per_tonne(t_mm, a))
    # an n x n grid of pieces: cut length (2(n-1) n a) over its mass; tends to the 2/(rho t a) rule as n grows
    for n, tolerance in ((10, 0.11), (200, 0.006)):
        length = 2 * (n - 1) * n * a
        mass_t = STEEL_DENSITY_KG_M3 * 0.014 * (n * a) ** 2 / 1000
        assert length / mass_t == pytest.approx(c.cut_length_m_per_tonne(t_mm, a), rel=tolerance)


def test_kerf_loss_raster_matches_exact_geometry_and_the_formula_in_the_limit():
    g = checks.kerf_geometry_check(3.0)
    assert g["raster"] == pytest.approx(g["exact"], rel=0.01)
    assert g["exact"] == pytest.approx(0.01)  # 3 mm x 4.8 m of cuts over 1.44 m^2
    assert c.exact_kerf_loss_fraction(60.0, 60.0, 4000, 4000, 3.0) == pytest.approx(c.kerf_loss_fraction(0, 3.0, 0.015), rel=1e-3)
    assert c.exact_kerf_loss_fraction(1.0, 1.0, 1, 1, 3.0) == 0.0  # uncut plate loses nothing
    # finer pieces mean more cutting and more kerf loss
    assert c.kerf_loss_fraction(14, 2.0, 0.75) == pytest.approx(2 * c.kerf_loss_fraction(14, 2.0, 1.5))


def test_raster_estimator_is_not_just_the_formula():
    # two cuts on a 3 m x 1 m plate: the measured loss follows the cut geometry, not a/2 rules of thumb
    assert checks.raster_kerf_loss(3.0, 1.0, 3, 1, 4.0, 1.0) == pytest.approx(2 * 0.004 * 1.0 / 3.0, rel=0.02)


def test_team_hours_and_their_dependence_on_parameters():
    base = c.CutParams()
    h14, clamped = c.cutting_hours_per_tonne(14, base)
    assert not clamped
    speed_m_h = c.CuttingModel().speed_mm_min(14) * 60 / 1000
    expected = 1.3 * 2000 / (STEEL_DENSITY_KG_M3 * 0.014 * 1.5) / (speed_m_h * 0.35 * 3)
    assert h14 == pytest.approx(expected)
    assert c.cutting_hours_per_tonne(14, c.CutParams(torches_per_team=6))[0] == pytest.approx(h14 / 2)
    assert c.cutting_hours_per_tonne(14, c.CutParams(piece_m=3.0))[0] == pytest.approx(h14 / 2)
    assert c.cutting_hours_per_tonne(14, c.CutParams(utilization=0.7))[0] == pytest.approx(h14 / 2)
    # thick plate holds more steel per metre of cut: fewer hours per tonne despite the lower speed
    assert c.cutting_hours_per_tonne(60, base)[0] < h14 < c.cutting_hours_per_tonne(6, base)[0]
    assert c.cutting_hours_per_tonne(1.0, base)[1] is True  # thinner than the table: clamped, and flagged


def test_parameter_validation():
    with pytest.raises(c.CuttingError):
        c.cut_length_m_per_tonne(0, 1.5)
    with pytest.raises(c.CuttingError):
        c.cut_length_m_per_tonne(10, -1)
    with pytest.raises(c.CuttingError):
        c.kerf_loss_fraction(10, 3, 1.5, 0.5)
    with pytest.raises(c.CuttingError):
        c.CutParams(utilization=0).validate()
    with pytest.raises(c.CuttingError):
        c.exact_kerf_loss_fraction(1, 1, 0, 1, 3)
