"""Properties of the per-minute concurrency sweep and the standard-pool rule.

Invariants:
- the sweep matches a direct count at every minute (differential, against the definition);
- each minute's count is non-negative and never exceeds the number of intervals;
- adding an interval never lowers any minute's count, and an interval outside the window changes nothing;
- a job runs or waits in a given minute, never both, when its timestamps are in order;
- the sweep handles a window that ends inside a minute;
- only standard labels in GitHub's own runner group count toward the plan limit;
- a job a re-run attempt carries over counts as one execution with its first creation time, and a
  job that ran again counts twice; in the committed executions no runner starts two jobs at once
  and no job starts before GitHub created it;
- the count of executions running at an instant matches a direct count.
Round trip: the committed minute series and summary rebuild from the committed executions.
"""

import csv
import datetime as dt
import json
import os
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import metrics  # noqa: E402

LO = dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc)


def at(seconds):
    return LO + dt.timedelta(seconds=seconds)


interval = st.tuples(st.integers(-4000, 16000), st.integers(0, 9000)).map(lambda p: (at(p[0]), at(p[0] + p[1])))
window_minutes = st.integers(1, 180)


def direct(intervals, lo, hi):
    n = int((hi - lo).total_seconds() // 60)
    return [sum(1 for a, b in intervals if a <= lo + dt.timedelta(minutes=i) < b) for i in range(n)]


@given(st.lists(interval, max_size=40), window_minutes)
def test_sweep_matches_a_direct_count(intervals, n):
    hi = LO + dt.timedelta(minutes=n)
    counts = metrics.sweep(intervals, LO, hi)
    assert counts == direct(intervals, LO, hi)
    assert len(counts) == n and all(0 <= c <= len(intervals) for c in counts)


@given(st.lists(interval, max_size=30), interval, window_minutes)
def test_another_interval_never_lowers_a_count(intervals, extra, n):
    hi = LO + dt.timedelta(minutes=n)
    base = metrics.sweep(intervals, LO, hi)
    more = metrics.sweep(intervals + [extra], LO, hi)
    assert all(m >= b for m, b in zip(more, base))
    outside = (hi + dt.timedelta(minutes=1), hi + dt.timedelta(minutes=9))
    assert metrics.sweep(intervals + [outside, (None, hi), (LO, None)], LO, hi) == base


@given(st.integers(0, 6000), st.integers(0, 3000), st.integers(0, 3000), window_minutes)
def test_a_job_waits_then_runs(created, wait, duration, n):
    c, s, e = at(created), at(created + wait), at(created + wait + duration)
    hi = LO + dt.timedelta(minutes=n)
    waiting, running = metrics.sweep([(c, s)], LO, hi), metrics.sweep([(s, e)], LO, hi)
    assert all(w + r <= 1 for w, r in zip(waiting, running))
    assert [w + r for w, r in zip(waiting, running)] == metrics.sweep([(c, e)], LO, hi)


@given(st.lists(interval, max_size=30), st.integers(1, 9000))
def test_sweep_handles_a_window_that_ends_inside_a_minute(intervals, seconds):
    hi = LO + dt.timedelta(seconds=seconds)
    n = -(-seconds // 60)
    expected = [sum(1 for a, b in intervals if a <= LO + dt.timedelta(minutes=i) < b and LO + dt.timedelta(minutes=i) < hi)
                for i in range(n)]
    assert metrics.sweep(intervals, LO, hi) == expected


def test_standard_pool_follows_labels_and_group():
    assert metrics.standard_pool({"labels": ["ubuntu-latest"], "runner_group_name": "GitHub Actions"})
    assert metrics.standard_pool({"labels": ["macos-14"], "runner_group_name": None})
    assert metrics.standard_pool({"labels": ["ubuntu-24.04-arm"], "runner_group_name": ""})
    assert not metrics.standard_pool({"labels": ["ubuntu-latest"], "runner_group_name": "Larger runners"})
    assert not metrics.standard_pool({"labels": ["self-hosted", "ubuntu-latest"]})
    assert not metrics.standard_pool({"labels": ["ubuntu-big"], "runner_group_name": "Compute"})
    assert not metrics.standard_pool({"labels": ["ubuntu-latest"], "runner_group_name": "Compute"})
    assert not metrics.standard_pool({"labels": ["ubuntu-latest-4-cores"], "runner_group_name": "GitHub Actions"})
    assert not metrics.standard_pool({"labels": []}) and not metrics.standard_pool({})


def job(name, created, started, completed, runner="GitHub Actions 7", run_id=1, repo="r"):
    stamp = lambda x: None if x is None else at(x).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return {"repo": repo, "run_id": run_id, "name": name, "created_at": stamp(created), "started_at": stamp(started),
            "completed_at": stamp(completed), "runner_name": runner}


def test_a_carried_over_job_counts_once_and_a_rerun_counts_twice():
    first = job("Test", 0, 120, 720)
    carried = job("Test", 86_400, 120, 720)            # attempt two lists it again: same runner and times
    rerun = job("Test", 86_400, 86_520, 87_000, runner="GitHub Actions 9")
    queued = job("Lint", 60, None, 300, runner=None)   # cancelled before any runner took it
    other_run = job("Test", 0, 120, 720, run_id=2)     # same names and times in another run stay separate
    rows = metrics.executions([carried, first, rerun, queued, other_run])
    ran = [j for j in rows if j["runner_name"]]
    assert len(rows) == 4 and len(ran) == 3
    kept = next(j for j in ran if j["run_id"] == 1 and j["started_at"] == first["started_at"])
    assert kept["created_at"] == first["created_at"]   # the earliest creation survives, so the wait is 2 minutes
    assert all(metrics.minutes(j["created_at"], j["started_at"]) >= 0 for j in ran)
    hi = LO + dt.timedelta(minutes=20)
    running = metrics.sweep([(metrics.t(j["started_at"]), metrics.t(j["completed_at"])) for j in ran], LO, hi)
    assert running == [0, 0] + [2] * 10 + [0] * 8      # runs 1 and 2, minutes 2 to 11; a double count would give 3


times = st.integers(0, 5000)


@given(st.lists(st.tuples(times, st.integers(0, 3000)), max_size=40), times)
def test_running_at_matches_a_direct_count(spans, when):
    iv = [(at(a), at(a + d)) for a, d in spans]
    starts, ends = sorted(a for a, _ in iv), sorted(b for _, b in iv)
    assert metrics.running_at(starts, ends, at(when)) == sum(1 for a, b in iv if a <= at(when) < b)


def test_running_at_reads_the_second_not_the_minute():
    starts, ends = [at(30), at(40)], [at(50), at(600)]
    assert metrics.running_at(starts, ends, at(45)) == 2   # both run 45 seconds in
    assert metrics.sweep(list(zip(starts, ends)), LO, LO + dt.timedelta(minutes=1)) == [0]   # the minute mark saw none


def test_quantile_takes_the_nearest_rank():
    assert [metrics.quantile([1, 2, 3, 4], p) for p in (0, 0.25, 0.5, 0.75, 0.9, 1)] == [1, 1, 2, 3, 4, 4]
    assert metrics.quantile(range(1, 11), 0.9) == 9 and metrics.quantile([7], 0.5) == 7


def test_committed_series_rebuilds_from_the_committed_executions():
    import org_concurrency as oc

    rows = oc.load_saved()
    ran = [j for j in rows if j["runner_name"] and j["started_at"]]
    assert all(j["created_at"] <= j["started_at"] for j in ran)                      # no carried-over copy survives
    assert len({(j["runner_name"], j["started_at"]) for j in ran}) == len(ran)       # one job per runner at a time
    running, waiting, summary = oc.summarize(rows)
    saved = list(csv.DictReader(open(os.path.join(ROOT, "data", "pe_org_concurrency_minutes.csv"))))
    assert [int(r["running"]) for r in saved] == running and [int(r["waiting"]) for r in saved] == waiting
    assert json.load(open(os.path.join(ROOT, "data", "pe_org_concurrency_summary.json"))) == json.loads(json.dumps(summary))
    assert summary["minutes"] == 14 * 24 * 60 and max(running) <= oc.LIMIT + 1


def test_executions_file_matches_the_raw_records():
    import org_concurrency as oc

    if not os.path.isdir(oc.RAW) or not os.listdir(oc.RAW):
        pytest.skip("raw job records absent; run scripts/collect_org_jobs.py")
    key = lambda j: tuple(str(j.get(k) or "") for k in oc.FIELDS)  # noqa: E731
    assert sorted(map(key, metrics.executions(oc.load_raw()))) == sorted(map(key, oc.load_saved()))
