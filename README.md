# CI capacity analysis

PolicyEngine and Axiom merged 3,399 pull requests in October 2026, 16 times as many as in October 2025. This repository counts those merges. It also measures how long checks on pull requests to PolicyEngine's US model ([policyengine-us](https://github.com/PolicyEngine/policyengine-us)) took to pass in the two weeks before and the two weeks after PolicyEngine moved from GitHub Team to GitHub Enterprise Cloud on October 23, 2026, and it counts how often the organization ran at the Team plan's 60-job limit.

## Merged pull requests

<img src="figures/merged_prs_per_month.png" alt="Merged pull requests per month" width="560">

| Month | PolicyEngine | Axiom | Both |
|---|---:|---:|---:|
| October 2025 | 212 | 0 | 212 |
| July 2026 | 1,496 | 2,134 | 3,630 |
| August 2026 | 773 | 703 | 1,476 |
| September 2026 | 995 | 733 | 1,728 |
| October 2026 | 2,454 | 945 | 3,399 |

[`data/merged_prs_monthly.csv`](data/merged_prs_monthly.csv) has every month from October 2025, plus November 1–7, 2026. GitHub's search API (`org:<org> is:pr is:merged merged:<first>..<last>`) supplies the counts, which cover every repository in each organization today, private ones included. The `_public` columns hold the counts anyone can reproduce without access to the organizations.

## Pull request checks on policyengine-us

<img src="figures/us_pr_check_time.png" alt="Time for pull request checks to pass" width="560">

| | Oct 9–22, GitHub Team | Oct 25–Nov 7, GitHub Enterprise |
|---|---:|---:|
| Jobs GitHub runs at once for the organization | 60 | 500 |
| Pull request runs created in the window, with skipped drafts and cancelled runs | 1,381 | 1,214 |
| Runs created in the window that ended in success or failure | 522 (37.3 a day) | 712 (50.9 a day) |
| Sampled runs | 200 | 200 |
| Job wait for a runner, median (95% interval) | 22.0 min (15.7–26.8) | 3 s (3–3) |
| Job wait, 90th percentile / longest | 85.9 / 189.6 min | 4 s / 5.8 min |
| Jobs that waited over 5 minutes | 67.6% | 0.1% |
| Sampled runs that passed on the first try | 133 | 165 |
| Time to pass, median (95% interval) | 141 min (126–156) | 66 min (64–67) |
| Time to pass, 25th–75th percentile | 111–218 min | 63–71 min |

Three changes separate the windows, and this analysis doesn't split the gain among them:

