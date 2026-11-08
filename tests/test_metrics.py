"""Properties of the metric definitions, and agreement with the 10/24 definitions they reuse.

Invariants:
- every job wait is non-negative when each job starts at or after it was queued;
- a run's wall time is at least each counted job's own queued-to-finished span, and shifting
  every timestamp by the same amount leaves it unchanged;
- jobs from later attempts, or with no runner, never change waits or wall time;
- a run with a failed attempt-one job, or a non-success conclusion, is never a strict success;
- nearest-rank quantiles rise with p and stay within the data's range;
- the bootstrap interval is ordered, inside the data's range, and the same for the same seed.
Differential: metrics.py matches the wait and wall definitions of analyze_post_upgrade.py in the
2026-10-24 internal report, transcribed below as the reference.
"""

import datetime as dt
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import metrics  # noqa: E402

BASE = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)


def iso(minutes):
    return (BASE + dt.timedelta(seconds=round(minutes * 60))).strftime("%Y-%m-%dT%H:%M:%SZ")


@st.composite
def jobs(draw, shift=0):
    created = draw(st.integers(0, 600))
    wait = draw(st.integers(0, 300))
    duration = draw(st.integers(0, 400))
    runner = draw(st.booleans())
    return {
        "name": draw(st.sampled_from(["Lint", "Test (1)", "Test (2)", "Contrib", "Baseline"])),
        "status": "completed",
        "conclusion": draw(st.sampled_from(["success", "skipped", "failure", "cancelled"])),
        "run_attempt": draw(st.sampled_from([1, 1, 1, 2])),
        "created_at": iso(created + shift),
        "started_at": iso(created + wait + shift) if runner else None,
        "completed_at": iso(created + wait + duration + shift) if runner else iso(created + shift),
        "runner_name": "GitHub Actions 1" if runner else None,
    }


runs = st.builds(
    lambda js, concl, att: {"conclusion": concl, "run_attempt": att, "jobs": js},
    st.lists(jobs(), max_size=12),
    st.sampled_from(["success", "failure"]),
    st.sampled_from([1, 1, 2]),
)


@given(runs)
def test_waits_non_negative(run):
    assert all(w >= 0 for w in metrics.job_waits(run))


@given(runs)
def test_wall_covers_each_counted_job(run):
    w = metrics.wall(run)
    counted = [j for j in run["jobs"] if metrics.ran(j)]
    if not counted:
        assert w is None
        return
    for j in counted:
        assert w + 1e-9 >= metrics.minutes(j["created_at"], j["completed_at"])


@given(runs, st.integers(-10_000, 10_000))
def test_wall_and_waits_shift_invariant(run, shift):
    def moved(t):
        return None if t is None else iso(metrics.minutes(iso(0), t) + shift)

    shifted = dict(run, jobs=[dict(j, created_at=moved(j["created_at"]), started_at=moved(j["started_at"]),
                                   completed_at=moved(j["completed_at"])) for j in run["jobs"]])
    assert metrics.wall(shifted) == metrics.wall(run)
    assert metrics.job_waits(shifted) == metrics.job_waits(run)


@given(runs, st.lists(jobs(), max_size=4))
def test_uncounted_jobs_change_nothing(run, extra):
    noise = [dict(j, run_attempt=2) for j in extra] + [dict(j, runner_name=None, started_at=None) for j in extra]
    noisy = dict(run, jobs=run["jobs"] + noise)
    assert metrics.wall(noisy) == metrics.wall(run)
    assert metrics.job_waits(noisy) == metrics.job_waits(run)


@given(runs)
def test_strict_success_excludes_failures(run):
    if metrics.strict_success(run):
        assert run["conclusion"] == "success" and run["run_attempt"] == 1
        assert all(j["conclusion"] in ("success", "skipped") for j in run["jobs"] if j["run_attempt"] == 1)
    failed = dict(run, jobs=run["jobs"] + [dict(run["jobs"][0], run_attempt=1, conclusion="failure")]) if run["jobs"] else None
    if failed:
        assert not metrics.strict_success(failed)


values = st.lists(st.floats(0, 1e4, allow_nan=False), min_size=1, max_size=200)


@given(values, st.floats(0, 1), st.floats(0, 1))
def test_quantile_monotone_and_bounded(xs, p, q):
    lo, hi = sorted((p, q))
    assert metrics.quantile(xs, lo) <= metrics.quantile(xs, hi)
    assert min(xs) <= metrics.quantile(xs, lo) <= max(xs)
    assert metrics.quantile(xs, 0) == min(xs)
    assert min(xs) <= metrics.median(xs) <= max(xs)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.lists(st.floats(0, 1e3, allow_nan=False), min_size=1, max_size=8), min_size=1, max_size=15))
def test_bootstrap_interval_ordered_bounded_deterministic(groups):
    lo, hi = metrics.bootstrap_median(groups, reps=200)
    pooled = [x for g in groups for x in g]
    assert min(pooled) <= lo <= hi <= max(pooled)
    assert metrics.bootstrap_median(groups, reps=200) == (lo, hi)


# Reference: the wait and wall definitions of analyze_post_upgrade.py (internal report, 2026-10-24).
def _ref_ran(j):
    return j.get("runner_name") and j.get("started_at") and j.get("completed_at") and j.get("run_attempt") == 1


def _ref(rs):
    rs = [r for r in rs if r.get("jobs")]
    waits = [metrics.minutes(j["created_at"], j["started_at"]) for r in rs for j in r["jobs"] if _ref_ran(j)]
    ok = [r for r in rs if r["conclusion"] == "success" and r["run_attempt"] == 1
          and all(j["conclusion"] in ("success", "skipped") for j in r["jobs"] if j.get("run_attempt") == 1)]
    walls = []
    for r in ok:
        js = [j for j in r["jobs"] if _ref_ran(j)]
        if js:
            walls.append(metrics.minutes(min(j["created_at"] for j in js), max(j["completed_at"] for j in js)))
    return waits, walls


@given(st.lists(runs, max_size=10))
def test_matches_report_definitions(rs):
    waits = [w for r in rs for w in metrics.job_waits(r)]
    walls = [w for r in rs if metrics.strict_success(r) for w in [metrics.wall(r)] if w is not None]
    assert (waits, walls) == _ref(rs)
