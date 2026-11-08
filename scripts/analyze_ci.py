"""Runner waits and passing-check times for sampled policyengine-us PR runs, before and after.

Input: data/us_pr_runs_sample.csv, data/us_pr_jobs_sample.csv and data/us_pr_frame_daily.csv
(scripts/collect_us_pr_ci.py). Definitions live in scripts/metrics.py:
- job wait: started_at - created_at, attempt-one jobs that got a runner;
- passing-check time: for strict attempt-one successes (run conclusion success on attempt 1,
  every attempt-one job success or skipped), first job created to last job completed.
Intervals: 95% percentile bootstrap over sampled runs (2,000 draws, seeded), so job waits
inside one run stay together.
Writes data/us_pr_ci_summary.json and prints a table.
"""

import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from metrics import bootstrap_median, job_waits, median, quantile, strict_success, wall  # noqa: E402


def load():
    runs = {}
    for r in csv.DictReader(open(os.path.join(ROOT, "data", "us_pr_runs_sample.csv"))):
        runs[int(r["run_id"])] = {"window": r["window"], "id": int(r["run_id"]), "conclusion": r["conclusion"],
                                  "run_attempt": int(r["run_attempt"]), "created_at": r["created_at"], "jobs": []}
    for j in csv.DictReader(open(os.path.join(ROOT, "data", "us_pr_jobs_sample.csv"))):
        runs[int(j["run_id"])]["jobs"].append({
            "name": j["job"], "status": j["job_status"], "conclusion": j["job_conclusion"] or None,
            "run_attempt": int(j["job_run_attempt"]) if j["job_run_attempt"] else None,
            "created_at": j["created_at"] or None, "started_at": j["started_at"] or None,
            "completed_at": j["completed_at"] or None, "runner_name": "yes" if j["got_runner"] == "True" else None,
        })
    return list(runs.values())


def frame_summary(window):
    rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "data", "us_pr_frame_daily.csv"))) if r["window"] == window]
    by = collections.Counter()
    for r in rows:
        for k, v in r.items():
            if k.startswith("n_"):
                by[k[2:]] += int(v or 0)
    total = sum(int(r["runs"]) for r in rows)
    return {"days": len(rows), "first_day": rows[0]["day"], "last_day": rows[-1]["day"], "runs": total,
            "by_conclusion": dict(sorted(by.items())),
            "success_or_failure": by["success"] + by["failure"],
            "success_or_failure_per_day": (by["success"] + by["failure"]) / len(rows)}


def window_summary(runs):
    waits_by_run = [job_waits(r) for r in runs]
    waits = [w for ws in waits_by_run for w in ws]
    ok = [r for r in runs if strict_success(r)]
    walls = [w for w in (wall(r) for r in ok) if w is not None]
    return {
        "sampled_runs": len(runs),
        "sampled_runs_by_conclusion": dict(collections.Counter(r["conclusion"] for r in runs)),
        "jobs_with_runner": len(waits),
        "wait_minutes": {"median": median(waits), "median_95ci": bootstrap_median(waits_by_run),
                         "p90": quantile(waits, 0.9), "p99": quantile(waits, 0.99), "max": max(waits) if waits else None,
                         "share_over_5": sum(w > 5 for w in waits) / len(waits) if waits else None,
                         "share_over_30": sum(w > 30 for w in waits) / len(waits) if waits else None},
        "strict_success_runs": len(walls),
        "passing_check_minutes": {"median": median(walls), "median_95ci": bootstrap_median([[w] for w in walls]),
                                  "p25": quantile(walls, 0.25), "p75": quantile(walls, 0.75),
                                  "p90": quantile(walls, 0.9), "min": min(walls) if walls else None,
                                  "max": max(walls) if walls else None},
        "passing_check_minutes_all": sorted(walls),
    }


def main():
    runs = load()
    out = {}
    for name in ("before", "after"):
        out[name] = {"frame": frame_summary(name), **window_summary([r for r in runs if r["window"] == name])}
    b, a = out["before"], out["after"]
    out["ratios"] = {
        "passing_check_median_before_over_after": b["passing_check_minutes"]["median"] / a["passing_check_minutes"]["median"],
        "success_or_failure_runs_per_day_after_over_before": a["frame"]["success_or_failure_per_day"] / b["frame"]["success_or_failure_per_day"],
    }
    json.dump(out, open(os.path.join(ROOT, "data", "us_pr_ci_summary.json"), "w"), indent=1)
    for name in ("before", "after"):
        w = out[name]
        f = w["frame"]
        print(f"{name}: {f['first_day']}..{f['last_day']}  runs listed {f['runs']} {f['by_conclusion']}")
        print(f"  sampled {w['sampled_runs']} {w['sampled_runs_by_conclusion']}, jobs with a runner {w['jobs_with_runner']}")
        wm = w["wait_minutes"]
        print(f"  wait min: median {wm['median']:.2f} (95% CI {wm['median_95ci'][0]:.2f}-{wm['median_95ci'][1]:.2f}) "
              f"p90 {wm['p90']:.2f} p99 {wm['p99']:.2f} max {wm['max']:.2f}  >5 {wm['share_over_5']:.1%}  >30 {wm['share_over_30']:.1%}")
        pc = w["passing_check_minutes"]
        print(f"  passing check min ({w['strict_success_runs']} runs): median {pc['median']:.1f} "
              f"(95% CI {pc['median_95ci'][0]:.1f}-{pc['median_95ci'][1]:.1f}) p25 {pc['p25']:.1f} p75 {pc['p75']:.1f} p90 {pc['p90']:.1f}")
    print("ratios", {k: round(v, 2) for k, v in out["ratios"].items()})


if __name__ == "__main__":
    main()
