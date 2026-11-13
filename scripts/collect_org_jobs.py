"""Pull every Actions run, and every job of each run that started, for PolicyEngine's busiest CI repositories.

Window: runs created 2026-10-09 through 2026-10-22 (UTC), the two weeks before the organization
left GitHub Team. Read-only REST GETs through an authenticated `gh`; every repository is public.
Writes, resumably, one line per run to data/raw/org-jobs/jobs-<repo>.jsonl:
  {"id": run id, "created_at": ..., "jobs": [every attempt's jobs]}
A rerun skips runs already saved. Runs GitHub skipped hold no jobs and get no line.
Usage: collect_org_jobs.py [repo ...]   (default: every repository in REPOS)
"""

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gh import core_remaining, rest  # noqa: E402

ORG = "PolicyEngine"
REPOS = [
    "chronicle", "microcosm", "microcosm-dynamics", "policyengine-api", "policyengine-core",
    "policyengine-scorecard", "policyengine-taxsim", "policyengine-uk", "policyengine-uk-data",
    "policyengine-us", "policyengine.py", "uk-autumn-budget-dashboard-2026",
]
FIRST, DAYS = dt.date(2026, 10, 9), 14
RAW = os.path.join(ROOT, "data", "raw", "org-jobs")
FLOOR = 1500  # leave the shared token this many core requests
KEEP = ("id", "name", "status", "conclusion", "created_at", "started_at", "completed_at", "run_attempt",
        "runner_name", "runner_group_name", "labels")


def runs_on(repo, day):
    out, page = [], 1
    while True:
        batch = (rest(f"repos/{ORG}/{repo}/actions/runs?created={day}&per_page=100&page={page}") or {}).get("workflow_runs", [])
        out += [{"id": r["id"], "created_at": r["created_at"], "conclusion": r["conclusion"]} for r in batch]
        if len(batch) < 100:
            return out
        page += 1


def jobs_of(repo, run_id):
    out, page = [], 1
    while True:
        batch = (rest(f"repos/{ORG}/{repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100&page={page}") or {}).get("jobs", [])
        out += [{k: j.get(k) for k in KEEP} for j in batch]
        if len(batch) < 100:
            return out
        page += 1


def saved_ids(path):
    if not os.path.exists(path):
        return set()
    return {json.loads(line)["id"] for line in open(path) if line.strip()}


def main():
    os.makedirs(RAW, exist_ok=True)
    for repo in sys.argv[1:] or REPOS:
        path = os.path.join(RAW, f"jobs-{repo}.jsonl")
        have, added = saved_ids(path), 0
        for k in range(DAYS):
            day = (FIRST + dt.timedelta(k)).isoformat()
            for run in runs_on(repo, day):
                if run["id"] in have or run["conclusion"] == "skipped":
                    continue
                if added % 50 == 0 and core_remaining()[0] < FLOOR:
                    sys.exit(f"stopping: fewer than {FLOOR} core requests left; rerun later")
                record = {"id": run["id"], "created_at": run["created_at"], "jobs": jobs_of(repo, run["id"])}
                with open(path, "a") as f:
                    f.write(json.dumps(record) + "\n")
                have.add(run["id"])
                added += 1
        print(f"{repo}: {len(have)} runs saved ({added} new)", flush=True)


if __name__ == "__main__":
    main()