- When PolicyEngine moved to Enterprise Cloud, GitHub raised its limit from 60 to 500 jobs at once on standard runners ([GitHub's Actions limits](https://docs.github.com/en/actions/reference/limits)). The organization's plan first read `enterprise` at 16:25 UTC on October 23.
- In [policyengine-us#10416](https://github.com/PolicyEngine/policyengine-us/pull/10416), merged at 22:05 UTC on October 23, Ziming Hua removed caps that held each pull request's Baseline and Contrib test suites to six jobs at a time. He had added them on October 15, in [policyengine-us#10231](https://github.com/PolicyEngine/policyengine-us/pull/10231), to share the organization's 60 runners among pull requests.
- In [policyengine-us#10439](https://github.com/PolicyEngine/policyengine-us/pull/10439), merged at 01:30 UTC on October 24, he moved the Rest Python tests, the longest path through CI, from two runners in sequence to parallel shards that a planning job balances from recent test timings. Those tests used more runner time afterward, a median 177 runner-minutes a run against 99, and finished sooner because the shards ran side by side.

The comparison leaves out October 23 and 24.

The caps did not cover the other jobs, which also waited. Before the caps, Baseline and Contrib jobs already waited a median 18.7 minutes:

| Job wait for a runner, median (90th percentile) | Baseline and Contrib jobs | Every other job |
|---|---:|---:|
| Oct 9–22, 110 runs created before #10231 merged | 18.7 min (89.5) | 4.2 min (56.8) |
| Oct 9–22, 90 runs created after it merged | 34.6 min (98.4) | 11.3 min (45.1) |
| Oct 25–Nov 7, 200 runs | 3 s (4 s) | 3 s (4 s) |

## The 60-job limit

GitHub's limits page gives an organization on the Team plan 60 jobs at once on standard GitHub-hosted runners, across all of its repositories. [`scripts/org_concurrency.py`](scripts/org_concurrency.py) counts the jobs running and waiting in each minute from October 9 to 22 in 12 PolicyEngine repositories. Runs created there in those two weeks started 57,357 jobs on standard runners. Jobs in other repositories, and in runs created before October 9, count toward the limit too, so the organization ran at least this many at once.

- Those repositories ran 60 jobs at once in 4,025 of the 20,160 minutes (67 hours), and 55 or more in 9,842 (49%).
- The count never passed 60, apart from two minutes at 61.
- At least one job waited to start in 12,156 minutes (60%).

Jobs started within seconds while fewer than 45 were running, and most waited once 55 or more were:

| Jobs running at the second GitHub created the job | Jobs | Median wait | Waited over 5 minutes |
|---|---:|---:|---:|
| Fewer than 30 | 8,119 | 2 s | 3% |
| 30 to 44 | 7,840 | 2 s | 3% |
| 45 to 54 | 6,370 | 9 s | 27% |
| 55 to 59 | 25,765 | 23.2 min | 80% |
| 60 or more | 4,264 | 27.4 min | 82% |

The table leaves out policyengine-us's Baseline and Contrib jobs created after #10231 merged, since its caps held those jobs too. When someone re-runs part of a run, GitHub lists the jobs the new attempt carries over a second time, and the script counts each of them once. [`data/pe_org_executions.csv.gz`](data/pe_org_executions.csv.gz) holds each job's times, and [`data/pe_org_concurrency_minutes.csv`](data/pe_org_concurrency_minutes.csv) the minute-by-minute counts.

## Definitions

[`scripts/metrics.py`](scripts/metrics.py) holds every definition, and the property-based tests in [`tests/`](tests) check them.

- The population covers runs of `.github/workflows/pr.yaml` on `pull_request` events that completed as success or failure. A seeded generator draws 200 of them per window. Cancelled runs (usually a newer push replacing an older one) and skipped runs (draft pull requests) stay out of the sample; [`data/us_pr_frame_daily.csv`](data/us_pr_frame_daily.csv) counts them by day.
- A job's wait runs from GitHub creating the job to a runner starting it, for first-attempt jobs that got a runner. Until #10416, this wait includes the time a capped suite's later jobs spent held behind its six-job cap, as well as waits for a runner.
- A run's time to pass runs from its first job's creation to its last job's completion, for runs that succeeded on the first attempt with every job passing or skipped.
- A job runs in a minute when a runner had started it and not yet finished it. It waits when GitHub had created it and no runner had started it. Only jobs for standard GitHub-hosted runners count, each execution once.
- A percentile bootstrap that resamples runs (2,000 draws) gives the 95% intervals, so the jobs of one run stay together.

## Reproduce

Each script makes read-only GitHub API calls through an authenticated [`gh`](https://cli.github.com/) CLI. A rerun reuses whatever an interrupted pull already saved in `data/raw/`, which git ignores.

```bash
python3 scripts/merged_prs.py        # data/merged_prs_monthly.csv
python3 scripts/collect_us_pr_ci.py  # data/us_pr_*_sample.csv, data/us_pr_frame_daily.csv
python3 scripts/analyze_ci.py        # data/us_pr_ci_summary.json
python3 scripts/collect_org_jobs.py  # data/raw/org-jobs/ (about 10,000 requests)
python3 scripts/org_concurrency.py   # data/pe_org_executions.csv.gz, data/pe_org_concurrency_*
python3 scripts/charts.py            # figures/*.svg and *.png (rsvg-convert for the PNGs)
uv run --with pytest --with hypothesis python -m pytest -q tests
```

Code: MIT. Text, data and figures: CC BY 4.0.
