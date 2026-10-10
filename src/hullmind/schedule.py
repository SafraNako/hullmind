"""Scheduling the dismantling: precedence constraints, a limited number of cutting teams.

* :func:`cpm` is the critical-path method: earliest and latest times, slack, and the project
  duration when there are as many teams as jobs.
* :func:`list_schedule` is Graham's list scheduling with the longest remaining path as the
  priority: whenever a team is free it takes the ready job with the most work still behind it.
* :func:`optimal_makespan_bruteforce` and :func:`optimal_makespan_milp` are two independent exact
  solvers for small instances, used to measure how far the heuristic is from the optimum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from .cutting import CutParams, cutting_hours_per_tonne
from .hazmat import Finding, removal_mass_by_code
from .ship import PREP, Ship


class ScheduleError(ValueError):
    """Invalid task list (duplicate names, unknown predecessors, cycles) or team count."""


@dataclass(frozen=True)
class Task:
    name: str
    hours: float
    after: Tuple[str, ...] = ()


def _validate(tasks: Sequence[Task]) -> Dict[str, Task]:
    by_name = {t.name: t for t in tasks}
    if len(by_name) != len(tasks):
        raise ScheduleError("görev adları benzersiz olmalı")
    for t in tasks:
        if t.hours < 0:
            raise ScheduleError(f"{t.name}: süre negatif olamaz")
        for dep in t.after:
            if dep not in by_name:
                raise ScheduleError(f"{t.name}: bilinmeyen öncül {dep!r}")
    _order(tasks)
    return by_name


def _order(tasks: Sequence[Task]) -> List[str]:
    remaining = {t.name: set(t.after) for t in tasks}
    out: List[str] = []
    while remaining:
        ready = sorted(n for n, deps in remaining.items() if not deps)
        if not ready:
            raise ScheduleError("görevlerde döngü var")
        for n in ready:
            out.append(n)
            del remaining[n]
        for deps in remaining.values():
            deps.difference_update(ready)
    return out


# ---------------------------------------------------------------------------
# critical path
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CPMResult:
    earliest_start: Dict[str, float]
    earliest_finish: Dict[str, float]
    latest_start: Dict[str, float]
    latest_finish: Dict[str, float]
    duration: float  # project duration with unlimited teams
    critical_path: List[str]

    def slack(self, name: str) -> float:
        return self.latest_start[name] - self.earliest_start[name]


def cpm(tasks: Sequence[Task]) -> CPMResult:
    by_name = _validate(tasks)
    order = _order(tasks)
    es: Dict[str, float] = {}
    ef: Dict[str, float] = {}
    for n in order:
        es[n] = max((ef[d] for d in by_name[n].after), default=0.0)
        ef[n] = es[n] + by_name[n].hours
    duration = max(ef.values())
    successors: Dict[str, List[str]] = {n: [] for n in by_name}
    for t in tasks:
        for d in t.after:
            successors[d].append(t.name)
    lf: Dict[str, float] = {}
    ls: Dict[str, float] = {}
    for n in reversed(order):
        lf[n] = min((ls[s] for s in successors[n]), default=duration)
        ls[n] = lf[n] - by_name[n].hours
    eps = 1e-9 * max(1.0, duration)
    critical = [n for n in order if abs(ls[n] - es[n]) <= eps]
    # one chain of critical tasks from a start to the end
    chain: List[str] = []
    starts = [n for n in critical if es[n] <= eps]
    current = max(starts, key=lambda n: ef[n]) if starts else None
    while current is not None:
        chain.append(current)
        nxt = [s for s in successors[current] if s in critical and abs(es[s] - ef[current]) <= eps]
        current = max(nxt, key=lambda n: by_name[n].hours) if nxt else None
    return CPMResult(es, ef, ls, lf, duration, chain)


def bottom_levels(tasks: Sequence[Task]) -> Dict[str, float]:
    """Longest path (including the task's own duration) from each task to the end of the project."""
    by_name = _validate(tasks)
    order = _order(tasks)
    successors: Dict[str, List[str]] = {n: [] for n in by_name}
    for t in tasks:
        for d in t.after:
            successors[d].append(t.name)
    level: Dict[str, float] = {}
    for n in reversed(order):
        level[n] = by_name[n].hours + max((level[s] for s in successors[n]), default=0.0)
    return level


# ---------------------------------------------------------------------------
# heuristic and bounds
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    task: str
    team: int
    start: float
    end: float


@dataclass(frozen=True)
class Schedule:
    entries: Tuple[Entry, ...]
    teams: int
    makespan: float

    def busy_hours(self) -> float:
        return sum(e.end - e.start for e in self.entries)

    def utilization(self) -> float:
        return self.busy_hours() / (self.teams * self.makespan) if self.makespan > 0 else 1.0


def lower_bound(tasks: Sequence[Task], teams: int) -> float:
    """No schedule can finish before the critical path, nor before the total work divided by the teams."""
    if teams < 1:
        raise ScheduleError("ekip sayısı en az 1 olmalı")
    return max(cpm(tasks).duration, sum(t.hours for t in tasks) / teams)


def list_schedule(tasks: Sequence[Task], teams: int) -> Schedule:
    """Graham list scheduling; priority = longest remaining path (critical-path priority)."""
    if teams < 1:
        raise ScheduleError("ekip sayısı en az 1 olmalı")
    by_name = _validate(tasks)
    level = bottom_levels(tasks)
    finish: Dict[str, float] = {}
    free_at = [0.0] * teams
    waiting = set(by_name)
    entries: List[Entry] = []
    time = 0.0
    while waiting:
        ready = [n for n in waiting if all(d in finish and finish[d] <= time + 1e-12 for d in by_name[n].after)]
        ready.sort(key=lambda n: (-level[n], n))
        idle = [j for j in range(teams) if free_at[j] <= time + 1e-12]
        for name, team in zip(ready, idle):
            end = time + by_name[name].hours
            entries.append(Entry(name, team, time, end))
            finish[name] = end
            free_at[team] = end
            waiting.discard(name)
        if not waiting:
            break
        upcoming = [f for f in list(free_at) + list(finish.values()) if f > time + 1e-12]
        time = min(upcoming)
    return Schedule(tuple(sorted(entries, key=lambda e: (e.start, e.team))), teams, max(e.end for e in entries))


# ---------------------------------------------------------------------------
# exact solvers for small instances
# ---------------------------------------------------------------------------

def _topological_orders(tasks: Sequence[Task]):
    by_name = {t.name: t for t in tasks}
    names = sorted(by_name)

    def rec(done: Tuple[str, ...], remaining: frozenset):
        if not remaining:
            yield done
            return
        for n in sorted(remaining):
            if all(d in done for d in by_name[n].after):
                yield from rec(done + (n,), remaining - {n})

    yield from rec((), frozenset(names))


def optimal_makespan_bruteforce(tasks: Sequence[Task], teams: int) -> float:
    """Exact optimum by trying every precedence-feasible order and placing each task as early as possible.

    Any left-shifted schedule is obtained from the list of its tasks sorted by start time, so the
    best order gives the optimum.
    """
    by_name = _validate(tasks)
    best = float("inf")
    for order in _topological_orders(tasks):
        free = [0.0] * teams
        finish: Dict[str, float] = {}
        for n in order:
            ready = max((finish[d] for d in by_name[n].after), default=0.0)
            starts = [max(f, ready) for f in free]
            earliest = min(starts)
            j = max((j for j in range(teams) if starts[j] == earliest), key=lambda j: free[j])
            finish[n] = earliest + by_name[n].hours
            free[j] = finish[n]
        best = min(best, max(finish.values()))
    return best


def optimal_makespan_milp(tasks: Sequence[Task], teams: int) -> int:
    """Exact optimum for integer durations with a time-indexed mixed-integer program (HiGHS)."""
    from scipy.optimize import Bounds, LinearConstraint, milp

    by_name = _validate(tasks)
    names = sorted(by_name)
    p = {n: int(round(by_name[n].hours)) for n in names}
    if any(abs(by_name[n].hours - p[n]) > 1e-9 for n in names):
        raise ScheduleError("MILP çözücü tamsayı süre ister")
    horizon = sum(p.values())
    index: Dict[Tuple[str, int], int] = {}
    for n in names:
        for t in range(0, horizon - p[n] + 1):
            index[(n, t)] = len(index)
    n_x = len(index)
    nvar = n_x + 1  # last variable: the makespan
    cost = np.zeros(nvar)
    cost[-1] = 1.0
    rows: List[np.ndarray] = []
    lo: List[float] = []
    hi: List[float] = []
    for n in names:  # every task starts exactly once
        row = np.zeros(nvar)
        for t in range(0, horizon - p[n] + 1):
            row[index[(n, t)]] = 1.0
        rows.append(row), lo.append(1.0), hi.append(1.0)
    for tau in range(horizon):  # at most `teams` tasks run at any time
        row = np.zeros(nvar)
        for n in names:
            for t in range(max(0, tau - p[n] + 1), min(tau, horizon - p[n]) + 1):
                row[index[(n, t)]] = 1.0
        rows.append(row), lo.append(0.0), hi.append(float(teams))
    for n in names:  # precedence and makespan
        for d in by_name[n].after:
            row = np.zeros(nvar)
            for t in range(0, horizon - p[n] + 1):
                row[index[(n, t)]] += t
            for t in range(0, horizon - p[d] + 1):
                row[index[(d, t)]] -= t + p[d]
            rows.append(row), lo.append(0.0), hi.append(np.inf)
        row = np.zeros(nvar)
        row[-1] = 1.0
        for t in range(0, horizon - p[n] + 1):
            row[index[(n, t)]] -= t + p[n]
        rows.append(row), lo.append(0.0), hi.append(np.inf)
    integrality = np.ones(nvar)
    bounds = Bounds(np.zeros(nvar), np.concatenate([np.ones(n_x), [horizon]]))
    result = milp(cost, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=integrality, bounds=bounds)
    if not result.success:
        raise ScheduleError("MILP çözülemedi: " + str(result.message))
    return int(round(result.x[-1]))


def graham_bound(teams: int) -> float:
    """List scheduling is within ``2 - 1/m`` of the optimum (Graham 1966)."""
    return 2.0 - 1.0 / teams


# ---------------------------------------------------------------------------
# the dismantling plan of a ship
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrepParams:
    base_hours: float = 72.0  # tank cleaning, gas-freeing, inspection
    hazmat_kg_per_h: float = 50.0  # removal rate of listed hazardous material, per team
    package_hours: float = 80.0  # the preparation is shared among teams in jobs of about this length


def package_names(block_name: str, count: int) -> List[str]:
    return [block_name] if count == 1 else [f"{block_name} [{i}/{count}]" for i in range(1, count + 1)]


def build_tasks(
    ship: Ship, cut: CutParams, findings: Sequence[Finding] = (), prep: PrepParams = PrepParams(),
    package_t: float = 150.0,
):
    """Tasks of the ship: the preparation job and, per block, work packages of about ``package_t`` tonnes.

    A block is cut by several teams at once, so it is split into equal packages that all wait for
    the block's predecessors, and whatever follows the block waits for all of them.
    Returns ``(tasks, clamped_blocks, packages_by_block)``.
    """
    if package_t <= 0:
        raise ScheduleError("iş paketi büyüklüğü pozitif olmalı")
    removal_kg = sum(removal_mass_by_code(list(findings)).values())
    prep_hours = prep.base_hours + removal_kg / prep.hazmat_kg_per_h
    n_prep = max(1, int(np.ceil(prep_hours / prep.package_hours - 1e-9)))
    prep_names = package_names(PREP, n_prep)
    tasks = [Task(name, prep_hours / n_prep, ()) for name in prep_names]
    clamped: List[str] = []
    packages: Dict[str, List[str]] = {PREP: prep_names}
    for b in ship.blocks:  # blocks are listed so that dependencies may refer to any of them
        count = max(1, int(np.ceil(b.mass_t / package_t - 1e-9)))
        packages[b.name] = package_names(b.name, count)
    for b in ship.blocks:
        per_t, was_clamped = cutting_hours_per_tonne(b.plate_mm, cut)
        if was_clamped:
            clamped.append(b.name)
        hours = b.mass_t * b.steel_share * per_t + b.mass_t * cut.handling_h_per_t
        after: List[str] = []
        for dep in (b.after if b.after else (PREP,)):
            after.extend(packages[dep])
        for name in packages[b.name]:
            tasks.append(Task(name, hours / len(packages[b.name]), tuple(after)))
    return tasks, clamped, packages


def block_spans(schedule: Schedule, packages: Dict[str, List[str]]) -> Dict[str, Tuple[float, float]]:
    """Start and end of each block: from its first package starting to its last one finishing."""
    by_task = {e.task: e for e in schedule.entries}
    return {b: (min(by_task[p].start for p in names), max(by_task[p].end for p in names))
            for b, names in packages.items()}
