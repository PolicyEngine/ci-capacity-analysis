"""Pure metric definitions shared by the CI analysis and its tests.

All times are ISO 8601 strings from the GitHub Actions REST API, in UTC.
- job wait: started_at - created_at, for attempt-one jobs that got a runner;
- strict success: run conclusion success on attempt 1, every attempt-one job success or skipped;
- run wall time: last attempt-one job completed_at - first attempt-one job created_at,
  over jobs that got a runner;
- capped suites: the Baseline and Contrib matrix jobs. policyengine-us#10231 let each of those
  suites run at most six jobs at a time from 2026-10-15T16:46Z, until #10416 removed the caps
  at 2026-10-23T22:05Z;
- standard pool: jobs with a standard GitHub-hosted label (such as ubuntu-latest or
  ubuntu-24.04-arm), in GitHub's own runner group and not self-hosted. GitHub's plan limit
  counts these across the organization;
- execution: one run of a job on a runner. A re-run attempt lists the jobs it carries over
  again, and those copies count once;
- concurrency: at each whole minute t, a job runs when started_at <= t < completed_at and waits
  when created_at <= t < started_at (or < completed_at when it never got a runner).
"""

import bisect
import datetime as dt
import math
import random
import re
import statistics as st


def t(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def minutes(a, b):
    return (t(b) - t(a)).total_seconds() / 60


def ran(job):
    """An attempt-one job that got a runner and finished."""
    return bool(
        job.get("runner_name") and job.get("started_at") and job.get("completed_at") and job.get("run_attempt") == 1
    )


def job_waits(run, keep=None):
    """Waits in minutes of the run's attempt-one jobs that got a runner; keep(job) narrows the jobs."""
    return [
        minutes(j["created_at"], j["started_at"])
        for j in run.get("jobs") or []
        if ran(j) and (keep is None or keep(j))
    ]


CAPPED_SUITES = ("Baseline tests", "Contrib tests")


def in_capped_suite(job):
    return (job.get("name") or "").startswith(CAPPED_SUITES)


def strict_success(run):
    jobs = [j for j in run.get("jobs") or [] if j.get("run_attempt") == 1]
    return (
        run.get("conclusion") == "success"
        and run.get("run_attempt") == 1
        and bool(jobs)
        and all(j.get("conclusion") in ("success", "skipped") for j in jobs)
    )


def wall(run):
    """Run wall time in minutes, or None when no attempt-one job got a runner."""
    js = [j for j in run.get("jobs") or [] if ran(j)]
    if not js:
        return None
    return minutes(min(j["created_at"] for j in js), max(j["completed_at"] for j in js))


def quantile(xs, p):
    """Nearest-rank quantile: the smallest value with at least a share p of the values at or below it."""
    xs = sorted(xs)
    if not xs:
        return None
    return xs[max(0, math.ceil(p * len(xs) - 1e-9) - 1)]


def median(xs):
    return st.median(xs) if xs else None


def bootstrap_median(groups, reps=2000, seed="ci-capacity-analysis", level=0.95):
    """Percentile bootstrap interval for the median of the pooled values, resampling groups (runs).

    groups: list of lists; each inner list holds one run's values (one value for wall time,
    many for job waits), so the interval respects clustering within runs.
    """
    groups = [g for g in groups if g]
    if not groups:
        return None
    rng = random.Random(seed)
    meds = []
    for _ in range(reps):
        pooled = [x for _ in groups for x in groups[rng.randrange(len(groups))]]
        meds.append(st.median(pooled))
    meds.sort()
    lo = meds[int((1 - level) / 2 * reps)]
    hi = meds[min(reps - 1, int((1 + level) / 2 * reps))]
    return lo, hi


STANDARD_LABEL = re.compile(r"^(ubuntu|windows|macos)-(latest|\d+(\.\d+)?)(-arm)?$")
GITHUB_GROUPS = ("", "github actions")


def standard_pool(job):
    """A job for a standard GitHub-hosted runner: a standard label, in GitHub's own runner group."""
    labels = job.get("labels") or []
    group = (job.get("runner_group_name") or "").lower()
    if "self-hosted" in labels or group not in GITHUB_GROUPS:
        return False
    return any(STANDARD_LABEL.match(label) for label in labels)


def executions(jobs):
    """One record per execution.

    When someone re-runs part of a run, GitHub lists each job the new attempt carries over again:
    a new job id and a later created_at, with the first execution's runner, started_at and
    completed_at. Those records describe one execution, so jobs that share a repository, run,
    name, runner and start and completion times collapse into one, which keeps the earliest
    created_at. A job that ran again has its own times and stays. Jobs no runner took pass through.
    """
    kept, out = {}, []
    for j in jobs:
        if not (j.get("runner_name") and j.get("started_at")):
            out.append(j)
            continue
        key = (j.get("repo"), j.get("run_id"), j.get("name"), j["runner_name"], j["started_at"], j.get("completed_at"))
        first = kept.get(key)
        if first is None:
            kept[key] = j
            out.append(j)
        elif (j.get("created_at") or "") < (first.get("created_at") or ""):
            first["created_at"] = j["created_at"]
    return out


def running_at(starts, ends, when):
    """Executions with started <= when < completed, from sorted lists of start and completion times."""
    return bisect.bisect_right(starts, when) - bisect.bisect_right(ends, when)


def sweep(intervals, lo, hi):
    """Count, at each whole minute t in [lo, hi), the intervals [a, b) with a <= t < b.

    intervals: pairs of datetimes; a pair with a missing end counts nowhere.
    Returns one count per minute, starting at lo.
    """
    n = math.ceil((hi - lo).total_seconds() / 60)
    delta = [0] * (n + 1)
    for a, b in intervals:
        if a is None or b is None or b <= lo or a >= hi:
            continue
        a, b = max(a, lo), min(b, hi)
        i = math.ceil((a - lo).total_seconds() / 60)
        k = math.ceil((b - lo).total_seconds() / 60)
        if k > i:
            delta[i] += 1
            delta[k] -= 1
    out, current = [], 0
    for i in range(n):
        current += delta[i]
        out.append(current)
    return out
