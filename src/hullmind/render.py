"""Plots: schedule Gantt chart, cost-revenue waterfall, risk histogram and tornado chart."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .economics import RiskResult, Statement  # noqa: E402


def plot_gantt(spans: Dict[str, Tuple[float, float]], critical_blocks: Sequence[str], hours_per_day: float,
               path: str, title: str = "Sökum planı") -> None:
    names = sorted(spans, key=lambda n: spans[n][0])
    fig, ax = plt.subplots(figsize=(10, 0.38 * len(names) + 1.6))
    for i, name in enumerate(names):
        start, end = spans[name]
        colour = "#B14A3A" if name in critical_blocks else "#2F7D5C"
        ax.barh(i, (end - start) / hours_per_day, left=start / hours_per_day, color=colour, alpha=0.85)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("çalışma günü")
    ax.set_title(title + "  (kırmızı: kritik yol üzerindeki bloklar)")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_statement(st: Statement, path: str, title: str = "Gelir-gider tablosu") -> None:
    names = list(st.lines)
    values = [st.lines[n] for n in names]
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, v in enumerate(values):
        ax.bar(i, v, color="#2F7D5C" if v >= 0 else "#B14A3A", alpha=0.85)
    ax.bar(len(values), st.profit, color="#1B2A3D")
    ax.set_xticks(range(len(values) + 1))
    ax.set_xticklabels(names + ["NET"], rotation=40, ha="right", fontsize=8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("USD")
    ax.set_title(f"{title}: net {st.profit:,.0f} USD".replace(",", "."))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_risk(result: RiskResult, tornado_rows: List[Tuple[str, float, float]], path: str) -> None:
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 4.8))
    ax.hist(result.samples / 1e6, bins=100, color="#2F7D5C", alpha=0.8, density=True)
    ax.axvline(0, color="k", lw=1)
    for q, v in result.percentiles.items():
        ax.axvline(v / 1e6, color="#B8862E", ls="--", lw=0.8)
    ax.set_xlabel("net kâr (milyon USD)")
    ax.set_title(f"Monte Carlo (n = {result.n:,}): P(zarar) = {result.prob_loss:.1%}".replace(",", "."))
    names = [r[0] for r in tornado_rows][::-1]
    lows = [r[1] / 1e6 for r in tornado_rows][::-1]
    highs = [r[2] / 1e6 for r in tornado_rows][::-1]
    y = np.arange(len(names))
    bx.barh(y, lows, color="#B14A3A", alpha=0.8, label="-%20")
    bx.barh(y, highs, color="#2F7D5C", alpha=0.8, label="+%20")
    bx.set_yticks(y)
    bx.set_yticklabels(names, fontsize=8)
    bx.axvline(0, color="k", lw=0.8)
    bx.set_xlabel("kârdaki değişim (milyon USD)")
    bx.set_title("Duyarlılık (her girdi ±%20)")
    bx.legend()
    bx.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
