"""The whole pipeline for one ship: screening, mass balance, plan, statement, risk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from . import economics as eco
from . import schedule as sch
from .cutting import CutParams
from .hazmat import Finding, screen
from .ship import Ship


@dataclass(frozen=True)
class Analysis:
    ship: Ship
    cut: CutParams
    findings: Tuple[Finding, ...]
    tasks: Tuple[sch.Task, ...]
    clamped_blocks: Tuple[str, ...]
    packages: Dict[str, List[str]]
    cpm: sch.CPMResult
    schedule: sch.Schedule
    parts: eco.Parts
    spans: Dict[str, Tuple[float, float]]
    critical_blocks: Tuple[str, ...]


def analyse(
    ship: Ship, cut: CutParams, teams: int, bid_usd_per_ldt: float, market: eco.Market = eco.Market(),
    yard: eco.Yard = eco.Yard(), prep: sch.PrepParams = sch.PrepParams(), package_t: float = 150.0,
) -> Analysis:
    ship.validate()
    findings = tuple(screen(list(ship.hazmat)))
    tasks, clamped, packages = sch.build_tasks(ship, cut, findings, prep, package_t)
    cpm = sch.cpm(tasks)
    schedule = sch.list_schedule(tasks, teams)
    parts = eco.make_parts(ship, cut, schedule, findings, market, yard, bid_usd_per_ldt)
    spans = sch.block_spans(schedule, packages)
    owner = {p: b for b, names in packages.items() for p in names}
    critical_blocks = tuple(dict.fromkeys(owner[t] for t in cpm.critical_path if t in owner))
    return Analysis(ship, cut, findings, tuple(tasks), tuple(clamped), packages, cpm, schedule, parts, spans,
                    critical_blocks)


def team_scan(
    ship: Ship, cut: CutParams, max_teams: int, bid_usd_per_ldt: float, market: eco.Market, yard: eco.Yard,
    prep: sch.PrepParams = sch.PrepParams(), package_t: float = 150.0,
) -> List[Tuple[int, float, float, float]]:
    """``(teams, makespan_h, utilization, profit)`` for 1..``max_teams`` teams."""
    findings = tuple(screen(list(ship.hazmat)))
    tasks, _, _ = sch.build_tasks(ship, cut, findings, prep, package_t)
    rows = []
    for m in range(1, max_teams + 1):
        schedule = sch.list_schedule(tasks, m)
        parts = eco.make_parts(ship, cut, schedule, findings, market, yard, bid_usd_per_ldt)
        rows.append((m, schedule.makespan, schedule.utilization(), eco.profit(parts)))
    return rows
