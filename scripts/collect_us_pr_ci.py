"""Sample policyengine-us pull-request CI runs from two weeks before and two weeks after the
GitHub Enterprise upgrade. Read-only GitHub REST calls through `gh api`.

Windows, UTC dates inclusive:
- before: 2026-10-09 to 2026-10-22, on GitHub Team (60 concurrent standard-runner jobs per org)
- after:  2026-10-25 to 2026-11-07, on GitHub Enterprise Cloud (500), after the org plan
          changed (first read as enterprise at 2026-10-23T16:25Z) and after policyengine-us#10439
          split the Rest Python tests over parallel shards (merged 2026-10-24T01:30Z)
The two days between are left out as the changeover.

Frame: runs of .github/workflows/pr.yaml on pull_request events. Every listed run is saved
with its conclusion, so cancelled and skipped runs are counted but never sampled.
Sample: 200 completed runs per window whose conclusion is success or failure, drawn without
replacement by a seeded generator; each sampled run's jobs (all attempts) are fetched.
Writes data/raw/frame-<window>.jsonl, data/raw/jobs/<run id>.json and data/raw/sample-<window>.jsonl,
then data/us_pr_runs_sample.csv (one row per sampled run), data/us_pr_jobs_sample.csv (one row per
job of a sampled run) and data/us_pr_frame_daily.csv (runs listed per day, by conclusion).
Reruns reuse the saved frames and fetched jobs, so an interrupted pull resumes where it stopped.
"""

import csv
import datetime as dt
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gh import rest  # noqa: E402

REPO = "PolicyEngine/policyengine-us"
WINDOWS = {"before": (dt.date(2026, 10, 9), 14), "after": (dt.date(2026, 10, 25), 14)}
SAMPLE = 200
RUN_FIELDS = ("id", "name", "event", "status", "conclusion", "run_attempt", "created_at", "updated_at", "head_sha")
JOB_FIELDS = ("name", "status", "conclusion", "created_at", "started_at", "completed_at", "run_attempt", "runner_name")


def days(start, n):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def runs_on(day):
    out, page = [], 1
    while True:
        r = rest(
            f"repos/{REPO}/actions/workflows/pr.yaml/runs?created={day}&event=pull_request&per_page=100&page={page}"
        )
        runs = (r or {}).get("workflow_runs", [])
        out += [{k: x.get(k) for k in RUN_FIELDS} for x in runs]
        if len(runs) < 100:
            return out
        if page >= 10:
            raise RuntimeError(f"{day}: over 1,000 runs; the listing would be truncated")
        page += 1


def jobs_for(run_id):
    jobs, page = [], 1
    while True:
        r = rest(f"repos/{REPO}/actions/runs/{run_id}/jobs?filter=all&per_page=100&page={page}")
        got = (r or {}).get("jobs", [])
        jobs += [{k: j.get(k) for k in JOB_FIELDS} for j in got]
        if len(got) < 100:
            return jobs
        page += 1


def cached_frame(raw, name, start, n):
    """List the window's runs once; later runs of this script reuse the saved frame."""
    path = os.path.join(raw, f"frame-{name}.jsonl")
    if os.path.exists(path):
        return [json.loads(line) for line in open(path)]
    with ThreadPoolExecutor(4) as ex:
        per_day = list(ex.map(runs_on, days(start, n)))
    frame = [r for d in per_day for r in d]
    with open(path, "w") as f:
        for r in frame:
            f.write(json.dumps(r) + "\n")
    return frame


def cached_jobs(raw, run_id):
    """Fetch a run's jobs once; a failed fetch returns None and a rerun retries it."""
    path = os.path.join(raw, "jobs", f"{run_id}.json")
    if os.path.exists(path):
        return json.load(open(path))
    try:
        jobs = jobs_for(run_id)
    except RuntimeError:
        return None
    with open(path, "w") as f:
        json.dump(jobs, f)
    return jobs


def main():
    raw = os.path.join(ROOT, "data", "raw")
    os.makedirs(os.path.join(raw, "jobs"), exist_ok=True)
    daily, run_rows, job_rows, missing = [], [], [], []
    for name, (start, n) in WINDOWS.items():
        frame = cached_frame(raw, name, start, n)
        for day in days(start, n):
            d = [r for r in frame if r["created_at"][:10] == day]
            c = {}
            for r in d:
                key = r["conclusion"] if r["status"] == "completed" else f"status:{r['status']}"
                c[key] = c.get(key, 0) + 1
            daily.append({"window": name, "day": day, "runs": len(d), **{f"n_{k}": v for k, v in sorted(c.items())}})
        eligible = sorted(
            (r for r in frame if r["status"] == "completed" and r["conclusion"] in ("success", "failure")),
            key=lambda r: r["id"],
        )
        rng = random.Random(f"ci-capacity-analysis|{REPO}|pr.yaml|{name}")
        sample = rng.sample(eligible, min(SAMPLE, len(eligible)))
        with ThreadPoolExecutor(4) as ex:
            for r, js in zip(sample, ex.map(lambda r: cached_jobs(raw, r["id"]), sample)):
                r["jobs"] = js
        missing += [r["id"] for r in sample if r["jobs"] is None]
        with open(os.path.join(raw, f"sample-{name}.jsonl"), "w") as f:
            for r in sample:
                f.write(json.dumps(r) + "\n")
        for r in sample:
            run_rows.append({"window": name, "run_id": r["id"], "conclusion": r["conclusion"],
                             "run_attempt": r["run_attempt"], "created_at": r["created_at"],
                             "jobs": len(r["jobs"] or [])})
            for j in r["jobs"] or []:
                job_rows.append(
                    {"window": name, "run_id": r["id"], "run_conclusion": r["conclusion"], "run_attempt": r["run_attempt"],
                     "run_created_at": r["created_at"], "job": j["name"], "job_status": j["status"],
                     "job_conclusion": j["conclusion"], "job_run_attempt": j["run_attempt"],
                     "created_at": j["created_at"], "started_at": j["started_at"], "completed_at": j["completed_at"],
                     "got_runner": bool(j["runner_name"])}
                )
        print(name, "frame", len(frame), "eligible", len(eligible), "sampled", len(sample), flush=True)
    if missing:
        sys.exit(f"{len(missing)} sampled runs have no jobs yet ({missing[:5]}...); rerun to retry them")
    keys = sorted({k for row in daily for k in row}, key=lambda k: (k not in ("window", "day", "runs"), k))
    with open(os.path.join(ROOT, "data", "us_pr_frame_daily.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval=0)
        w.writeheader()
        w.writerows(daily)
    with open(os.path.join(ROOT, "data", "us_pr_runs_sample.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["window", "run_id", "conclusion", "run_attempt", "created_at", "jobs"])
        w.writeheader()
        w.writerows(run_rows)
    with open(os.path.join(ROOT, "data", "us_pr_jobs_sample.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(job_rows[0]))
        w.writeheader()
        w.writerows(job_rows)
    with open(os.path.join(ROOT, "data", "us_pr_fetched_at.txt"), "w") as f:
        f.write(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    print("COLLECT_DONE", len(job_rows), "jobs")


if __name__ == "__main__":
    main()
