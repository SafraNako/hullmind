"""Number formatting and the Markdown report."""

from __future__ import annotations

from typing import List, Optional, Sequence

from . import checks
from . import economics as eco
from .analysis import Analysis
from .hazmat import Finding


def usd(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def num(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float, digits: int = 1) -> str:
    return f"%{x * 100:.{digits}f}".replace(".", ",")


def hazmat_rows(findings: Sequence[Finding]) -> List[str]:
    rows = ["| kod | madde | yer | malzeme (kg) | derişim (mg/kg) | eşik | Envanter Kısım I |", "|---|---|---|---|---|---|---|"]
    for f in findings:
        rows.append(f"| {f.entry.code} | {f.entry.name_tr} | {f.item.location} | {num(f.item.material_kg, 0)} | "
                    f"{num(f.concentration_mg_per_kg, 0)} | {f.entry.threshold_text} | {'EVET' if f.listed else 'hayır'} |")
    return rows


def build_report(a: Analysis, risk_result: Optional[eco.RiskResult], bid_margin: float, title: str = "") -> str:
    ship, parts = a.ship, a.parts
    st = eco.statement(parts)
    days = parts.days
    out = [
        f"# HullMind raporu: {title or ship.name}", "",
        "> Fiyat ve maliyet değerleri girdi olarak verilmiştir; varsayılanlar ÖRNEKTİR, piyasa verisi değildir. "
        "Kütle payları, kesim karmaşıklığı ve verimlilik varsayımlardır; gemi için gerçek envanter (IHM) ve tersane "
        "verisiyle değiştirilmelidir.", "",
        "## Gemi", "",
        f"{ship.name} ({ship.ship_type}), {ship.build_year} yapımı, LDT = {num(ship.ldt, 0)} t, {len(ship.blocks)} blok.", "",
        "## Kütle dengesi", "", "| kalem | ton | LDT payı |", "|---|---|---|",
    ]
    mb = checks.mass_balance(ship, a.cut)
    for key in ("çelik hurda", "kerf kaybı", "demir dışı", "satılamayan kalan"):
        out.append(f"| {key} | {num(mb[key], 1)} | {pct(mb[key] / ship.ldt)} |")
    out.append(f"| **toplam** | **{num(mb['toplam'], 1)}** | fark {mb['fark (LDT - toplam)']:+.2e} t |")
    out += ["", "## Tehlikeli madde taraması (IMO MEPC.269(68) eşik değerleri)", ""]
    out += hazmat_rows(a.findings) if a.findings else ["Anket girilmemiş."]
    out += ["", "## Sökum planı", "",
            f"- ekip sayısı: {parts.teams}; toplam iş: {num(parts.work_hours, 0)} ekip-saat",
            f"- süre: {num(parts.makespan_h, 0)} saat = {num(days, 0)} çalışma günü ({num(parts.yard.hours_per_day, 0)} saat/gün)",
            f"- kritik yol (sonsuz ekip ile alt sınır): {num(a.cpm.duration, 0)} saat; iş yükü sınırı: "
            f"{num(parts.work_hours / parts.teams, 0)} saat; çizelge bu iki sınırın büyüğünün "
            f"{num(parts.makespan_h / max(a.cpm.duration, parts.work_hours / parts.teams), 3)} katı",
            f"- ekip kullanımı: {pct(a.schedule.utilization())}",
            f"- kritik yoldaki bloklar: {', '.join(a.critical_blocks)}", "",
            "| blok | başlangıç (gün) | bitiş (gün) |", "|---|---|---|"]
    for name, (s0, s1) in sorted(a.spans.items(), key=lambda kv: kv[1][0]):
        out.append(f"| {name} | {num(s0 / parts.yard.hours_per_day, 1)} | {num(s1 / parts.yard.hours_per_day, 1)} |")
    out += ["", "## Gelir-gider tablosu", "", "| kalem | USD |", "|---|---|"]
    for key, value in st.lines.items():
        out.append(f"| {key} | {usd(value)} |")
    out.append(f"| **net kâr** | **{usd(st.profit)}** |")
    out += ["", f"Kâr marjı (gelire göre): {pct(st.margin)}. Teklif {num(parts.bid_usd_per_ldt, 0)} USD/LDT "
            f"(satın alma {usd(parts.purchase_usd)} USD).", "",
            f"- zarar etmemek için çelik fiyatı en az {num(eco.breakeven_steel_price(parts), 0)} USD/t "
            f"(şimdiki: {num(parts.market.steel_usd_t, 0)})",
            f"- bu girdilerle en yüksek teklif: {num(eco.max_bid_usd_per_ldt(parts), 1)} USD/LDT "
            f"(kâr = 0); gelirin {pct(bid_margin, 0)}'i kâr için: {num(eco.max_bid_usd_per_ldt(parts, bid_margin), 1)} USD/LDT", "",
            "### Duyarlılık (her girdi ±%20)", "", "| girdi | -%20 | +%20 |", "|---|---|---|"]
    for name, lo, hi in eco.tornado(parts):
        out.append(f"| {name} | {usd(lo)} | {usd(hi)} |")
    if risk_result is not None:
        r = risk_result
        out += ["", "### Risk (Monte Carlo)", "",
                f"{r.n} çekiliş: ortalama {usd(r.mean)} USD, standart sapma {usd(r.std)} USD; "
                f"zarar olasılığı {pct(r.prob_loss)}; en kötü %5'in ortalaması {usd(r.cvar5)} USD. "
                f"Yüzdelikler: " + ", ".join(f"%{q}: {usd(v)}" for q, v in r.percentiles.items()) + "."]
    if a.clamped_blocks:
        out += ["", "> Uyarı: şu blokların levha kalınlığı üretici tablosunun dışında olduğu için en yakın kenar "
                "değeri kullanıldı: " + ", ".join(a.clamped_blocks) + "."]
    return "\n".join(out) + "\n"
