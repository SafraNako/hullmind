"""Self-checks of the models against independent methods; used by ``dogrulama`` and the tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from . import economics as eco
from . import schedule as sch
from .cutting import exact_kerf_loss_fraction, kerf_loss_fraction, leave_one_out_errors
from .cutting import CutParams
from .ship import Ship


def speed_interpolation_error(fuel: str = "asetilen") -> Dict[str, float]:
    """Leave-one-out error of the log-log interpolation of the manufacturer's cutting speeds."""
    errors = np.array(list(leave_one_out_errors(fuel).values()))
    return {"n": float(errors.size), "max_abs": float(np.max(np.abs(errors))), "rms": float(np.sqrt(np.mean(errors**2))),
            "median_abs": float(np.median(np.abs(errors)))}


def raster_kerf_loss(width_m: float, height_m: float, nx: int, ny: int, kerf_mm: float, pixel_mm: float) -> float:
    """Kerf loss of a plate cut into nx x ny pieces, measured by rasterizing the burned strips.

    A pixel is lost when it lies within half a kerf of an internal cut line. This uses no formula
    for the cut length, only the geometry of the lines.
    """
    px = pixel_mm / 1000.0
    nxp, nyp = int(round(width_m / px)), int(round(height_m / px))
    x = (np.arange(nxp) + 0.5) * px
    y = (np.arange(nyp) + 0.5) * px
    half = kerf_mm / 2000.0
    lost_x = np.zeros(nxp, dtype=bool)
    for i in range(1, nx):
        lost_x |= np.abs(x - i * width_m / nx) < half
    lost_y = np.zeros(nyp, dtype=bool)
    for j in range(1, ny):
        lost_y |= np.abs(y - j * height_m / ny) < half
    lost = lost_x[:, None] | lost_y[None, :]
    return float(lost.mean())


def kerf_geometry_check(kerf_mm: float = 3.0) -> Dict[str, float]:
    width = height = 1.2
    nx = ny = 3
    exact = exact_kerf_loss_fraction(width, height, nx, ny, kerf_mm)
    raster = raster_kerf_loss(width, height, nx, ny, kerf_mm, pixel_mm=kerf_mm / 6.0)
    big = exact_kerf_loss_fraction(60.0, 60.0, 40, 40, kerf_mm)  # large plate: tends to the 2*kerf/a rule
    return {"exact": exact, "raster": raster, "asymptotic_large_plate": big,
            "formula_large_plate": kerf_loss_fraction(10.0, kerf_mm, 1.5)}


def random_tasks(rng: np.random.Generator, n: int, edge_probability: float = 0.3, max_hours: int = 6) -> List[sch.Task]:
    tasks = []
    for j in range(n):
        preds = tuple(f"T{i}" for i in range(j) if rng.random() < edge_probability)
        tasks.append(sch.Task(f"T{j}", float(rng.integers(1, max_hours + 1)), preds))
    return tasks


@dataclass
class ScheduleStudy:
    instances: int
    exact_solvers_agree: int
    heuristic_optimal: int
    worst_ratio: float
    mean_ratio: float
    bound_violations: int
    lower_bound_violations: int


def schedule_study(instances: int = 40, n: int = 7, seed: int = 5, use_milp: bool = True) -> ScheduleStudy:
    """List scheduling against two independent exact solvers (brute force, and a MILP) on small random instances."""
    rng = np.random.default_rng(seed)
    agree = optimal = bound_bad = lb_bad = 0
    ratios = []
    for _ in range(instances):
        m = int(rng.integers(2, 4))
        tasks = random_tasks(rng, n)
        brute = sch.optimal_makespan_bruteforce(tasks, m)
        if use_milp:
            milp = sch.optimal_makespan_milp(tasks, m)
            agree += abs(milp - brute) < 1e-9
        else:
            agree += 1
        heuristic = sch.list_schedule(tasks, m).makespan
        ratios.append(heuristic / brute)
        optimal += abs(heuristic - brute) < 1e-9
        bound_bad += heuristic > sch.graham_bound(m) * brute + 1e-9
        lb_bad += brute < sch.lower_bound(tasks, m) - 1e-9
    return ScheduleStudy(instances, int(agree), int(optimal), float(max(ratios)), float(np.mean(ratios)),
                         int(bound_bad), int(lb_bad))


def risk_vs_analytic(parts: eco.Parts, sigma: float = 0.25, n: int = 400_000, seed: int = 3) -> Dict[str, Tuple[float, float]]:
    """Monte Carlo with only the steel price random against the exact lognormal result: (simulated, exact)."""
    risk = eco.Risk(sigma_steel=sigma, sigma_nonferrous=0.0, sigma_productivity=0.0, sigma_hazmat=0.0)
    mc = eco.monte_carlo(parts, risk, n, seed)
    exact = eco.analytic_steel_only(parts, sigma)
    return {"mean": (mc.mean, exact["mean"]), "std": (mc.std, exact["std"]), "prob_loss": (mc.prob_loss, exact["prob_loss"]),
            "p5": (mc.percentiles[5], exact["p5"]), "p50": (mc.percentiles[50], exact["p50"]),
            "p95": (mc.percentiles[95], exact["p95"])}


def mass_balance(ship: Ship, cut: CutParams) -> Dict[str, float]:
    kept, lost = eco.recovered_steel(ship, cut)
    parts = {"çelik hurda": kept, "kerf kaybı": lost, "demir dışı": ship.nonferrous_t(), "satılamayan kalan": ship.other_t()}
    parts["toplam"] = sum(parts.values())
    parts["fark (LDT - toplam)"] = ship.ldt - parts["toplam"]
    return parts
