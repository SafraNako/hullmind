import math

import numpy as np
import pytest
from scipy import optimize

from hullmind import analysis, checks, cutting, economics as eco, ship as s


@pytest.fixture(scope="module")
def parts():
    a = analysis.analyse(s.example_ship("dokme-yuk", 11500, 1998), cutting.CutParams(), 10, 240.0)
    return a.parts


def test_statement_lines_add_up_to_the_profit_function(parts):
    st = eco.statement(parts)
    assert sum(st.lines.values()) == pytest.approx(st.profit, rel=1e-12)
    assert st.profit == pytest.approx(eco.profit(parts), rel=1e-12)
    revenue = sum(v for v in st.lines.values() if v > 0)
    assert st.margin == pytest.approx(st.profit / revenue)
    assert st.lines["Gemi satın alma bedeli"] == pytest.approx(-240.0 * parts.ldt)


def test_each_line_follows_its_closed_form(parts):
    st, m, y = eco.statement(parts), parts.market, parts.yard
    assert st.lines["Çelik hurda geliri"] == pytest.approx(parts.steel_t * m.steel_usd_t)
    assert st.lines["Finansman"] == pytest.approx(-240.0 * parts.ldt * y.financing_per_year * (parts.days + y.delivery_days) / 365.0)
    assert st.lines["Ekip işçiliği, sarf ve seferberlik"] == pytest.approx(
        -(parts.work_hours / y.hours_per_day * y.team_usd_per_day + parts.teams * y.team_mobilization_usd))
    assert st.lines["Tersane genel gideri"] == pytest.approx(-parts.days * y.overhead_usd_per_day)
    revenue = parts.steel_t * m.steel_usd_t + parts.nonferrous_t * m.nonferrous_usd_t + m.equipment_resale_usd
    assert st.lines["Harç, vergi, komisyon"] == pytest.approx(-y.fees_fraction_of_revenue * revenue)
    assert st.lines["Tehlikeli madde giderimi"] == pytest.approx(-parts.hazmat_kg * m.hazmat_usd_per_kg)


def test_profit_is_linear_in_the_steel_price_with_the_expected_slope(parts):
    slope = parts.steel_t * (1 - parts.yard.fees_fraction_of_revenue)
    p1, p2 = eco.profit(parts, steel_price=300.0), eco.profit(parts, steel_price=400.0)
    assert (p2 - p1) / 100.0 == pytest.approx(slope, rel=1e-12)
    assert eco.profit(parts, steel_price=350.0) == pytest.approx(0.5 * (p1 + p2), rel=1e-12)


def test_breakeven_price_and_maximum_bid_solve_the_profit_equation(parts):
    p_be = eco.breakeven_steel_price(parts)
    root = optimize.brentq(lambda p: eco.profit(parts, steel_price=p), 1.0, 5000.0, xtol=1e-10)
    assert p_be == pytest.approx(root, rel=1e-9)
    assert eco.profit(parts, steel_price=p_be) == pytest.approx(0.0, abs=1e-4)
    assert eco.breakeven_steel_price(parts, 100000.0) > p_be
    bid0 = eco.max_bid_usd_per_ldt(parts)
    assert eco.profit(parts, bid=bid0) == pytest.approx(0.0, abs=1e-4)
    revenue = parts.steel_t * parts.market.steel_usd_t + parts.nonferrous_t * parts.market.nonferrous_usd_t + parts.market.equipment_resale_usd
    bid5 = eco.max_bid_usd_per_ldt(parts, 0.05)
    assert bid5 < bid0
    assert eco.profit(parts, bid=bid5) == pytest.approx(0.05 * revenue, rel=1e-9)


def test_duration_and_hazmat_multipliers_enter_as_derived(parts):
    y, m = parts.yard, parts.market
    d_prod = eco.profit(parts, prod=1.0) - eco.profit(parts, prod=1.1)
    time_cost = parts.work_hours / y.hours_per_day * y.team_usd_per_day + parts.days * y.overhead_usd_per_day \
        + parts.bid_usd_per_ldt * parts.ldt * y.financing_per_year * parts.days / 365.0
    assert d_prod == pytest.approx(0.1 * time_cost, rel=1e-9)
    assert eco.profit(parts, hazmat=1.0) - eco.profit(parts, hazmat=2.0) == pytest.approx(parts.hazmat_kg * m.hazmat_usd_per_kg)


