"""Torch-cutting productivity from a manufacturer's cutting-parameter table.

Cutting speed and kerf come from the GCE FIT+ tables (see :mod:`hullmind.data`); between
tabulated thicknesses speed is interpolated linearly in log-log coordinates (speed falls
roughly as a power of thickness). The model never extrapolates beyond the table.

The rest is geometry. A plate of thickness ``t`` cut into square pieces of side ``a`` has a
cut length of ``2/a`` per unit area (each piece owns two of its four edges), so per tonne
of plate

    L = 2 / (rho t a)      [m of cut per kg],

and the kerf, the strip of steel burned away along every cut, removes the fraction
``kerf * 2 / a`` of the plate's mass. Real ship structure has stiffeners and curved plating,
so a ``complexity`` factor >= 1 scales the cut length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from .data import CUTTING_TABLES, STEEL_DENSITY_KG_M3


class CuttingError(ValueError):
    """Thickness outside the table or an invalid parameter."""


class CuttingModel:
    """Cutting speed [mm/min] and kerf [mm] as functions of plate thickness [mm]."""

    def __init__(self, fuel: str = "asetilen"):
        if fuel not in CUTTING_TABLES:
            raise CuttingError(f"bilinmeyen yakıt: {fuel!r} (asetilen ya da propan)")
        self.fuel = fuel
        table = CUTTING_TABLES[fuel]
        self.thickness = np.array(sorted(table), dtype=float)
        self.speeds = np.array([table[int(t)][0] for t in self.thickness], dtype=float)
        self.kerfs = np.array([0.5 * (table[int(t)][1] + table[int(t)][2]) for t in self.thickness], dtype=float)

    @property
    def t_min(self) -> float:
        return float(self.thickness[0])

    @property
    def t_max(self) -> float:
        return float(self.thickness[-1])

    def clamp(self, t_mm: float) -> Tuple[float, bool]:
        """The thickness limited to the table range, and whether it had to be."""
        used = min(max(t_mm, self.t_min), self.t_max)
        return used, used != t_mm

    def _check(self, t_mm: float) -> None:
        if not (self.t_min <= t_mm <= self.t_max):
            raise CuttingError(f"{t_mm} mm tablo aralığının ({self.t_min:g}-{self.t_max:g} mm) dışında")

    def speed_mm_min(self, t_mm: float) -> float:
        self._check(t_mm)
        return float(np.exp(np.interp(math.log(t_mm), np.log(self.thickness), np.log(self.speeds))))

    def kerf_mm(self, t_mm: float) -> float:
        self._check(t_mm)
        return float(np.interp(t_mm, self.thickness, self.kerfs))


def leave_one_out_errors(fuel: str = "asetilen") -> Dict[float, float]:
    """Relative error of the interpolated speed at each interior table node when that node is left out."""
    model = CuttingModel(fuel)
    out = {}
    for i in range(1, len(model.thickness) - 1):
        t = model.thickness[i]
        keep = [j for j in range(len(model.thickness)) if j != i]
        predicted = float(np.exp(np.interp(math.log(t), np.log(model.thickness[keep]), np.log(model.speeds[keep]))))
        out[float(t)] = predicted / float(model.speeds[i]) - 1.0
    return out


def _check_geometry(piece_m: float, complexity: float) -> None:
    if piece_m <= 0:
        raise CuttingError("parça boyu pozitif olmalı")
    if complexity < 1.0:
        raise CuttingError("karmaşıklık çarpanı en az 1 olmalı")


def cut_length_m_per_tonne(t_mm: float, piece_m: float = 1.5, complexity: float = 1.0) -> float:
    """Metres of cut per tonne of plate cut into ``piece_m`` squares: ``1000 * 2 / (rho t a)`` times ``complexity``."""
    _check_geometry(piece_m, complexity)
    if t_mm <= 0:
        raise CuttingError("levha kalınlığı pozitif olmalı")
    return complexity * 1000.0 * 2.0 / (STEEL_DENSITY_KG_M3 * (t_mm / 1000.0) * piece_m)


def kerf_loss_fraction(t_mm: float, kerf_mm: float, piece_m: float = 1.5, complexity: float = 1.0) -> float:
    """Fraction of the plate's mass burned away in the kerf: ``kerf * 2 / a`` times ``complexity``."""
    _check_geometry(piece_m, complexity)
    if kerf_mm < 0:
        raise CuttingError("kerf negatif olamaz")
    return complexity * (kerf_mm / 1000.0) * 2.0 / piece_m


def exact_kerf_loss_fraction(width_m: float, height_m: float, nx: int, ny: int, kerf_mm: float) -> float:
    """Exact kerf loss of a ``width x height`` plate cut into ``nx x ny`` equal pieces.

    The internal cuts are ``(nx-1)`` vertical lines of length ``height`` and ``(ny-1)``
    horizontal lines of length ``width``; the burned strip has area ``kerf * length``.
    """
    if min(width_m, height_m) <= 0 or nx < 1 or ny < 1:
        raise CuttingError("geçersiz levha ya da parça sayısı")
    length = (nx - 1) * height_m + (ny - 1) * width_m
    return (kerf_mm / 1000.0) * length / (width_m * height_m)


@dataclass(frozen=True)
class CutParams:
    """Everything that turns a tonne of plate into team-hours."""

    fuel: str = "asetilen"
    piece_m: float = 1.5
    complexity: float = 1.3
    utilization: float = 0.35  # share of the shift a torch is actually cutting
    torches_per_team: int = 3
    handling_h_per_t: float = 0.15  # lifting, sorting and moving material per tonne handled (team-hours)

    def validate(self) -> None:
        _check_geometry(self.piece_m, self.complexity)
        if not 0.0 < self.utilization <= 1.0:
            raise CuttingError("kesim kullanım oranı (0, 1] aralığında olmalı")
        if self.torches_per_team < 1 or self.handling_h_per_t < 0:
            raise CuttingError("geçersiz ekip parametreleri")


def cutting_hours_per_tonne(t_mm: float, params: CutParams) -> Tuple[float, bool]:
    """Team-hours of torch work per tonne of plate of thickness ``t_mm`` (and whether ``t_mm`` was clamped)."""
    params.validate()
    model = CuttingModel(params.fuel)
    t_used, clamped = model.clamp(t_mm)
    speed_m_h = model.speed_mm_min(t_used) * 60.0 / 1000.0
    hours = cut_length_m_per_tonne(t_used, params.piece_m, params.complexity) / (
        speed_m_h * params.utilization * params.torches_per_team)
    return hours, clamped
