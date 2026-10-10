"""Reference data transcribed from published sources.

Torch cutting
    GCE Group, *Cutting Parameters for Oxy-Fuel Cutting Torches* (FIT+ range, 2025
    edition): acetylene ``ASF`` high-speed nozzles (3-300 mm) and propane ``PRC``
    rapid-cutting nozzles (5-70 mm). Speeds in mm/min; the kerf width is the
    manufacturer's value for each nozzle (two nozzle sizes overlap at some thicknesses,
    giving a range).

Hazardous materials
    IMO resolution MEPC.269(68), *2015 Guidelines for the development of the Inventory
    of Hazardous Materials*, Appendix 1 (Table A: materials listed in appendix 1 of the
    Hong Kong Convention; Table B: appendix 2) with their threshold values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# thickness [mm] -> (cutting speed [mm/min], kerf width low [mm], kerf width high [mm])
ACETYLENE_ASF: Dict[int, Tuple[float, float, float]] = {
    3: (840, 0.8, 0.8), 4: (800, 0.8, 0.8), 5: (750, 0.9, 0.9), 6: (750, 1.5, 1.5), 8: (730, 1.5, 1.5),
    10: (710, 1.7, 2.1), 15: (630, 2.1, 2.1), 20: (560, 2.1, 2.1), 25: (510, 2.1, 2.5), 30: (480, 2.6, 2.6),
    35: (450, 2.7, 2.7), 40: (430, 2.7, 2.8), 50: (395, 2.9, 2.9), 60: (365, 3.0, 3.0), 70: (345, 3.0, 3.0),
    80: (310, 3.0, 3.0), 90: (290, 3.0, 3.0), 100: (270, 3.0, 3.6), 120: (235, 3.6, 3.6), 130: (220, 3.6, 3.6),
    150: (205, 3.6, 5.0), 200: (170, 5.0, 5.0), 230: (140, 5.0, 6.0), 250: (125, 6.0, 6.0), 300: (110, 6.0, 6.0),
}

PROPANE_PRC: Dict[int, Tuple[float, float, float]] = {
    5: (840, 2.8, 3.0), 10: (740, 2.8, 3.0), 15: (640, 2.9, 3.2), 20: (590, 2.9, 3.2), 25: (520, 2.9, 3.2),
    30: (500, 2.9, 3.2), 40: (450, 2.9, 3.2), 50: (410, 3.3, 3.3), 70: (340, 3.5, 3.5),
}

CUTTING_TABLES = {"asetilen": ACETYLENE_ASF, "propan": PROPANE_PRC}

STEEL_DENSITY_KG_M3 = 7850.0


@dataclass(frozen=True)
class HazmatEntry:
    code: str
    name_tr: str
    name_en: str
    threshold_mg_per_kg: Optional[float]  # None: no threshold value, any quantity is listed
    threshold_text: str
    table: str  # "A" (Convention appendix 1) or "B" (appendix 2)


HAZMAT_TABLE = (
    HazmatEntry("A-1", "Asbest", "Asbestos", 1000.0, "%0,1", "A"),
    HazmatEntry("A-2", "Poliklorlu bifeniller (PCB)", "Polychlorinated biphenyls (PCBs)", 50.0, "50 mg/kg", "A"),
    HazmatEntry("A-3", "Ozon tabakasını incelten maddeler (CFC, halon, HCFC ...)", "Ozone depleting substances",
                None, "eşik yok", "A"),
    HazmatEntry("A-4", "Organokalay içeren zehirli boya (TBT)", "Anti-fouling systems containing organotin",
                2500.0, "2500 mg toplam kalay/kg", "A"),
    HazmatEntry("B-1", "Kadmiyum ve bileşikleri", "Cadmium and cadmium compounds", 100.0, "100 mg/kg", "B"),
    HazmatEntry("B-2", "Altı değerlikli krom ve bileşikleri", "Hexavalent chromium and compounds", 1000.0,
                "1000 mg/kg", "B"),
    HazmatEntry("B-3", "Kurşun ve bileşikleri", "Lead and lead compounds", 1000.0, "1000 mg/kg", "B"),
    HazmatEntry("B-4", "Cıva ve bileşikleri", "Mercury and mercury compounds", 1000.0, "1000 mg/kg", "B"),
    HazmatEntry("B-5", "Polibromlu bifeniller (PBB)", "Polybrominated biphenyls (PBBs)", 50.0, "50 mg/kg", "B"),
    HazmatEntry("B-6", "Polibromlu difenil eterler (PBDE)", "Polybrominated diphenyl ethers (PBDEs)", 1000.0,
                "1000 mg/kg", "B"),
    HazmatEntry("B-7", "Poliklorlu naftalenler (3'ten fazla klor atomu)", "Polychlorinated naphthalenes", 50.0,
                "50 mg/kg", "B"),
    HazmatEntry("B-8", "Radyoaktif maddeler", "Radioactive substances", None, "eşik yok", "B"),
    HazmatEntry("B-9", "Kısa zincirli klorlu parafinler (C10-C13)", "Certain shortchain chlorinated paraffins",
                10000.0, "%1", "B"),
)

HAZMAT_BY_CODE = {h.code: h for h in HAZMAT_TABLE}
