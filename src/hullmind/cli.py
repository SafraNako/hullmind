from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import checks, ship as shipmod
from . import economics as eco
from . import schedule as sch
from .analysis import Analysis, analyse, team_scan
from .cutting import CutParams, CuttingError, CuttingModel, cutting_hours_per_tonne, kerf_loss_fraction, leave_one_out_errors
from .data import CUTTING_TABLES, HAZMAT_TABLE
from .hazmat import HazmatError, screen
from .report import build_report, hazmat_rows, num, pct, usd
from .schedule import ScheduleError
from .ship import ShipError


class UsageError(ValueError):
    """Bad command-line input."""


NOTICE = "Not: fiyat ve maliyet varsayılanları ÖRNEKTİR (piyasa verisi değil); kendi değerlerinizi verin."


# ---------------------------------------------------------------------------
# option groups
# ---------------------------------------------------------------------------

def _add_ship(p: argparse.ArgumentParser) -> None:
    p.add_argument("--gemi", required=True, help="gemi tanım dosyası (JSON; ornek-gemi ile üretilir)")


def _add_cut(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("kesim")
    g.add_argument("--yakit", choices=list(CUTTING_TABLES), default="asetilen")
    g.add_argument("--parca-m", type=float, default=1.5, help="kesilen hurda parçasının kenarı (m)")
    g.add_argument("--karmasiklik", type=float, default=1.3, help="kesim uzunluğu çarpanı (rijitler, eğri levha) ≥ 1")
    g.add_argument("--kullanim", type=float, default=0.35, help="vardiyada meşalenin gerçekten kestiği pay (0-1]")
    g.add_argument("--mesale", type=int, default=3, help="ekip başına meşale")
    g.add_argument("--elleme", type=float, default=0.15, help="ton başına elleme (ekip-saat)")
    g.add_argument("--paket-t", type=float, default=150.0, help="iş paketi büyüklüğü (ton)")
    g.add_argument("--hazirlik-saat", type=float, default=72.0, help="tank temizliği ve gaz arındırma (saat)")
    g.add_argument("--tehlikeli-hizi", type=float, default=50.0, help="tehlikeli madde söküm hızı (kg/saat)")


def _add_money(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("fiyat ve maliyet (varsayılanlar ÖRNEKTİR)")
    m, y = eco.Market(), eco.Yard()
    g.add_argument("--teklif", type=float, default=250.0, help="gemi için teklif (USD/LDT)")
    g.add_argument("--celik-fiyat", type=float, default=m.steel_usd_t, help="çelik hurda (USD/t)")
    g.add_argument("--demir-disi-fiyat", type=float, default=m.nonferrous_usd_t, help="demir dışı metal (USD/t)")
    g.add_argument("--ekipman-satis", type=float, default=m.equipment_resale_usd)
    g.add_argument("--atik-maliyet", type=float, default=m.waste_disposal_usd_t, help="zararsız atık (USD/t)")
    g.add_argument("--tehlikeli-maliyet", type=float, default=m.hazmat_usd_per_kg, help="tehlikeli madde (USD/kg)")
    g.add_argument("--ekip-gun", type=float, default=y.team_usd_per_day, help="ekip-gün maliyeti (USD)")
    g.add_argument("--seferberlik", type=float, default=y.team_mobilization_usd, help="ekip başına seferberlik (USD)")
    g.add_argument("--gun-saati", type=float, default=y.hours_per_day)
    g.add_argument("--genel-gider", type=float, default=y.overhead_usd_per_day, help="günlük genel gider (USD)")
    g.add_argument("--cekme", type=float, default=y.towing_usd)
    g.add_argument("--teslim-gunu", type=float, default=y.delivery_days)
    g.add_argument("--harc", type=float, default=y.fees_fraction_of_revenue, help="gelire oranla harç, vergi, komisyon")
    g.add_argument("--faiz", type=float, default=y.financing_per_year, help="yıllık finansman oranı")


def _add_risk(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("risk")
    r = eco.Risk()
    g.add_argument("--monte-carlo", type=int, default=0, metavar="N")
    g.add_argument("--tohum", type=int)
    g.add_argument("--sigma-celik", type=float, default=r.sigma_steel)
    g.add_argument("--sigma-demir-disi", type=float, default=r.sigma_nonferrous)
    g.add_argument("--sigma-verim", type=float, default=r.sigma_productivity)
    g.add_argument("--sigma-tehlikeli", type=float, default=r.sigma_hazmat)


def _cut(args) -> CutParams:
    cut = CutParams(args.yakit, args.parca_m, args.karmasiklik, args.kullanim, args.mesale, args.elleme)
    cut.validate()
    return cut


def _market(args) -> eco.Market:
    return eco.Market(args.celik_fiyat, args.demir_disi_fiyat, args.ekipman_satis, args.atik_maliyet, args.tehlikeli_maliyet)


def _yard(args) -> eco.Yard:
    return eco.Yard(args.ekip_gun, args.seferberlik, args.gun_saati, args.genel_gider, args.cekme, args.teslim_gunu,
                    args.harc, args.faiz)


def _risk(args) -> eco.Risk:
    return eco.Risk(args.sigma_celik, args.sigma_demir_disi, args.sigma_verim, args.sigma_tehlikeli)


def _analysis(args) -> Analysis:
    ship = shipmod.load(args.gemi)
    return analyse(ship, _cut(args), args.ekip, args.teklif, _market(args), _yard(args),
                   sch.PrepParams(args.hazirlik_saat, args.tehlikeli_hizi), args.paket_t)


def _emit(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=float))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _cmd_ornek_gemi(args: argparse.Namespace) -> int:
    ship = shipmod.example_ship(args.tip, args.ldt, args.yil, args.ad)
    shipmod.save(ship, args.cikti)
    print(f"{args.cikti}: {ship.name}, {ship.ship_type}, LDT {num(ship.ldt, 0)} t, {len(ship.blocks)} blok, "
          f"{len(ship.hazmat)} tehlikeli madde kaydı (örnek, yapay veri)")
    return 0


def _cmd_kutle_dengesi(args: argparse.Namespace) -> int:
    ship = shipmod.load(args.gemi)
    mb = checks.mass_balance(ship, _cut(args))
    print(f"{ship.name}: LDT = {num(ship.ldt, 0)} t")
    for key, value in mb.items():
        if key.startswith("fark"):
            print(f"  {key}: {value:+.3e} t")
        else:
            print(f"  {key:<20}{num(value, 1):>12} t  {pct(value / ship.ldt):>8}")
    return 0


def _cmd_kesim_hizi(args: argparse.Namespace) -> int:
    cut = CutParams(args.yakit, args.parca_m, args.karmasiklik, args.kullanim, args.mesale, args.elleme)
    model = CuttingModel(args.yakit)
    if args.tablo:
        print(f"Üretici tablosu (GCE FIT+, {args.yakit}):  kalınlık (mm) → hız (mm/dk), kerf (mm)")
        for t in model.thickness:
            print(f"  {num(float(t), 0):>6}  {num(model.speed_mm_min(float(t)), 0):>7}  {num(model.kerf_mm(float(t)), 2):>5}")
        errors = leave_one_out_errors(args.yakit)
        print(f"Bir düğümü dışarıda bırakıp enterpolasyon hatası: en çok {pct(max(abs(v) for v in errors.values()))}")
        return 0
    if args.kalinlik is None:
        raise UsageError("--kalinlik ya da --tablo verilmeli")
    t = args.kalinlik
    speed = model.speed_mm_min(t)
    hours, _ = cutting_hours_per_tonne(t, cut)
    print(f"{num(t, 1)} mm {args.yakit}: kesme hızı {num(speed, 0)} mm/dk, kerf {num(model.kerf_mm(t), 2)} mm")
    print(f"  ton başına kesim {num(hours, 3)} ekip-saat; kerf kaybı {pct(kerf_loss_fraction(t, model.kerf_mm(t), cut.piece_m, cut.complexity), 2)}")
    return 0


def _cmd_tehlikeli_madde(args: argparse.Namespace) -> int:
    ship = shipmod.load(args.gemi)
    findings = screen(list(ship.hazmat))
    if args.json:
        _emit([{"kod": f.entry.code, "madde": f.entry.name_en, "yer": f.item.location, "malzeme_kg": f.item.material_kg,
                "derisim_mg_kg": f.concentration_mg_per_kg, "esik_mg_kg": f.entry.threshold_mg_per_kg,
                "kisim_I": f.listed} for f in findings])
        return 0
    if args.esikler:
        print("IMO MEPC.269(68) eşik değerleri:")
        for h in HAZMAT_TABLE:
            print(f"  {h.code}  {h.name_tr:<55}{h.threshold_text}")
        return 0
    print("\n".join(hazmat_rows(findings)) if findings else "Anket girilmemiş.")
    listed = sum(1 for f in findings if f.listed)
    print(f"\n{len(findings)} kayıt, {listed} tanesi eşiği aşıyor (Envanter Kısım I).")
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    a = _analysis(args)
    p = a.parts
    if args.json:
        _emit({"sure_saat": a.schedule.makespan, "gun": p.days, "ekip": a.schedule.teams, "is_saat": p.work_hours,
               "kritik_yol_saat": a.cpm.duration, "kullanim": a.schedule.utilization(),
               "kritik_bloklar": list(a.critical_blocks),
               "bloklar": {k: {"baslangic_saat": v[0], "bitis_saat": v[1]} for k, v in a.spans.items()}})
        return 0
    lower = max(a.cpm.duration, p.work_hours / a.schedule.teams)
    print(f"{a.ship.name}: {len(a.tasks)} iş paketi, {a.schedule.teams} ekip")
    print(f"  süre: {num(a.schedule.makespan, 0)} saat = {num(p.days, 0)} çalışma günü")
    print(f"  alt sınır: kritik yol {num(a.cpm.duration, 0)} saat, iş yükü/ekip {num(p.work_hours / a.schedule.teams, 0)} saat; "
          f"çizelge/alt sınır = {num(a.schedule.makespan / lower, 3)} (Graham garantisi ≤ {num(sch.graham_bound(a.schedule.teams), 2)}× en iyi)")
    print(f"  ekip kullanımı: {pct(a.schedule.utilization())}")
    print(f"  kritik yoldaki bloklar: {', '.join(a.critical_blocks)}")
    print("  blok                                   başlangıç  bitiş (gün)")
    for name, (s0, s1) in sorted(a.spans.items(), key=lambda kv: kv[1][0]):
        print(f"  {name:<38} {num(s0 / p.yard.hours_per_day, 1):>9} {num(s1 / p.yard.hours_per_day, 1):>9}")
    if a.clamped_blocks:
        print("  Uyarı: levha kalınlığı tablo dışında kalan bloklar (en yakın kenar kullanıldı): " + ", ".join(a.clamped_blocks))
    if args.grafik:
        from .render import plot_gantt
        plot_gantt(a.spans, a.critical_blocks, p.yard.hours_per_day, args.grafik, a.ship.name)
        print(f"Grafik: {args.grafik}")
    return 0


def _cmd_ekonomi(args: argparse.Namespace) -> int:
    a = _analysis(args)
    p = a.parts
    st = eco.statement(p)
    result = eco.monte_carlo(p, _risk(args), args.monte_carlo, args.tohum) if args.monte_carlo else None
    rows = eco.tornado(p)
    if args.json:
        _emit({"kalemler": st.lines, "net_kar": st.profit, "marj": st.margin,
               "zararsiz_celik_fiyati": eco.breakeven_steel_price(p),
               "en_yuksek_teklif_usd_ldt": eco.max_bid_usd_per_ldt(p, args.marj),
               "duyarlilik": [{"girdi": n, "dusuk": lo, "yuksek": hi} for n, lo, hi in rows],
               "risk": None if result is None else {"ortalama": result.mean, "std": result.std,
                                                    "zarar_olasiligi": result.prob_loss, "cvar5": result.cvar5,
                                                    "yuzdelikler": result.percentiles}})
        return 0
    print(NOTICE)
    print(f"{a.ship.name}: LDT {num(a.ship.ldt, 0)} t, {a.schedule.teams} ekip, {num(p.days, 0)} gün, teklif {num(p.bid_usd_per_ldt, 0)} USD/LDT")
    for key, value in st.lines.items():
        print(f"  {key:<36}{usd(value):>14}")
    print(f"  {'NET KÂR':<36}{usd(st.profit):>14}   (gelirin {pct(st.margin)}'i)")
    print(f"Zarar etmemek için çelik fiyatı ≥ {num(eco.breakeven_steel_price(p), 0)} USD/t (şimdiki {num(p.market.steel_usd_t, 0)}).")
    print(f"Kâr = 0 olan en yüksek teklif: {num(eco.max_bid_usd_per_ldt(p), 1)} USD/LDT; "
          f"gelirin {pct(args.marj, 0)}'i kâr için: {num(eco.max_bid_usd_per_ldt(p, args.marj), 1)} USD/LDT.")
    print("Duyarlılık (her girdi ±%20, kârdaki değişim USD):")
    for name, lo, hi in rows[:5]:
        print(f"  {name:<28}{usd(lo):>12}{usd(hi):>12}")
    if result is not None:
        n_text = f"{result.n:,}".replace(",", ".")
        print(f"Monte Carlo ({n_text} çekiliş): ortalama {usd(result.mean)}, std {usd(result.std)}, "
              f"zarar olasılığı {pct(result.prob_loss)}, en kötü %5'in ortalaması {usd(result.cvar5)}")
        print("  yüzdelikler: " + ", ".join(f"%{q}: {usd(v)}" for q, v in result.percentiles.items()))
    if args.grafik:
        from .render import plot_risk, plot_statement
        base = Path(args.grafik)
        plot_statement(st, str(base.with_name(base.stem + "_gelir_gider" + base.suffix)))
        print(f"Grafik: {base.with_name(base.stem + '_gelir_gider' + base.suffix)}")
        if result is not None:
            plot_risk(result, rows, str(base))
            print(f"Grafik: {base}")
    return 0


def _cmd_ekip_secimi(args: argparse.Namespace) -> int:
    ship = shipmod.load(args.gemi)
    rows = team_scan(ship, _cut(args), args.en_cok, args.teklif, _market(args), _yard(args),
                     sch.PrepParams(args.hazirlik_saat, args.tehlikeli_hizi), args.paket_t)
    hpd = args.gun_saati
    print(NOTICE)
    print(" ekip   süre (gün)  kullanım      net kâr (USD)")
    best = max(rows, key=lambda r: r[3])
    for m, makespan, util, profit in rows:
        mark = "  ← en iyi" if m == best[0] else ""
        print(f"{m:5d}  {num(makespan / hpd, 1):>10}  {pct(util):>8}  {usd(profit):>14}{mark}")
    print("İşçilik çalışılan saate, genel gider ve finansman süreye, seferberlik ekip sayısına bağlıdır; "
          "daha çok ekip süreyi kısaltır ama kullanımı düşürür.")
    return 0


def _cmd_rapor(args: argparse.Namespace) -> int:
    a = _analysis(args)
    result = eco.monte_carlo(a.parts, _risk(args), args.monte_carlo, args.tohum) if args.monte_carlo else None
    text = build_report(a, result, args.marj)
    if args.cikti:
        Path(args.cikti).write_text(text, encoding="utf-8")
        print(f"Rapor: {args.cikti}")
    else:
        print(text)
    return 0


def _cmd_dogrulama(args: argparse.Namespace) -> int:
    print("Bağımsız doğrulamalar:")
    for fuel in CUTTING_TABLES:
        e = checks.speed_interpolation_error(fuel)
        print(f"  kesme hızı enterpolasyonu ({fuel}): bir düğümü dışarıda bırakınca {int(e['n'])} düğümde en çok {pct(e['max_abs'])}, "
              f"RMS {pct(e['rms'])}, ortanca {pct(e['median_abs'])}")
    k = checks.kerf_geometry_check()
    print(f"  kerf kaybı: kesin geometri {num(k['exact'], 5)}, piksel sayımı {num(k['raster'], 5)} "
          f"(fark {pct(abs(k['raster'] / k['exact'] - 1), 2)}); büyük levhada 2·kerf/a kuralı {num(k['formula_large_plate'], 5)} ↔ "
          f"kesin {num(k['asymptotic_large_plate'], 5)} (sonlu levha (n-1)/n çarpanı)")
    s = checks.schedule_study(args.ornek, 7, 5)
    print(f"  çizelge: {s.instances} rastgele küçük çizelgede kaba kuvvet ve MILP en iyisi {s.exact_solvers_agree} kez aynı; "
          f"sezgisel {s.heuristic_optimal} kez en iyi, en kötü oran {num(s.worst_ratio, 3)}, ortalama {num(s.mean_ratio, 4)}; "
          f"Graham sınırı aşılan: {s.bound_violations}, alt sınır ihlali: {s.lower_bound_violations}")
    ship = shipmod.example_ship()
    a = analyse(ship, CutParams(), 8, 250.0)
    r = checks.risk_vs_analytic(a.parts)
    print("  risk (yalnızca çelik fiyatı belirsiz): Monte Carlo ↔ kesin lognormal")
    for key, (sim, exact) in r.items():
        shown = f"{num(sim, 4)} ↔ {num(exact, 4)}" if key == "prob_loss" else f"{usd(sim)} ↔ {usd(exact)}"
        print(f"    {key:<10}{shown}")
    mb = checks.mass_balance(ship, CutParams())
    print(f"  kütle dengesi: LDT − toplam = {mb['fark (LDT - toplam)']:+.2e} t")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hullmind", description="Tekli gemi sökümü: kütle dengesi, kesim, plan, ekonomi, risk.")
    sub = parser.add_subparsers(dest="komut", required=True)

    p = sub.add_parser("ornek-gemi", help="yapay örnek gemi dosyası üret")
    p.add_argument("--tip", choices=shipmod.ship_types(), default="dokme-yuk")
    p.add_argument("--ldt", type=float, default=11500.0)
    p.add_argument("--yil", type=int, default=1998)
    p.add_argument("--ad", default="ÖRNEK GEMİ")
    p.add_argument("--cikti", required=True)
    p.set_defaults(func=_cmd_ornek_gemi)

    p = sub.add_parser("kutle-dengesi", help="çelik, demir dışı, kerf kaybı ve kalan")
    _add_ship(p)
    _add_cut(p)
    p.set_defaults(func=_cmd_kutle_dengesi)

    p = sub.add_parser("kesim-hizi", help="üretici tablosundan kesme hızı ve ton başına süre")
    p.add_argument("--kalinlik", type=float)
    p.add_argument("--tablo", action="store_true")
    _add_cut(p)
    p.set_defaults(func=_cmd_kesim_hizi)

    p = sub.add_parser("tehlikeli-madde", help="IMO eşik değerlerine göre tarama")
    _add_ship(p)
    p.add_argument("--esikler", action="store_true", help="yalnızca eşik tablosunu yazdır")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_tehlikeli_madde)

    p = sub.add_parser("plan", help="blok bağımlılıkları ve ekip sayısıyla çizelge")
    _add_ship(p)
    p.add_argument("--ekip", type=int, default=8)
    _add_cut(p)
    _add_money(p)
    p.add_argument("--grafik")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_plan)

    p = sub.add_parser("ekonomi", help="gelir-gider, en yüksek teklif, duyarlılık, Monte Carlo")
    _add_ship(p)
    p.add_argument("--ekip", type=int, default=8)
    _add_cut(p)
    _add_money(p)
    _add_risk(p)
    p.add_argument("--marj", type=float, default=0.05, help="hedef kâr marjı (gelirin oranı)")
    p.add_argument("--grafik")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_ekonomi)

    p = sub.add_parser("ekip-secimi", help="ekip sayısını tara, en kârlıyı bul")
    _add_ship(p)
    p.add_argument("--en-cok", type=int, default=20)
    _add_cut(p)
    _add_money(p)
    p.set_defaults(func=_cmd_ekip_secimi)

    p = sub.add_parser("rapor", help="Markdown raporu")
    _add_ship(p)
    p.add_argument("--ekip", type=int, default=8)
    _add_cut(p)
    _add_money(p)
    _add_risk(p)
    p.add_argument("--marj", type=float, default=0.05)
    p.add_argument("--cikti")
    p.set_defaults(func=_cmd_rapor)

    p = sub.add_parser("dogrulama", help="modelleri bağımsız yöntemlerle yeniden sına")
    p.add_argument("--ornek", type=int, default=40, help="rastgele küçük çizelge sayısı")
    p.set_defaults(func=_cmd_dogrulama)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (UsageError, ShipError, ScheduleError, HazmatError, CuttingError, eco.EconomicsError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