def test_lognormal_draws_have_unit_mean_and_the_stated_spread():
    rng = np.random.default_rng(1)
    x = eco.lognormal_unit_mean(rng, 0.3, 1_000_000)
    assert x.mean() == pytest.approx(1.0, abs=4 * x.std() / 1000)
    assert x.std() == pytest.approx(math.sqrt(math.exp(0.09) - 1), rel=0.01)
    assert np.all(eco.lognormal_unit_mean(rng, 0.0, 10) == 1.0)


def test_monte_carlo_matches_the_exact_lognormal_result_when_only_steel_is_random(parts):
    r = checks.risk_vs_analytic(parts, sigma=0.25, n=400_000, seed=3)
    exact = eco.analytic_steel_only(parts, 0.25)
    se_mean = exact["std"] / math.sqrt(400_000)
    assert r["mean"][0] == pytest.approx(exact["mean"], abs=4.5 * se_mean)
    assert r["std"][0] == pytest.approx(exact["std"], rel=0.01)
    assert r["prob_loss"][0] == pytest.approx(exact["prob_loss"], abs=4.5 * math.sqrt(0.25 / 400_000))
    for key in ("p5", "p50", "p95"):
        assert r[key][0] == pytest.approx(exact[key], abs=0.02 * exact["std"])
    assert 0.0 < exact["prob_loss"] < 1.0


def test_monte_carlo_is_reproducible_ordered_and_validated(parts):
    a = eco.monte_carlo(parts, n=5000, seed=7)
    b = eco.monte_carlo(parts, n=5000, seed=7)
    assert np.array_equal(a.samples, b.samples)
    q = a.percentiles
    assert q[5] <= q[25] <= q[50] <= q[75] <= q[95]
    assert a.cvar5 <= q[5]
    assert a.prob_loss == pytest.approx(np.mean(a.samples < 0))
    zero = eco.monte_carlo(parts, eco.Risk(0, 0, 0, 0), n=2000, seed=1)
    assert zero.std == pytest.approx(0.0, abs=1e-6) and zero.mean == pytest.approx(eco.profit(parts))
    with pytest.raises(eco.EconomicsError):
        eco.monte_carlo(parts, n=10)
    with pytest.raises(eco.EconomicsError):
        eco.Risk(sigma_steel=-0.1).validate()
    with pytest.raises(eco.EconomicsError):
        eco.analytic_steel_only(parts, 0.0)


def test_tornado_is_the_finite_difference_of_the_profit_function(parts):
    rows = {name: (lo, hi) for name, lo, hi in eco.tornado(parts, 0.2)}
    slope = parts.steel_t * (1 - parts.yard.fees_fraction_of_revenue)
    steel_move = slope * 0.2 * parts.market.steel_usd_t
    assert rows["Çelik fiyatı"] == (pytest.approx(-steel_move), pytest.approx(steel_move))
    assert rows["Geri kazanılan çelik"] == (pytest.approx(-steel_move), pytest.approx(steel_move))
    bid_move = parts.ldt * 0.2 * parts.bid_usd_per_ldt * (1 + parts.yard.financing_per_year * (parts.days + parts.yard.delivery_days) / 365.0)
    assert rows["Teklif (USD/LDT)"] == (pytest.approx(bid_move), pytest.approx(-bid_move))
    swings = [abs(hi - lo) for _, lo, hi in eco.tornado(parts)]
    assert swings == sorted(swings, reverse=True)
    with pytest.raises(eco.EconomicsError):
        eco.tornado(parts, 1.5)


def test_input_validation(parts):
    with pytest.raises(eco.EconomicsError):
        eco.Market(steel_usd_t=-1).validate()
    with pytest.raises(eco.EconomicsError):
        eco.Yard(hours_per_day=0).validate()
    with pytest.raises(eco.EconomicsError):
        eco.Yard(fees_fraction_of_revenue=1.0).validate()


def test_team_scan_profit_matches_the_direct_computation_and_trades_time_against_idle_cost():
    ship = s.example_ship("dokme-yuk", 11500, 1998)
    market, yard = eco.Market(), eco.Yard()
    rows = analysis.team_scan(ship, cutting.CutParams(), 14, 240.0, market, yard)
    assert [r[0] for r in rows] == list(range(1, 15))
    direct = analysis.analyse(ship, cutting.CutParams(), 8, 240.0, market, yard)
    assert rows[7][3] == pytest.approx(eco.profit(direct.parts), rel=1e-12)
    assert rows[0][2] == pytest.approx(1.0)  # one team is always busy
    best = max(rows, key=lambda r: r[3])
    assert 2 < best[0] < 14 and best[3] > rows[0][3]  # neither one team nor the maximum is best
    for m, makespan, util, _ in rows:
        assert 0 < util <= 1.0 + 1e-9 and makespan > 0
