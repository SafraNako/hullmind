import json

import pytest

from hullmind import cli, ship as s


def run(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def gemi(tmp_path, capsys):
    path = tmp_path / "gemi.json"
    assert run(capsys, "ornek-gemi", "--tip", "dokme-yuk", "--ldt", 11500, "--yil", 1998, "--cikti", path)[0] == 0
    return path


@pytest.mark.parametrize("tip", s.ship_types())
def test_ornek_gemi_for_every_type(tip, tmp_path, capsys):
    path = tmp_path / f"{tip}.json"
    code, out, _ = run(capsys, "ornek-gemi", "--tip", tip, "--ldt", 9000, "--cikti", path)
    assert code == 0 and "9.000 t" in out
    assert s.load(path).ldt == 9000.0


def test_kutle_dengesi_closes(gemi, capsys):
    code, out, _ = run(capsys, "kutle-dengesi", "--gemi", gemi)
    assert code == 0 and "çelik hurda" in out and "fark (LDT - toplam): +0.000e+00 t" in out
    code, out2, _ = run(capsys, "kutle-dengesi", "--gemi", gemi, "--yakit", "propan")
    assert out2 != out


def test_kesim_hizi_table_and_single_thickness(capsys):
    code, out, _ = run(capsys, "kesim-hizi", "--tablo")
    assert code == 0 and "710" in out and "enterpolasyon hatası" in out
    code, out, _ = run(capsys, "kesim-hizi", "--kalinlik", 10)
    assert "710 mm/dk" in out and "kerf 1,90 mm" in out
    code, _, err = run(capsys, "kesim-hizi", "--kalinlik", 500)
    assert code == 2 and "dışında" in err
    assert run(capsys, "kesim-hizi")[0] == 2


def test_tehlikeli_madde_screening_and_threshold_table(gemi, capsys):
    code, out, _ = run(capsys, "tehlikeli-madde", "--gemi", gemi)
    assert code == 0 and "5 tanesi eşiği aşıyor" in out and "| B-4 |" in out
    code, out, _ = run(capsys, "tehlikeli-madde", "--gemi", gemi, "--json")
    rows = {r["kod"]: r for r in json.loads(out)}
    assert rows["A-1"]["kisim_I"] is True and rows["B-4"]["kisim_I"] is False and rows["A-1"]["esik_mg_kg"] == 1000.0
    code, out, _ = run(capsys, "tehlikeli-madde", "--gemi", gemi, "--esikler")
    assert "MEPC.269(68)" in out and "%0,1" in out and "eşik yok" in out


def test_plan_text_json_and_gantt(gemi, tmp_path, capsys):
    png = tmp_path / "gantt.png"
    code, out, _ = run(capsys, "plan", "--gemi", gemi, "--ekip", 10, "--grafik", png)
    assert code == 0 and "10 ekip" in out and "Graham" in out and "Omurga ve çift dip" in out
    assert png.stat().st_size > 8000
    code, out, _ = run(capsys, "plan", "--gemi", gemi, "--ekip", 10, "--json")
    data = json.loads(out)
    assert data["ekip"] == 10 and data["kullanim"] <= 1.0
    assert data["sure_saat"] >= max(data["kritik_yol_saat"], data["is_saat"] / 10) - 1e-6
    assert data["bloklar"]["Omurga ve çift dip"]["bitis_saat"] == pytest.approx(data["sure_saat"])
    # more teams, shorter job
    code, out1, _ = run(capsys, "plan", "--gemi", gemi, "--ekip", 3, "--json")
    assert json.loads(out1)["sure_saat"] > data["sure_saat"]


def test_ekonomi_json_agrees_with_the_closed_forms(gemi, capsys):
    code, out, _ = run(capsys, "ekonomi", "--gemi", gemi, "--ekip", 10, "--teklif", 240, "--json")
    assert code == 0
    d = json.loads(out)
    assert sum(d["kalemler"].values()) == pytest.approx(d["net_kar"], rel=1e-9)
    assert d["risk"] is None
    # the maximum bid is the bid at which the profit margin equals the target, so raising the bid by it lowers profit
    code, out2, _ = run(capsys, "ekonomi", "--gemi", gemi, "--ekip", 10, "--teklif", d["en_yuksek_teklif_usd_ldt"],
                        "--marj", 0.05, "--json")
    d2 = json.loads(out2)
    revenue = sum(v for v in d2["kalemler"].values() if v > 0)
    assert d2["net_kar"] == pytest.approx(0.05 * revenue, rel=1e-6)
    assert d2["zararsiz_celik_fiyati"] < 350.0


def test_ekonomi_text_with_monte_carlo_and_plots(gemi, tmp_path, capsys):
    png = tmp_path / "risk.png"
    code, out, _ = run(capsys, "ekonomi", "--gemi", gemi, "--ekip", 10, "--teklif", 240, "--monte-carlo", 20000,
                       "--tohum", 1, "--grafik", png)
    assert code == 0 and "ÖRNEKTİR" in out and "NET KÂR" in out and "Monte Carlo (20.000 çekiliş)" in out
    assert "zarar olasılığı" in out and png.stat().st_size > 8000
    assert (tmp_path / "risk_gelir_gider.png").stat().st_size > 8000


def test_prices_change_the_answer_in_the_expected_direction(gemi, capsys):
    base = json.loads(run(capsys, "ekonomi", "--gemi", gemi, "--teklif", 240, "--json")[1])["net_kar"]
    high = json.loads(run(capsys, "ekonomi", "--gemi", gemi, "--teklif", 240, "--celik-fiyat", 450, "--json")[1])["net_kar"]
    dear = json.loads(run(capsys, "ekonomi", "--gemi", gemi, "--teklif", 300, "--json")[1])["net_kar"]
    assert high > base > dear


def test_ekip_secimi_marks_the_best_row(gemi, capsys):
    code, out, _ = run(capsys, "ekip-secimi", "--gemi", gemi, "--en-cok", 12, "--teklif", 240)
    assert code == 0 and out.count("← en iyi") == 1 and "%100,0" in out


def test_rapor_file_and_stdout(gemi, tmp_path, capsys):
    path = tmp_path / "rapor.md"
    code, out, _ = run(capsys, "rapor", "--gemi", gemi, "--ekip", 10, "--teklif", 240, "--monte-carlo", 10000, "--tohum", 2,
                       "--cikti", path)
    assert code == 0
    md = path.read_text(encoding="utf-8")
    for needle in ("# HullMind raporu", "## Kütle dengesi", "MEPC.269(68)", "## Sökum planı", "## Gelir-gider tablosu",
                   "### Duyarlılık", "### Risk (Monte Carlo)", "ÖRNEKTİR", "| A-1 |"):
        assert needle in md, needle
    code, out, _ = run(capsys, "rapor", "--gemi", gemi, "--ekip", 6)
    assert out.startswith("# HullMind raporu") and "Risk (Monte Carlo)" not in out


def test_dogrulama_command(capsys):
    code, out, _ = run(capsys, "dogrulama", "--ornek", 8)
    assert code == 0
    for needle in ("kesme hızı enterpolasyonu (asetilen)", "kerf kaybı", "çizelge: 8 rastgele", "Graham sınırı aşılan: 0",
                   "Monte Carlo ↔ kesin lognormal", "kütle dengesi"):
        assert needle in out, needle


def test_errors_exit_with_code_2(gemi, tmp_path, capsys):
    bad = tmp_path / "bozuk.json"
    bad.write_text("{}", encoding="utf-8")
    for argv in (("plan", "--gemi", bad), ("plan", "--gemi", tmp_path / "yok.json"), ("plan", "--gemi", gemi, "--ekip", 0),
                 ("ekonomi", "--gemi", gemi, "--celik-fiyat", -5), ("ekonomi", "--gemi", gemi, "--monte-carlo", 10),
                 ("kutle-dengesi", "--gemi", gemi, "--kullanim", 0)):
        code, _, err = run(capsys, *argv)
        assert code == 2 and "Hata" in err, argv
    with pytest.raises(SystemExit):
        cli.main([])
