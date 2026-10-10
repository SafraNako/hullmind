"""Screening of hazardous materials against the IMO inventory threshold values (MEPC.269(68))."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .data import HAZMAT_BY_CODE, HazmatEntry


class HazmatError(ValueError):
    """Unknown material code or inconsistent quantities."""


@dataclass(frozen=True)
class HazmatItem:
    """One entry of a hazardous-material survey: where it is, how much material, how much substance."""

    code: str
    location: str
    material_kg: float  # mass of the material or article that contains the substance
    substance_kg: Optional[float] = None  # mass of the substance itself; None when only the concentration is known
    concentration_mg_per_kg: Optional[float] = None

    def concentration(self) -> float:
        """Concentration in mg per kg of material, from the substance mass or the stated concentration."""
        if self.material_kg <= 0:
            raise HazmatError(f"{self.code}: malzeme kütlesi pozitif olmalı")
        if self.concentration_mg_per_kg is not None:
            if self.concentration_mg_per_kg < 0:
                raise HazmatError(f"{self.code}: derişim negatif olamaz")
            return self.concentration_mg_per_kg
        if self.substance_kg is None or self.substance_kg < 0:
            raise HazmatError(f"{self.code}: madde kütlesi ya da derişim verilmeli")
        if self.substance_kg > self.material_kg:
            raise HazmatError(f"{self.code}: madde kütlesi malzeme kütlesinden büyük olamaz")
        return self.substance_kg / self.material_kg * 1e6


@dataclass(frozen=True)
class Finding:
    item: HazmatItem
    entry: HazmatEntry
    concentration_mg_per_kg: float
    listed: bool  # must be recorded in Part I of the inventory

    @property
    def removal_mass_kg(self) -> float:
        """Mass that has to be handled as hazardous waste: the whole material when it is listed."""
        return self.item.material_kg if self.listed else 0.0


def entry(code: str) -> HazmatEntry:
    try:
        return HAZMAT_BY_CODE[code]
    except KeyError:
        raise HazmatError(f"bilinmeyen tehlikeli madde kodu: {code!r} (A-1..A-4, B-1..B-9)") from None


def is_listed(code: str, concentration_mg_per_kg: float) -> bool:
    """A material is listed when the substance exceeds the threshold; with no threshold value, at any quantity."""
    e = entry(code)
    if concentration_mg_per_kg < 0:
        raise HazmatError("derişim negatif olamaz")
    if e.threshold_mg_per_kg is None:
        return concentration_mg_per_kg > 0
    return concentration_mg_per_kg > e.threshold_mg_per_kg


def screen(items: List[HazmatItem]) -> List[Finding]:
    findings = []
    for item in items:
        c = item.concentration()
        findings.append(Finding(item, entry(item.code), c, is_listed(item.code, c)))
    return findings


def removal_mass_by_code(findings: List[Finding]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for f in findings:
        if f.listed:
            out[f.entry.code] = out.get(f.entry.code, 0.0) + f.item.material_kg
    return out
