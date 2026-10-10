"""The ship description: blocks that partition the lightship weight, their dependencies, and a hazmat survey."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .hazmat import HazmatItem

PREP = "ön-temizlik"  # the reserved first task: tank cleaning, gas-freeing and hazardous-material removal


class ShipError(ValueError):
    """The ship description is inconsistent."""


@dataclass(frozen=True)
class Block:
    """A part of the ship that is cut and handled as one job."""

    name: str
    mass_t: float
    plate_mm: float  # representative plate thickness for the cutting model
    steel_share: float = 0.96  # share of the block's mass that is recoverable steel
    nonferrous_share: float = 0.005  # copper, aluminium, brass, stainless (sold separately)
    after: Tuple[str, ...] = ()  # blocks (or PREP) that must be finished first
    kind: str = "gövde"


@dataclass(frozen=True)
class Ship:
    name: str
    ship_type: str
    ldt: float  # light displacement tonnage [t]
    build_year: int
    blocks: Tuple[Block, ...]
    hazmat: Tuple[HazmatItem, ...] = ()

    def block(self, name: str) -> Block:
        for b in self.blocks:
            if b.name == name:
                return b
        raise ShipError(f"blok bulunamadı: {name!r}")

    def validate(self) -> None:
        if self.ldt <= 0:
            raise ShipError("LDT pozitif olmalı")
        if not self.blocks:
            raise ShipError("en az bir blok gerekli")
        names = [b.name for b in self.blocks]
        if len(set(names)) != len(names) or PREP in names:
            raise ShipError("blok adları benzersiz olmalı ve rezerve adı kullanmamalı")
        for b in self.blocks:
            if b.mass_t <= 0 or b.plate_mm <= 0:
                raise ShipError(f"{b.name}: kütle ve levha kalınlığı pozitif olmalı")
            if not (0.0 <= b.steel_share and 0.0 <= b.nonferrous_share and b.steel_share + b.nonferrous_share <= 1.0):
                raise ShipError(f"{b.name}: çelik ve demir dışı payları toplamı 0-1 aralığında olmalı")
            for dep in b.after:
                if dep != PREP and dep not in names:
                    raise ShipError(f"{b.name}: bilinmeyen bağımlılık {dep!r}")
        total = sum(b.mass_t for b in self.blocks)
        if abs(total - self.ldt) > 1e-6 * self.ldt:
            raise ShipError(f"blok kütleleri toplamı ({total:.3f} t) LDT'ye ({self.ldt:.3f} t) eşit olmalı")
        _topological_order(self)  # raises on a cycle

    # --- mass balance ----------------------------------------------------------------
    def steel_t(self) -> float:
        return sum(b.mass_t * b.steel_share for b in self.blocks)

    def nonferrous_t(self) -> float:
        return sum(b.mass_t * b.nonferrous_share for b in self.blocks)

    def other_t(self) -> float:
        """Insulation, paint, wood, plastics and outfitting that cannot be sold as scrap."""
        return sum(b.mass_t * (1.0 - b.steel_share - b.nonferrous_share) for b in self.blocks)


def _topological_order(ship: Ship) -> List[str]:
    remaining = {b.name: set(b.after) - {PREP} for b in ship.blocks}
    order: List[str] = []
    while remaining:
        ready = sorted(n for n, deps in remaining.items() if not deps)
        if not ready:
            raise ShipError("bağımlılıklarda döngü var: " + ", ".join(sorted(remaining)))
        for n in ready:
            order.append(n)
            del remaining[n]
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def topological_order(ship: Ship) -> List[str]:
    return _topological_order(ship)


# ---------------------------------------------------------------------------
# example ships
# ---------------------------------------------------------------------------

# type -> (cargo sections, superstructure %, machinery %, deck equipment %, hull plate mm, machinery plate mm)
# ASSUMED shares of the lightweight; real ships differ and the user is expected to supply the survey.
_TYPES: Dict[str, Tuple[int, float, float, float, float, float]] = {
    "dokme-yuk": (5, 4.0, 9.0, 5.0, 14.0, 30.0),
    "tanker": (6, 3.5, 8.0, 4.0, 16.0, 30.0),
    "konteyner": (5, 4.5, 14.0, 5.0, 18.0, 35.0),
    "genel-yuk": (4, 5.0, 12.0, 6.0, 12.0, 30.0),
}


def ship_types() -> List[str]:
    return list(_TYPES)


def example_ship(ship_type: str = "dokme-yuk", ldt: float = 11500.0, build_year: int = 1998, name: str = "ÖRNEK GEMİ") -> Ship:
    """A synthetic ship of the given type whose blocks sum exactly to ``ldt``."""
    if ship_type not in _TYPES:
        raise ShipError(f"bilinmeyen gemi tipi: {ship_type!r} ({', '.join(_TYPES)})")
    sections, sup, mach, deck, plate, mplate = _TYPES[ship_type]
    upper_names, lower_names = [], []
    rest = 100.0 - sup - mach - deck
    # hull: stern 8 %, bow 7 %, keel 6 %, the remainder split evenly over upper and lower cargo sections
    fixed = 8.0 + 7.0 + 6.0
    per_section = (rest - fixed) / (2 * sections)
    spec: List[Tuple[str, float, float, float, float, Tuple[str, ...], str]] = [
        ("Konaklama üstyapısı", sup, 6.0, 0.80, 0.06, (PREP,), "üstyapı"),
        ("Makine dairesi ekipmanı", mach, mplate, 0.80, 0.06, (PREP,), "makine"),
        ("Güverte ekipmanı", deck, 10.0, 0.85, 0.03, (PREP,), "ekipman"),
        ("Kıç bölüm", 8.0, plate, 0.96, 0.005, ("Konaklama üstyapısı", "Makine dairesi ekipmanı"), "gövde"),
    ]
    for i in range(1, sections + 1):
        up, lo = f"Kargo bölümü {i} (üst)", f"Kargo bölümü {i} (alt)"
        upper_names.append(up)
        lower_names.append(lo)
        spec.append((up, per_section, plate, 0.96, 0.005, ("Güverte ekipmanı", "Konaklama üstyapısı"), "gövde"))
        spec.append((lo, per_section, plate * 1.15, 0.96, 0.005, (up,), "gövde"))
    spec.append(("Baş bölüm", 7.0, plate, 0.96, 0.005, tuple(upper_names), "gövde"))
    spec.append(("Omurga ve çift dip", 6.0, plate * 1.4, 0.96, 0.005, tuple(lower_names) + ("Kıç bölüm", "Baş bölüm"), "gövde"))
    total_weight = sum(s[1] for s in spec)
    blocks = []
    for bname, weight, t, steel, nf, after, kind in spec:
        blocks.append(Block(bname, ldt * weight / total_weight, round(t, 1), steel, nf, after, kind))
    # make the sum exact despite rounding
    drift = ldt - sum(b.mass_t for b in blocks)
    blocks[-1] = Block(blocks[-1].name, blocks[-1].mass_t + drift, blocks[-1].plate_mm, blocks[-1].steel_share,
                       blocks[-1].nonferrous_share, blocks[-1].after, blocks[-1].kind)
    hazmat = ()
    if build_year < 2002:  # asbestos was banned on new ships by SOLAS from 2002
        hazmat = (
            HazmatItem("A-1", "Konaklama bölmeleri yalıtımı", 4000.0, concentration_mg_per_kg=100000.0),
            HazmatItem("A-2", "Eski kablo izolasyonu", 1500.0, concentration_mg_per_kg=80.0),
            HazmatItem("A-3", "Soğutma sistemi (R-12)", 120.0, substance_kg=120.0),
            HazmatItem("A-4", "Su altı boyası (TBT)", 6000.0, concentration_mg_per_kg=4000.0),
            HazmatItem("B-3", "Akü ve kurşun ağırlıklar", 8000.0, substance_kg=7200.0),
            HazmatItem("B-4", "Cıvalı sensörler ve lambalar", 40.0, concentration_mg_per_kg=200.0),
        )
    ship = Ship(name, ship_type, ldt, build_year, tuple(blocks), hazmat)
    ship.validate()
    return ship


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def to_dict(ship: Ship) -> dict:
    return {
        "ad": ship.name, "tip": ship.ship_type, "ldt": ship.ldt, "insa_yili": ship.build_year,
        "bloklar": [{"ad": b.name, "kutle_t": b.mass_t, "levha_mm": b.plate_mm, "celik_payi": b.steel_share,
                     "demir_disi_payi": b.nonferrous_share, "sonra": list(b.after), "tur": b.kind} for b in ship.blocks],
        "tehlikeli_madde": [{"kod": h.code, "yer": h.location, "malzeme_kg": h.material_kg,
                             "madde_kg": h.substance_kg, "derisim_mg_kg": h.concentration_mg_per_kg}
                            for h in ship.hazmat],
    }


def from_dict(data: dict) -> Ship:
    try:
        blocks = tuple(
            Block(b["ad"], float(b["kutle_t"]), float(b["levha_mm"]), float(b.get("celik_payi", 0.96)),
                  float(b.get("demir_disi_payi", 0.005)), tuple(b.get("sonra", ())), b.get("tur", "gövde"))
            for b in data["bloklar"])
        hazmat = tuple(
            HazmatItem(h["kod"], h.get("yer", ""), float(h["malzeme_kg"]),
                       None if h.get("madde_kg") is None else float(h["madde_kg"]),
                       None if h.get("derisim_mg_kg") is None else float(h["derisim_mg_kg"]))
            for h in data.get("tehlikeli_madde", []))
        ship = Ship(data["ad"], data["tip"], float(data["ldt"]), int(data["insa_yili"]), blocks, hazmat)
    except (KeyError, TypeError, ValueError) as exc:
        raise ShipError(f"gemi dosyası çözümlenemedi: {exc!r}") from exc
    ship.validate()
    return ship


def save(ship: Ship, path) -> None:
    Path(path).write_text(json.dumps(to_dict(ship), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path) -> Ship:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShipError(f"gemi dosyası okunamadı: {path}") from exc
    return from_dict(data)
