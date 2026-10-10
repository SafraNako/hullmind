# hullmind

A calculator and planner for dismantling **one ship**: how its lightweight splits into
scrap steel, non-ferrous metal and waste, how long torch cutting takes with a given number
of teams under the dependencies between hull blocks, what the job earns, the highest bid a
yard can afford, how risky that is, and which listed hazardous materials the survey triggers.
This is the MVP of roadmap item #92 ("start with a single-ship dismantling calculation and
analysis tool"). CLI messages are in Turkish (`hullmind` subcommands are ASCII-transliterated
Turkish, like the other tools in this series); code and this document are in English.

It is not a safety plan, an Inventory of Hazardous Materials, or financial advice: see
*Scope and limitations*.

## What is real data and what is assumed

| | source | status |
|---|---|---|
| torch cutting speed and kerf versus plate thickness | GCE Group, *Cutting Parameters for Oxy-Fuel Cutting Torches* (FIT+ range, 2025): acetylene `ASF` nozzles 3-300 mm, propane `PRC` nozzles 5-70 mm | transcribed from the manufacturer's chart |
| hazardous-material threshold values | IMO resolution MEPC.269(68), Appendix 1, Tables A and B (13 materials) | transcribed, thresholds read from the resolution's text |
| composition of a ship (steel, non-ferrous, waste, block shares, plate thickness) | typical shares of the lightweight | **assumed**; the example ships are synthetic. Replace with the ship's survey |
| cutting complexity (stiffeners), torch utilization, handling time | 1.3, 0.35, 0.15 team-h/t | **assumed** |
| prices and yard costs | placeholders | **ILLUSTRATIVE**, not market data; every command that prints money says so |

What the program guarantees is the arithmetic, the use of the published tables, and that
every model was checked against an independent method (next section).

## Models

1. **Mass balance** ([`ship.py`](src/hullmind/ship.py)). The blocks partition the LDT
   exactly; each block says how much of it is recoverable steel and non-ferrous metal. The
   kerf (the steel burned away along the cuts) is a separate line, so
   `LDT = steel + kerf loss + non-ferrous + unsalable remainder` closes to rounding.
2. **Cutting** ([`cutting.py`](src/hullmind/cutting.py)). Speed and kerf come from the GCE
   table, interpolated log-log between thicknesses and never extrapolated. A plate cut into
   squares of side `a` has `2/a` metres of cut per square metre, so a tonne of plate of
   thickness `t` needs `2000/(rho t a)` metres of cut and loses the fraction `2 kerf/a` of
   its mass to the kerf; a complexity factor scales the cut length. Team-hours per tonne =
   cut length / (speed * utilization * torches) + handling.
3. **Schedule** ([`schedule.py`](src/hullmind/schedule.py)). Each block becomes work packages
   of about 150 t (several teams cut one block at once); the preparation (tank cleaning,
   gas-freeing, removal of the listed hazardous material) is shared the same way.
   Critical-path method for the unlimited-team duration; Graham list scheduling with the
   longest remaining path as priority for a given number of teams.
4. **Economics** ([`economics.py`](src/hullmind/economics.py)). One function, `profit()`,
   serves the cost-revenue statement, the break-even steel price and maximum bid (both
   closed forms, because profit is linear in each), the sensitivity analysis and the Monte
   Carlo. Labour is billed on worked hours, overhead and financing on duration, mobilization
   per team, so the number of teams has a real optimum (`ekip-secimi`).
5. **Risk.** Lognormal scrap price, non-ferrous price, duration and hazardous-material
   quantity with unit mean; probability of loss, percentiles, mean of the worst 5 %.
6. **Hazardous materials** ([`hazmat.py`](src/hullmind/hazmat.py)). A survey item is listed
   in Part I of the inventory when the concentration of the substance exceeds the IMO
   threshold (at any quantity for ozone-depleting and radioactive substances); a listed item
   adds its whole material mass to the removal job and the disposal cost.

## What is checked, and against what

Run `hullmind dogrulama` to repeat the model checks below on your machine; the tests repeat
them with fixed seeds.

