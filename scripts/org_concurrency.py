"""Jobs running and waiting across PolicyEngine's busiest CI repositories, minute by minute.

Input: data/raw/org-jobs/jobs-<repo>.jsonl (scripts/collect_org_jobs.py): every job of every run
created from 2026-10-09 through 2026-10-22 (UTC) in 12 repositories. When those records are
absent, the script reads the executions it saved from them, data/pe_org_executions.csv.gz.
Only standard-pool executions count, each once (metrics.executions drops the copies a re-run
attempt lists). Other repositories' jobs also count toward GitHub's limit, and so do jobs of
runs created before October 9, so the organization ran at least this many jobs at once.

Definitions (scripts/metrics.py): at each whole minute t, an execution runs when started_at <= t <
completed_at and waits when created_at <= t < started_at (or < completed_at when no runner took it).
The wait table groups each execution that got a runner by the number running at the second
GitHub created its job. It leaves out policyengine-us Baseline and Contrib jobs created after
policyengine-us#10231 merged, because that pull request's own caps also held them.

Writes data/pe_org_executions.csv.gz, data/pe_org_concurrency_minutes.csv and
data/pe_org_concurrency_summary.json.
"""

import csv
import datetime as dt
import glob
import gzip
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from metrics import (  # noqa: E402
    executions,
    in_capped_suite,
    median,
    minutes,
    quantile,
    running_at,
    standard_pool,
    sweep,
    t,
)

RAW = os.path.join(ROOT, "data", "raw", "org-jobs")
SAVED = os.path.join(ROOT, "data", "pe_org_executions.csv.gz")
LO, HI = "2026-10-09T00:00:00Z", "2026-10-23T00:00:00Z"
LIMIT = 60
CAPS_SET = "2026-10-15T16:46:11Z"  # policyengine-us#10231 merged
BINS = [(0, 30), (30, 45), (45, 55), (55, 60), (60, None)]
FIELDS = ["repo", "run_id", "name", "created_at", "started_at", "completed_at", "runner_name"]


def load_raw():
    jobs = []
    for path in sorted(glob.glob(os.path.join(RAW, "jobs-*.jsonl"))):
        repo = os.path.basename(path)[5:-6]
        runs = {}
        for line in open(path):
            if line.strip():
                record = json.loads(line)
                runs[record["id"]] = record  # the latest record per run
        for run_id in sorted(runs):
            jobs += [dict(j, repo=repo, run_id=run_id) for j in runs[run_id]["jobs"] if standard_pool(j)]
    return jobs


def save(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    with open(SAVED, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as z:
        z.write(buffer.getvalue().encode())


def load_saved():
    with gzip.open(SAVED, "rt", newline="") as f:
        return [{k: (v or None) for k, v in row.items()} | {"run_id": int(row["run_id"])} for row in csv.DictReader(f)]


def intervals(rows):
    """Running and waiting intervals. An execution GitHub never gave a completion time counts as
    running nowhere: its record went stale, and the run's later jobs show the runner moved on."""
    running = [(t(j["started_at"]), t(j["completed_at"]))
               for j in rows if j.get("runner_name") and j.get("started_at") and j.get("completed_at")]
    waiting = []
    for j in rows:
        end = j.get("started_at") or j.get("completed_at")
        if j.get("created_at") and end:
            waiting.append((t(j["created_at"]), t(end)))
    return running, waiting


def bin_label(lo, hi):
    return f"{lo} or more" if hi is None else f"{lo} to {hi - 1}"


def wait_by_running(rows, running_iv, lo, hi):
    starts, ends = sorted(a for a, _ in running_iv), sorted(b for _, b in running_iv)
    groups = {bin_label(*b): [] for b in BINS}
    for j in rows:
        if not (j.get("runner_name") and j.get("started_at") and j.get("created_at")):
            continue
        created = t(j["created_at"])
        if not lo <= created < hi:
            continue
        if j["repo"] == "policyengine-us" and in_capped_suite(j) and created >= t(CAPS_SET):
            continue
        count = running_at(starts, ends, created)
        for b_lo, b_hi in BINS:
            if count >= b_lo and (b_hi is None or count < b_hi):
                groups[bin_label(b_lo, b_hi)].append(minutes(j["created_at"], j["started_at"]))
    return {k: {"jobs": len(v), "median_wait_minutes": median(v), "p90_wait_minutes": quantile(v, 0.9),
                "share_over_5_minutes": sum(w > 5 for w in v) / len(v) if v else None} for k, v in groups.items()}


def summarize(rows):
    lo, hi = t(LO), t(HI)
    run_iv, wait_iv = intervals(rows)
    running, waiting = sweep(run_iv, lo, hi), sweep(wait_iv, lo, hi)
    n = len(running)
    ran = [j for j in rows if j.get("runner_name") and j.get("started_at")]
    summary = {
        "window_utc": [LO, HI], "minutes": n, "repositories": sorted({j["repo"] for j in rows}),
        "executions_that_ran": len(ran), "jobs_no_runner_took": len(rows) - len(ran),
        "executions_without_a_completion_time": sum(1 for j in ran if not j.get("completed_at")), "limit": LIMIT,
        "running": {"mean": sum(running) / n, "median": median(running), "p90": quantile(running, 0.9),
                    "p99": quantile(running, 0.99), "max": max(running)},
        "minutes_running_at_or_over_limit": sum(r >= LIMIT for r in running),
        "minutes_running_at_limit": sum(r == LIMIT for r in running),
        "minutes_running_over_limit": sum(r > LIMIT for r in running),
        "minutes_running_55_or_more": sum(r >= 55 for r in running),
        "minutes_with_a_job_waiting": sum(q > 0 for q in waiting),
        "wait_by_jobs_running_at_creation": wait_by_running(rows, run_iv, lo, hi),
    }
    return running, waiting, summary


def main():
    if glob.glob(os.path.join(RAW, "jobs-*.jsonl")):
        jobs = load_raw()
        rows = executions(jobs)
        print(f"{len(jobs)} standard-pool job records, {len(rows)} after dropping {len(jobs) - len(rows)} carried-over copies")
        save(rows)
    rows = load_saved()
    running, waiting, summary = summarize(rows)
    lo = t(LO)
    with open(os.path.join(ROOT, "data", "pe_org_concurrency_minutes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["minute_utc", "running", "waiting"])
        for i in range(len(running)):
            w.writerow([(lo + dt.timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%MZ"), running[i], waiting[i]])
    json.dump(summary, open(os.path.join(ROOT, "data", "pe_org_concurrency_summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
