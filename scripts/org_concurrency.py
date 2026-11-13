"""Jobs running and waiting across PolicyEngine's busiest CI repositories, minute by minute.

Input: data/raw/org-jobs/jobs-<repo>.jsonl (scripts/collect_org_jobs.py): every job of every run
created from 2026-10-09 through 2026-10-22 (UTC) in 12 repositories. Only standard-pool jobs count.
Other repositories' jobs also count toward GitHub's limit, so the organization ran at least
this many jobs at once.

Definitions (scripts/metrics.py): at each whole minute t, a job runs when started_at <= t <
completed_at and waits when created_at <= t < started_at (or < completed_at when no runner took it).
The wait table groups each job that got a runner by the number of jobs running in the minute
GitHub created it. It leaves out policyengine-us Baseline and Contrib jobs created after
policyengine-us#10231 merged, because that pull request's own caps also held them.

Writes data/pe_org_concurrency_minutes.csv and data/pe_org_concurrency_summary.json.
"""

import csv
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from metrics import in_capped_suite, median, minutes, quantile, standard_pool, sweep, t  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw", "org-jobs")
LO, HI = "2026-10-09T00:00:00Z", "2026-10-23T00:00:00Z"
LIMIT = 60
CAPS_SET = "2026-10-15T16:46:11Z"  # policyengine-us#10231 merged
BINS = [(0, 30), (30, 45), (45, 55), (55, 60), (60, None)]


def load():
    jobs = []
    for path in sorted(glob.glob(os.path.join(RAW, "jobs-*.jsonl"))):
        repo = os.path.basename(path)[5:-6]
        runs = {}
        for line in open(path):
            if line.strip():
                record = json.loads(line)
                runs[record["id"]] = record  # one record per run, even if fetched twice
        for record in runs.values():
            jobs += [dict(j, repo=repo) for j in record["jobs"] if standard_pool(j)]
    return jobs


def intervals(jobs):
    running = [(t(j["started_at"]), t(j["completed_at"])) for j in jobs
               if j.get("runner_name") and j.get("started_at") and j.get("completed_at")]
    waiting = []
    for j in jobs:
        end = j.get("started_at") or j.get("completed_at")
        if j.get("created_at") and end:
            waiting.append((t(j["created_at"]), t(end)))
    return running, waiting


def bin_label(lo, hi):
    return f"{lo} or more" if hi is None else f"{lo} to {hi - 1}"


def wait_by_running(jobs, running, lo):
    groups = {bin_label(*b): [] for b in BINS}
    for j in jobs:
        if not (j.get("runner_name") and j.get("started_at") and j.get("created_at")):
            continue
        created = t(j["created_at"])
        i = int((created - lo).total_seconds() // 60)
        if not 0 <= i < len(running):
            continue
        if j["repo"] == "policyengine-us" and in_capped_suite(j) and created >= t(CAPS_SET):
            continue
        for b_lo, b_hi in BINS:
            if running[i] >= b_lo and (b_hi is None or running[i] < b_hi):
                groups[bin_label(b_lo, b_hi)].append(minutes(j["created_at"], j["started_at"]))
    return {k: {"jobs": len(v), "median_wait_minutes": median(v), "p90_wait_minutes": quantile(v, 0.9),
                "share_over_5_minutes": sum(w > 5 for w in v) / len(v) if v else None} for k, v in groups.items()}


def main():
    jobs = load()
    lo, hi = t(LO), t(HI)
    run_iv, wait_iv = intervals(jobs)
    running, waiting = sweep(run_iv, lo, hi), sweep(wait_iv, lo, hi)
    n = len(running)
    with open(os.path.join(ROOT, "data", "pe_org_concurrency_minutes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["minute_utc", "running", "waiting"])
        for i in range(n):
            w.writerow([(lo + dt.timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%MZ"), running[i], waiting[i]])
    out = {
        "window_utc": [LO, HI], "minutes": n, "repositories": sorted({j["repo"] for j in jobs}),
        "standard_jobs": len(jobs), "limit": LIMIT,
        "running": {"mean": sum(running) / n, "median": median(running), "p90": quantile(running, 0.9),
                    "p99": quantile(running, 0.99), "max": max(running)},
        "minutes_running_at_or_over_limit": sum(r >= LIMIT for r in running),
        "minutes_running_at_limit": sum(r == LIMIT for r in running),
        "minutes_running_over_limit": sum(r > LIMIT for r in running),
        "minutes_running_55_or_more": sum(r >= 55 for r in running),
        "minutes_with_a_job_waiting": sum(q > 0 for q in waiting),
        "wait_by_jobs_running_at_creation": wait_by_running(jobs, running, lo),
    }
    json.dump(out, open(os.path.join(ROOT, "data", "pe_org_concurrency_summary.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
