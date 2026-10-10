import numpy as np
import pytest

from hullmind import checks, cutting, hazmat, schedule as sch, ship as s
from hullmind.schedule import Task


def textbook():
    return [Task("A", 3), Task("B", 2, ("A",)), Task("C", 4, ("A",)), Task("D", 2, ("B", "C"))]


def check_valid(tasks, schedule):
    by = {t.name: t for t in tasks}
    end = {e.task: e.end for e in schedule.entries}
    start = {e.task: e.start for e in schedule.entries}
    assert set(end) == set(by)
    for t in tasks:
        assert end[t.name] - start[t.name] == pytest.approx(t.hours)
        for d in t.after:
            assert start[t.name] >= end[d] - 1e-9
    for team in range(schedule.teams):
        spans = sorted((e.start, e.end) for e in schedule.entries if e.team == team)
        assert all(a[1] <= b[0] + 1e-9 for a, b in zip(spans, spans[1:]))


def test_cpm_on_the_textbook_network():
    r = sch.cpm(textbook())
    assert r.duration == 9.0
    assert r.critical_path == ["A", "C", "D"]
    assert r.slack("B") == 2.0 and r.slack("A") == r.slack("C") == r.slack("D") == 0.0
    assert r.earliest_start["D"] == 7.0 and r.latest_finish["B"] == 7.0
    assert sch.bottom_levels(textbook()) == {"A": 9.0, "B": 4.0, "C": 6.0, "D": 2.0}


def test_list_schedule_properties_on_the_textbook_network():
    t = textbook()
    one = sch.list_schedule(t, 1)
    assert one.makespan == pytest.approx(11.0) and one.utilization() == pytest.approx(1.0)  # total work
    two = sch.list_schedule(t, 2)
    assert two.makespan == pytest.approx(9.0)  # the critical path
    many = sch.list_schedule(t, 10)
    assert many.makespan == pytest.approx(sch.cpm(t).duration)
    for plan in (one, two, many):
        check_valid(t, plan)
    assert sch.lower_bound(t, 1) == 11.0 and sch.lower_bound(t, 2) == 9.0


def test_list_scheduling_is_not_always_optimal_and_the_exact_solvers_prove_it():
    tasks = [Task("a", 3), Task("b", 3), Task("c", 2), Task("d", 2), Task("e", 2)]
    heuristic = sch.list_schedule(tasks, 2).makespan
    assert heuristic == 7.0  # 3+2+2 on one team, 3+2 on the other
    assert sch.optimal_makespan_bruteforce(tasks, 2) == 6.0  # {3,3} and {2,2,2}
    assert sch.optimal_makespan_milp(tasks, 2) == 6
    assert heuristic / 6.0 <= sch.graham_bound(2)  # 7/6 <= 3/2


def test_two_exact_solvers_agree_and_bound_the_heuristic_on_random_instances():
    study = checks.schedule_study(instances=40, n=7, seed=11)
    assert study.exact_solvers_agree == study.instances
    assert study.bound_violations == 0 and study.lower_bound_violations == 0
    assert study.heuristic_optimal >= 0.8 * study.instances
    assert 1.0 <= study.worst_ratio <= 1.5
    assert 1.0 <= study.mean_ratio < 1.02


def test_heuristic_is_valid_and_respects_the_lower_bound_on_larger_random_instances():
    rng = np.random.default_rng(2)
    for _ in range(25):
        tasks = checks.random_tasks(rng, 30, 0.15, 9)
        for m in (1, 3, 6):
            plan = sch.list_schedule(tasks, m)
            check_valid(tasks, plan)
            lb = sch.lower_bound(tasks, m)
            assert lb - 1e-9 <= plan.makespan <= sch.graham_bound(m) * lb + 1e-9  # Graham's bound against the lower bound
            if m == 1:
                assert plan.makespan == pytest.approx(sum(t.hours for t in tasks))


def test_task_list_validation():
    for bad in ([Task("a", 1), Task("a", 2)], [Task("a", 1, ("x",))], [Task("a", -1)],
                [Task("a", 1, ("b",)), Task("b", 1, ("a",))]):
        with pytest.raises(sch.ScheduleError):
            sch.cpm(bad)
    with pytest.raises(sch.ScheduleError):
        sch.list_schedule(textbook(), 0)
    with pytest.raises(sch.ScheduleError):
        sch.optimal_makespan_milp([Task("a", 1.5)], 1)


# --- the ship's task list ----------------------------------------------------------------------