- **Cutting speed table.** Interpolating a tabulated speed from its neighbours (leave one out)
  is off by at most 6.7 % (rms 2.1 %, median 0.9 %) over the 23 interior acetylene nodes and
  4.4 % over the 7 propane nodes. The worst point is 200 mm, where the table is sparsest
  (170 mm/min between 205 at 150 mm and 140 at 230 mm). The model reproduces every
  tabulated node exactly.
- **Kerf loss.** Rasterizing the burned strips of a 1.2 m plate cut into 3×3 pieces (a pixel
  is lost when it lies within half a kerf of a cut line; no cut-length formula involved)
  gives 0.00997 against the exact 0.01000 (0.25 %). For a large plate the exact loss tends to
  the `2 kerf/a` rule as the number of pieces grows (to 0.1 % at 4000×4000 pieces).
- **Cut length.** The metres of cut per tonne of an `n × n` grid of pieces approach
  `2000/(rho t a)` as `n` grows (10 % off for `n = 10`, 0.5 % for `n = 200`: the `(n-1)/n`
  of a finite grid).
- **Scheduling.** Two independent exact solvers, a brute force over every precedence-feasible
  order and a time-indexed mixed-integer program (HiGHS), agree on all 40 random 7-task
  instances. List scheduling is optimal in 38 of them, at worst 7.1 % above the optimum
  (mean 0.35 %), and never exceeds Graham's bound `2 - 1/m` or goes below the lower bound
  `max(critical path, work/teams)`. A classic five-task case shows the heuristic is not
  exact: tasks of 3, 3, 2, 2, 2 on two teams give 7 by list scheduling and 6 by both exact
  solvers. The critical-path duration equals the longest chain found by enumerating every
  path in 60 random networks, and with as many teams as tasks every task starts at its
  earliest start.
- **Economics.** The statement lines add up to `profit()`; the break-even steel price and the
  maximum bid solve `profit = target` (checked with a root finder); the profit's slope in
  the steel price is `steel_t (1 - fee)`; the duration and hazardous-material multipliers
  enter as derived.
- **Monte Carlo.** With only the steel price random, profit is affine in a lognormal variable,
  so its mean, standard deviation, loss probability and quantiles are known exactly. 400 000
  draws agree with them: mean 149 332 against 148 011 (standard error 1 444), standard
  deviation 913 463 against 912 913, probability of loss 0.4824 against 0.4828.
- **Hazardous-material thresholds.** The test compares every code with the value printed in
  MEPC.269(68) (asbestos 0.1 % = 1000 mg/kg, PCBs 50, cadmium 100, hexavalent chromium,
  lead and mercury 1000, PBBs 50, PBDEs 1000, PCNs 50, organotin 2500 mg tin/kg,
  chlorinated paraffins 1 %), and the listing rule at and just above each threshold.

## Example

The synthetic example ship ([`examples/ornek_gemi.json`](examples/ornek_gemi.json): a 1998
bulk carrier of 11 500 LDT, 16 blocks, a survey with asbestos, PCBs, CFC, TBT paint, lead
and mercury) with 10 teams and a bid of 240 USD/LDT, illustrative prices:

```
$ hullmind plan --gemi examples/ornek_gemi.json --ekip 10
  süre: 726 saat = 91 çalışma günü
  alt sınır: kritik yol 373 saat, iş yükü/ekip 628 saat; çizelge/alt sınır = 1,156 (Graham garantisi ≤ 1,90× en iyi)
  ekip kullanımı: %86,5
  kritik yoldaki bloklar: ön-temizlik, Konaklama üstyapısı, Kargo bölümü 1 (üst), Baş bölüm, Omurga ve çift dip

$ hullmind ekonomi --gemi examples/ornek_gemi.json --ekip 10 --teklif 240 --monte-carlo 200000 --tohum 1
  Çelik hurda geliri                       3.744.527
  Gemi satın alma bedeli                  -2.760.000
  Ekip işçiliği, sarf ve seferberlik        -856.751
  NET KÂR                                    267.383   (gelirin %6,0'i)
Zarar etmemek için çelik fiyatı ≥ 324 USD/t (şimdiki 350).
Kâr = 0 olan en yüksek teklif: 262,7 USD/LDT; gelirin %5'i kâr için: 243,7 USD/LDT.
Monte Carlo (200.000 çekiliş): ortalama 264.190, std 931.327, zarar olasılığı %42,8, ...
```

