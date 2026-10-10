"""Cost-revenue statement of a dismantling job, the break-even bid, and Monte Carlo risk.

All money formulas live in :func:`profit`, which works on scalars and on numpy arrays, so the
deterministic statement, the Monte Carlo and the sensitivity analysis are the same arithmetic.

Price and cost defaults are ILLUSTRATIVE placeholders, not market data: set them from current
quotes. What the module guarantees is the arithmetic and its internal consistency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats as sps

from .cutting import CutParams, CuttingModel, kerf_loss_fraction
from .hazmat import Finding, removal_mass_by_code
from .schedule import Schedule
from .ship import Ship


class EconomicsError(ValueError):
    """Invalid price, cost or risk parameter."""


@dataclass(frozen=True)
class Market:
    steel_usd_t: float = 350.0  # scrap steel price (ILLUSTRATIVE)
    nonferrous_usd_t: float = 4500.0  # mixed copper / aluminium / brass / stainless lot (ILLUSTRATIVE)
    equipment_resale_usd: float = 40000.0  # re-usable equipment sold as it is (ILLUSTRATIVE)
    waste_disposal_usd_t: float = 120.0  # non-hazardous residues (ILLUSTRATIVE)
    hazmat_usd_per_kg: float = 4.0  # removal and disposal of listed hazardous material (ILLUSTRATIVE)

    def validate(self) -> None:
        for name, value in self.__dict__.items():
            if value < 0:
                raise EconomicsError(f"{name} negatif olamaz")


@dataclass(frozen=True)
class Yard:
    team_usd_per_day: float = 900.0  # crew and consumables of one cutting team-day, paid for worked time (ILLUSTRATIVE)
    team_mobilization_usd: float = 15000.0  # torches, rigging, supervision per team (ILLUSTRATIVE)
    hours_per_day: float = 8.0
    overhead_usd_per_day: float = 1500.0  # supervision, utilities, site (ILLUSTRATIVE)
    towing_usd: float = 60000.0
    delivery_days: float = 20.0  # from purchase to the start of cutting
    fees_fraction_of_revenue: float = 0.04  # port, tax, brokerage
    financing_per_year: float = 0.08  # cost of money on the purchase price

    def validate(self) -> None:
        if self.hours_per_day <= 0 or self.team_usd_per_day < 0 or self.overhead_usd_per_day < 0:
            raise EconomicsError("geçersiz tersane parametreleri")
        if not 0.0 <= self.fees_fraction_of_revenue < 1.0 or self.financing_per_year < 0 or self.delivery_days < 0:
            raise EconomicsError("geçersiz oran ya da gün sayısı")


@dataclass(frozen=True)
class Parts:
    """The physical quantities and the rates; everything :func:`profit` needs."""

    ldt: float
    steel_t: float  # recovered, after the kerf loss
    kerf_loss_t: float
    nonferrous_t: float
    other_t: float
    hazmat_kg: float
    makespan_h: float
    work_hours: float  # team-hours actually worked
    teams: int
    bid_usd_per_ldt: float
    market: Market
    yard: Yard

    @property
    def days(self) -> float:
        return self.makespan_h / self.yard.hours_per_day

    @property
    def purchase_usd(self) -> float:
        return self.bid_usd_per_ldt * self.ldt


def recovered_steel(ship: Ship, cut: CutParams) -> Tuple[float, float]:
    """Steel that reaches the scrap pile and the steel burned away in the kerf, both in tonnes."""
    model = CuttingModel(cut.fuel)
    kept = lost = 0.0
    for b in ship.blocks:
        t_used, _ = model.clamp(b.plate_mm)
        steel = b.mass_t * b.steel_share
        loss = steel * kerf_loss_fraction(t_used, model.kerf_mm(t_used), cut.piece_m, cut.complexity)
        kept += steel - loss
        lost += loss
    return kept, lost


def make_parts(
    ship: Ship, cut: CutParams, schedule: Schedule, findings: Sequence[Finding],
    market: Market, yard: Yard, bid_usd_per_ldt: float,
) -> Parts:
    market.validate()
    yard.validate()
    if schedule.makespan <= 0 or schedule.teams < 1 or bid_usd_per_ldt < 0:
        raise EconomicsError("geçersiz süre, ekip sayısı ya da teklif")
    kept, lost = recovered_steel(ship, cut)
    hazmat_kg = sum(removal_mass_by_code(list(findings)).values())
    return Parts(ship.ldt, kept, lost, ship.nonferrous_t(), ship.other_t(), hazmat_kg, schedule.makespan,
                 schedule.busy_hours(), schedule.teams, bid_usd_per_ldt, market, yard)


def profit(parts: Parts, steel_price=None, nonferrous_price=None, prod=1.0, hazmat=1.0, bid=None):
    """Net profit in USD. Scalars or numpy arrays.

    ``steel_price`` / ``nonferrous_price`` default to the market values; ``prod`` multiplies the
    duration (1.2 = twenty per cent slower); ``hazmat`` multiplies the hazardous-material quantity;
    ``bid`` overrides the bid in USD per LDT.
    """
    m, y = parts.market, parts.yard
    steel_price = m.steel_usd_t if steel_price is None else steel_price
    nonferrous_price = m.nonferrous_usd_t if nonferrous_price is None else nonferrous_price
    bid = parts.bid_usd_per_ldt if bid is None else bid
    revenue = parts.steel_t * steel_price + parts.nonferrous_t * nonferrous_price + m.equipment_resale_usd
    days = parts.days * prod
    labor = parts.work_hours * prod / y.hours_per_day * y.team_usd_per_day + parts.teams * y.team_mobilization_usd
    overhead = days * y.overhead_usd_per_day
    financing = bid * parts.ldt * y.financing_per_year * (days + y.delivery_days) / 365.0
    costs = (bid * parts.ldt + labor + overhead + financing + y.towing_usd + parts.other_t * m.waste_disposal_usd_t
             + parts.hazmat_kg * hazmat * m.hazmat_usd_per_kg + y.fees_fraction_of_revenue * revenue)
    return revenue - costs


@dataclass(frozen=True)
class Statement:
    lines: Dict[str, float]  # signed USD: revenue positive, costs negative
    profit: float
    margin: float  # profit / revenue


def statement(parts: Parts) -> Statement:
    m, y = parts.market, parts.yard
    steel = parts.steel_t * m.steel_usd_t
    nonferrous = parts.nonferrous_t * m.nonferrous_usd_t
    revenue = steel + nonferrous + m.equipment_resale_usd
    days = parts.days
    lines = {
        "Çelik hurda geliri": steel,
        "Demir dışı metal geliri": nonferrous,
        "Ekipman satışı": m.equipment_resale_usd,
        "Gemi satın alma bedeli": -parts.purchase_usd,
        "Ekip işçiliği, sarf ve seferberlik": -(parts.work_hours / y.hours_per_day * y.team_usd_per_day
                                              + parts.teams * y.team_mobilization_usd),
        "Tersane genel gideri": -days * y.overhead_usd_per_day,
        "Finansman": -parts.bid_usd_per_ldt * parts.ldt * y.financing_per_year * (days + y.delivery_days) / 365.0,
        "Römork ve çekme": -y.towing_usd,
        "Atık bertarafı": -parts.other_t * m.waste_disposal_usd_t,
        "Tehlikeli madde giderimi": -parts.hazmat_kg * m.hazmat_usd_per_kg,
        "Harç, vergi, komisyon": -y.fees_fraction_of_revenue * revenue,
    }
    total = sum(lines.values())
    return Statement(lines, total, total / revenue if revenue else float("nan"))


def breakeven_steel_price(parts: Parts, target_profit: float = 0.0) -> float:
    """Steel price at which the profit equals ``target_profit`` (profit is linear in the price)."""
    p0 = profit(parts, steel_price=0.0)
    slope = parts.steel_t * (1.0 - parts.yard.fees_fraction_of_revenue)
    if slope <= 0:
        raise EconomicsError("geri kazanılan çelik yok")
    return (target_profit - p0) / slope


def max_bid_usd_per_ldt(parts: Parts, margin: float = 0.0) -> float:
    """Highest bid with a profit of ``margin`` times the revenue (profit is linear in the bid)."""
    p0 = profit(parts, bid=0.0)
    p1 = profit(parts, bid=1.0)
    slope = p1 - p0  # negative: every dollar of bid per LDT costs this much
    revenue = parts.steel_t * parts.market.steel_usd_t + parts.nonferrous_t * parts.market.nonferrous_usd_t \
        + parts.market.equipment_resale_usd
    return (margin * revenue - p0) / slope


# ---------------------------------------------------------------------------
# risk
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Risk:
    sigma_steel: float = 0.25  # relative volatility of the scrap price over the job
    sigma_nonferrous: float = 0.20
    sigma_productivity: float = 0.15  # relative spread of the duration
    sigma_hazmat: float = 0.30  # relative spread of the hazardous-material quantity

    def validate(self) -> None:
        if min(self.sigma_steel, self.sigma_nonferrous, self.sigma_productivity, self.sigma_hazmat) < 0:
            raise EconomicsError("belirsizlik parametreleri negatif olamaz")


def lognormal_unit_mean(rng: np.random.Generator, sigma: float, n: int) -> np.ndarray:
    """Draws with mean exactly 1 and relative standard deviation ``sqrt(exp(sigma^2) - 1)``."""
    if sigma == 0:
        return np.ones(n)
    return rng.lognormal(mean=-0.5 * sigma * sigma, sigma=sigma, size=n)


@dataclass(frozen=True)
class RiskResult:
    n: int
    mean: float
    std: float
    percentiles: Dict[int, float]
    prob_loss: float
    cvar5: float  # mean of the worst 5 %
    samples: np.ndarray


def monte_carlo(parts: Parts, risk: Risk = Risk(), n: int = 200_000, seed: Optional[int] = None) -> RiskResult:
    risk.validate()
    if n < 1000:
        raise EconomicsError("Monte Carlo için en az 1000 çekiliş gerekir")
    rng = np.random.default_rng(seed)
    price = parts.market.steel_usd_t * lognormal_unit_mean(rng, risk.sigma_steel, n)
    nf_price = parts.market.nonferrous_usd_t * lognormal_unit_mean(rng, risk.sigma_nonferrous, n)
    prod = lognormal_unit_mean(rng, risk.sigma_productivity, n)
    hz = lognormal_unit_mean(rng, risk.sigma_hazmat, n)
    result = profit(parts, price, nf_price, prod, hz)
    cut = np.quantile(result, 0.05)
    return RiskResult(
        n=n, mean=float(result.mean()), std=float(result.std(ddof=1)),
        percentiles={q: float(np.quantile(result, q / 100.0)) for q in (5, 25, 50, 75, 95)},
        prob_loss=float(np.mean(result < 0.0)), cvar5=float(result[result <= cut].mean()), samples=result,
    )


def analytic_steel_only(parts: Parts, sigma: float) -> Dict[str, float]:
    """Exact profit distribution when only the steel price is random (lognormal, mean = the market price).

    Profit is ``a P + b`` with ``a = steel_t (1 - fee)``, so its mean, standard deviation, the loss
    probability and the quantiles follow from the lognormal law of ``P``.
    """
    if sigma <= 0:
        raise EconomicsError("sigma pozitif olmalı")
    a = parts.steel_t * (1.0 - parts.yard.fees_fraction_of_revenue)
    b = profit(parts, steel_price=0.0)
    p0 = parts.market.steel_usd_t
    mu = math.log(p0) - 0.5 * sigma**2
    dist = sps.lognorm(s=sigma, scale=math.exp(mu))
    p_be = -b / a
    return {
        "mean": a * p0 + b,
        "std": a * p0 * math.sqrt(math.exp(sigma**2) - 1.0),
        "prob_loss": float(dist.cdf(p_be)) if p_be > 0 else 0.0,
        "p5": a * float(dist.ppf(0.05)) + b,
        "p50": a * float(dist.ppf(0.50)) + b,
        "p95": a * float(dist.ppf(0.95)) + b,
    }


# ---------------------------------------------------------------------------
# sensitivity
# ---------------------------------------------------------------------------

def tornado(parts: Parts, rel: float = 0.2) -> List[Tuple[str, float, float]]:
    """Change in profit when each input is moved by -``rel`` and +``rel`` (others fixed), largest swing first."""
    if not 0 < rel < 1:
        raise EconomicsError("göreli değişim (0, 1) aralığında olmalı")
    m, y = parts.market, parts.yard
    base = profit(parts)
    variants = {
        "Çelik fiyatı": lambda f: profit(parts, steel_price=m.steel_usd_t * f),
        "Demir dışı fiyatı": lambda f: profit(parts, nonferrous_price=m.nonferrous_usd_t * f),
        "Teklif (USD/LDT)": lambda f: profit(parts, bid=parts.bid_usd_per_ldt * f),
        "Süre (verimlilik)": lambda f: profit(parts, prod=f),
        "Tehlikeli madde miktarı": lambda f: profit(parts, hazmat=f),
        "Ekip maliyeti": lambda f: profit(replace(parts, yard=replace(y, team_usd_per_day=y.team_usd_per_day * f))),
        "Genel gider": lambda f: profit(replace(parts, yard=replace(y, overhead_usd_per_day=y.overhead_usd_per_day * f))),
        "Geri kazanılan çelik": lambda f: profit(replace(parts, steel_t=parts.steel_t * f)),
    }
    rows = [(name, fn(1 - rel) - base, fn(1 + rel) - base) for name, fn in variants.items()]
    return sorted(rows, key=lambda r: -abs(r[2] - r[1]))