def test_build_tasks_conserves_the_work_and_maps_dependencies_to_packages():
    ship = s.example_ship("dokme-yuk", 11500, 1998)
    findings = hazmat.screen(list(ship.hazmat))
    cut = cutting.CutParams()
    tasks, clamped, packages = sch.build_tasks(ship, cut, findings, sch.PrepParams(), package_t=150.0)
    by = {t.name: t for t in tasks}
    assert not clamped
    # work of a block = steel cutting + handling of the whole block
    for b in ship.blocks:
        per_t, _ = cutting.cutting_hours_per_tonne(b.plate_mm, cut)
        expected = b.mass_t * b.steel_share * per_t + b.mass_t * cut.handling_h_per_t
        assert sum(by[p].hours for p in packages[b.name]) == pytest.approx(expected)
        assert len(packages[b.name]) == int(np.ceil(b.mass_t / 150.0))
    removal_kg = sum(f.item.material_kg for f in findings if f.listed)
    assert sum(by[p].hours for p in packages[s.PREP]) == pytest.approx(72.0 + removal_kg / 50.0)
    # a block waits for every package of each predecessor, and starts after the preparation
    keel = ship.block("Omurga ve çift dip")
    assert set(by[packages[keel.name][0]].after) == {p for dep in keel.after for p in packages[dep]}
    first = ship.block("Güverte ekipmanı")
    assert set(by[packages[first.name][0]].after) == set(packages[s.PREP])
    assert sch.cpm(tasks).critical_path[0].startswith(s.PREP)


def test_clamped_plates_are_reported():
    ship = s.example_ship()
    thin = s.Ship(ship.name, ship.ship_type, ship.ldt, ship.build_year,
                  tuple(s.Block(b.name, b.mass_t, 2.0 if b.name == "Konaklama üstyapısı" else b.plate_mm, b.steel_share,
                                b.nonferrous_share, b.after, b.kind) for b in ship.blocks))
    _, clamped, _ = sch.build_tasks(thin, cutting.CutParams())
    assert clamped == ["Konaklama üstyapısı"]


def test_more_teams_shorten_the_job_down_to_the_critical_path():
    ship = s.example_ship("tanker", 30000, 2001)
    tasks, _, packages = sch.build_tasks(ship, cutting.CutParams(), (), sch.PrepParams())
    cp = sch.cpm(tasks).duration
    plans = {m: sch.list_schedule(tasks, m) for m in (1, 2, 4, 8, 16, len(tasks))}
    assert plans[1].makespan == pytest.approx(sum(t.hours for t in tasks))
    assert plans[2].makespan < 0.6 * plans[1].makespan
    assert plans[len(tasks)].makespan == pytest.approx(cp)  # as many teams as jobs: the critical path
    for m, plan in plans.items():
        assert plan.makespan >= sch.lower_bound(tasks, m) - 1e-6
        assert 0 < plan.utilization() <= 1.0 + 1e-9
    spans = sch.block_spans(plans[8], packages)
    assert set(spans) == set(packages)
    assert all(a < b for a, b in spans.values())
    for b in ship.blocks:  # a block starts after all its predecessors end
        for dep in b.after:
            assert spans[b.name][0] >= spans[dep][1] - 1e-9


# --- independent checks of the critical-path method --------------------------------------------------

def longest_path_by_enumeration(tasks):
    """Longest chain by depth-first enumeration of every path: no forward/backward pass involved."""
    by = {t.name: t for t in tasks}
    successors = {t.name: [u.name for u in tasks if t.name in u.after] for t in tasks}
    best = 0.0

    def walk(name, total):
        nonlocal best
        total += by[name].hours
        if not successors[name]:
            best = max(best, total)
        for nxt in successors[name]:
            walk(nxt, total)

    for t in tasks:
        if not t.after:
            walk(t.name, 0.0)
    return best


def test_cpm_duration_equals_the_longest_enumerated_path_on_random_networks():
    rng = np.random.default_rng(21)
    for _ in range(60):
        tasks = checks.random_tasks(rng, int(rng.integers(3, 11)), 0.35, 9)
        result = sch.cpm(tasks)
        assert result.duration == pytest.approx(longest_path_by_enumeration(tasks))
        by = {t.name: t for t in tasks}
        chain = result.critical_path
        assert sum(by[n].hours for n in chain) == pytest.approx(result.duration)
        for earlier, later in zip(chain, chain[1:]):
            assert earlier in by[later].after


def test_with_enough_teams_every_task_starts_at_its_earliest_start():
    rng = np.random.default_rng(8)
    for _ in range(20):
        tasks = checks.random_tasks(rng, 12, 0.3, 7)
        plan = sch.list_schedule(tasks, len(tasks))
        es = sch.cpm(tasks).earliest_start
        for e in plan.entries:
            assert e.start == pytest.approx(es[e.task])


def test_exact_solvers_agree_with_each_other_on_instances_with_one_team_and_with_many():
    rng = np.random.default_rng(31)
    for _ in range(12):
        tasks = checks.random_tasks(rng, 6, 0.3, 5)
        total = sum(t.hours for t in tasks)
        assert sch.optimal_makespan_bruteforce(tasks, 1) == pytest.approx(total)  # one team: the work, whatever the order
        assert sch.optimal_makespan_milp(tasks, 1) == round(total)
        assert sch.optimal_makespan_bruteforce(tasks, 6) == pytest.approx(sch.cpm(tasks).duration)  # one team per task
        assert sch.optimal_makespan_milp(tasks, 6) == round(sch.cpm(tasks).duration)
