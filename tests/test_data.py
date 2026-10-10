import pytest

from hullmind import data


def test_manufacturer_table_spot_values_from_the_published_chart():
    t = data.ACETYLENE_ASF
    assert len(t) == 25 and min(t) == 3 and max(t) == 300
    for thickness, speed in ((3, 840), (10, 710), (25, 510), (50, 395), (100, 270), (150, 205), (300, 110)):
        assert t[thickness][0] == speed
    assert t[10][1:] == (1.7, 2.1) and t[300][1:] == (6.0, 6.0) and t[3][1:] == (0.8, 0.8)  # kerf, two nozzle sizes
    p = data.PROPANE_PRC
    assert len(p) == 9 and (p[5][0], p[10][0], p[70][0]) == (840, 740, 340)


@pytest.mark.parametrize("table", [data.ACETYLENE_ASF, data.PROPANE_PRC])
def test_speed_falls_and_kerf_grows_with_thickness(table):
    thick = sorted(table)
    speeds = [table[t][0] for t in thick]
    kerfs_low = [table[t][1] for t in thick]
    assert speeds == sorted(speeds, reverse=True)
    assert all(table[t][1] <= table[t][2] for t in thick)
    assert kerfs_low[-1] >= kerfs_low[0]


def test_imo_thresholds_as_printed_in_mepc_269_68():
    expected = {
        "A-1": 1000.0,  # asbestos 0.1 %
        "A-2": 50.0, "A-3": None, "A-4": 2500.0,
        "B-1": 100.0, "B-2": 1000.0, "B-3": 1000.0, "B-4": 1000.0, "B-5": 50.0, "B-6": 1000.0,
        "B-7": 50.0, "B-8": None, "B-9": 10000.0,  # short-chain chlorinated paraffins 1 %
    }
    assert {h.code: h.threshold_mg_per_kg for h in data.HAZMAT_TABLE} == expected
    assert len(data.HAZMAT_TABLE) == 13 and set(data.HAZMAT_BY_CODE) == set(expected)
    assert {h.table for h in data.HAZMAT_TABLE if h.code.startswith("A")} == {"A"}
    assert {h.table for h in data.HAZMAT_TABLE if h.code.startswith("B")} == {"B"}
    assert data.HAZMAT_BY_CODE["A-1"].threshold_text == "%0,1" and data.HAZMAT_BY_CODE["B-9"].threshold_text == "%1"