`ekip-secimi` scans the number of teams: 1 team earns -1 059 434 (785 working days),
3 teams -559, 8 teams 266 178, 11 teams 268 291 (best), 14 teams 245 211 (utilization falls
from 100 % to 77 %). The two steel rows of the sensitivity table (price and recovered tonnes)
are identical by construction: profit depends on their product.

## Things found along the way

- **One team per block made the plan absurd.** With a block as the unit of work, the critical
  path was the sum of a chain of 700-tonne blocks (2587 h with the earlier defaults), extra teams
  were useless (utilization 35 % with 10 teams) and the result depended on a modelling artefact. Blocks are
  now split into work packages, which several teams can work on at once.
- **The preparation was a single 464-hour job** (removing 19.6 t of listed hazardous
  material at 50 kg/h on one team), delaying everything by 58 days. It is shared among teams
  like any other work.
- **Billing every team for the whole duration** punished extra teams for waiting, which no
  yard does; labour is now billed on worked hours, with mobilization per team, which is what
  produces an interior optimum in the team scan.
- **The first import of scipy took two minutes** in a fresh virtual environment (the operating
  system scanning new binaries), which looked like a hang in the scheduler. It was not.
- **A discrepancy I did not resolve.** The default steel share of the lightweight is 93 %.
  Sources I read quote "about 90 %" of a ship as steel, but also, for 2012, about 9.8 million
  tonnes of steel scrap from 12 million LDT (82 %), second-hand through a summary. The shares
  are assumptions for that reason, and the input format is the ship's own survey.

## Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

hullmind ornek-gemi --tip dokme-yuk --ldt 11500 --yil 1998 --cikti gemi.json
hullmind kutle-dengesi --gemi gemi.json
hullmind kesim-hizi --kalinlik 14          # or --tablo for the manufacturer's table
hullmind tehlikeli-madde --gemi gemi.json  # --esikler prints the IMO table
hullmind plan --gemi gemi.json --ekip 10 --grafik gantt.png
hullmind ekonomi --gemi gemi.json --ekip 10 --teklif 240 --celik-fiyat 380 --monte-carlo 200000 --grafik risk.png
hullmind ekip-secimi --gemi gemi.json --teklif 240
hullmind rapor --gemi gemi.json --ekip 10 --teklif 240 --monte-carlo 100000 --cikti rapor.md
hullmind dogrulama
```

Ship types: `dokme-yuk` (bulk carrier), `tanker`, `konteyner`, `genel-yuk`. The ship file is
JSON (blocks with mass, plate thickness, steel and non-ferrous shares and `sonra`, the
blocks that must finish first; hazardous-material survey items by IMO code with the
material mass and either the substance mass or the concentration); edit it to describe a
real ship. `plan` and `ekonomi` take `--json`.

## Testing

```bash
pytest -v
```

72 tests in about 6 seconds, no mocking. Pure numerical Python (numpy, scipy, matplotlib), no
network, no model calls.

## Scope and limitations

- A planning and costing aid, not a safety plan: no hull-girder strength or stability during
  cutting, no tides, weather, beaching or pier logistics, no crane or transport limits, no
  worker-safety planning.
- The hazardous-material screen is arithmetic against the IMO thresholds for the quantities
  you enter; it is not a survey, and it does not replace the Inventory of Hazardous Materials
  or the regulations that apply to a given yard and flag.
- Cutting productivity assumes oxy-fuel cutting of plate at the manufacturer's speeds;
  thicknesses outside 3-300 mm (5-70 mm for propane) are clamped to the table edge and
  reported. The complexity factor, utilization and handling time are assumptions, not
  measurements.
- One price scenario with lognormal noise; no price correlation between steel and
  non-ferrous metal, no time value beyond the financing line.
- Defaults for prices and costs are illustrative placeholders.

## License

MIT -- see [LICENSE](LICENSE).
