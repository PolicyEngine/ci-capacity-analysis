# CI capacity analysis

How many pull requests PolicyEngine and Axiom merge each month, and how long a policyengine-us pull request waits for its checks, in the two weeks before and after PolicyEngine moved from GitHub Team to GitHub Enterprise Cloud on October 23, 2026.

Results go here once the pull finishes.

## Reproduce

Each script makes read-only GitHub API calls through an authenticated [`gh`](https://cli.github.com/) CLI.

```bash
python3 scripts/merged_prs.py        # data/merged_prs_monthly.csv
python3 scripts/collect_us_pr_ci.py  # data/us_pr_*_sample.csv, data/us_pr_frame_daily.csv
python3 scripts/analyze_ci.py        # data/us_pr_ci_summary.json
python3 scripts/charts.py            # figures/*.svg and *.png (rsvg-convert for the PNGs)
uv run --with pytest --with hypothesis python -m pytest -q tests
```

Code: MIT. Text, data and figures: CC BY 4.0.
