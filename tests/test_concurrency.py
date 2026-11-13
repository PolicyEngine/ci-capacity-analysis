"""Properties of the per-minute concurrency sweep and the standard-pool rule.

Invariants:
- the sweep matches a direct count at every minute (differential, against the definition);
- each minute's count is non-negative and never exceeds the number of intervals;
- adding an interval never lowers any minute's count, and an interval outside the window changes nothing;
- a job runs or waits in a given minute, never both, when its timestamps are in order;
- only standard labels outside a larger-runner group count toward the plan limit.
Round trip: the committed minute series and summary rebuild from the raw job records when present.
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


def test_standard_pool_follows_labels_and_group():
    assert metrics.standard_pool({"labels": ["ubuntu-latest"], "runner_group_name": "GitHub Actions"})
    assert metrics.standard_pool({"labels": ["macos-14"], "runner_group_name": None})
    assert not metrics.standard_pool({"labels": ["ubuntu-latest"], "runner_group_name": "Larger runners"})
    assert not metrics.standard_pool({"labels": ["self-hosted", "linux"]})
    assert not metrics.standard_pool({"labels": []}) and not metrics.standard_pool({})


def test_committed_series_rebuilds_from_raw():
    raw = os.path.join(ROOT, "data", "raw", "org-jobs")
    if not os.path.isdir(raw) or not os.listdir(raw):
        pytest.skip("raw job records absent; run scripts/collect_org_jobs.py")
    import org_concurrency as oc

    jobs = oc.load()
    lo, hi = metrics.t(oc.LO), metrics.t(oc.HI)
    run_iv, wait_iv = oc.intervals(jobs)
    running, waiting = metrics.sweep(run_iv, lo, hi), metrics.sweep(wait_iv, lo, hi)
    rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "pe_org_concurrency_minutes.csv"))))
    assert [int(r["running"]) for r in rows] == running and [int(r["waiting"]) for r in rows] == waiting
    summary = json.load(open(os.path.join(ROOT, "data", "pe_org_concurrency_summary.json")))
    assert summary["minutes"] == len(running) == 14 * 24 * 60
    assert summary["minutes_running_at_or_over_limit"] == sum(r >= oc.LIMIT for r in running)
    assert summary["wait_by_jobs_running_at_creation"] == json.loads(json.dumps(oc.wait_by_running(jobs, running, lo)))
    assert sum(g["jobs"] for g in summary["wait_by_jobs_running_at_creation"].values()) <= summary["standard_jobs"]
