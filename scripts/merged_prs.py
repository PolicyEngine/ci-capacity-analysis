"""Merged pull requests per month in the PolicyEngine and TheAxiomFoundation GitHub orgs.

GitHub search API, `search/issues?q=org:<org> is:pr is:merged merged:<first>..<last>`, field
total_count; the same query with `is:public` gives the share anyone can recount without org
access. Counts run from October 2025 through October 2026, plus November 1-7, 2026 as a
partial month. A search that reports incomplete_results is retried. Each count is cached in
data/raw/search-cache.json, so a rerun after a network failure resumes; delete the cache to recount.
Writes data/merged_prs_monthly.csv and data/merged_prs_fetched_at.txt.
"""

import calendar
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gh import rest  # noqa: E402

ORGS = ("PolicyEngine", "TheAxiomFoundation")
MONTHS = [(2025, m) for m in (10, 11, 12)] + [(2026, m) for m in range(1, 11)]
PARTIAL = ("2026-11", dt.date(2026, 11, 1), dt.date(2026, 11, 7))


CACHE = os.path.join(ROOT, "data", "raw", "search-cache.json")


def count(q):
    """total_count for a search, cached in data/raw so an interrupted run resumes."""
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if q in cache:
        return cache[q]
    for _ in range(5):
        r = rest(f"search/issues?q={urllib.parse.quote(q)}&per_page=1")
        if r and not r.get("incomplete_results"):
            cache[q] = r["total_count"]
            json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)
            time.sleep(2.5)  # the search API allows 30 requests a minute
            return r["total_count"]
        time.sleep(10)
    raise RuntimeError(f"search stayed incomplete: {q}")


def periods():
    for y, m in MONTHS:
        yield f"{y}-{m:02d}", dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1]), False
    label, a, b = PARTIAL
    yield label, a, b, True


def main():
    rows = []
    for label, a, b, partial in periods():
        row = {"month": label, "first_day": a.isoformat(), "last_day": b.isoformat(), "days": (b - a).days + 1,
               "partial": partial}
        for org in ORGS:
            base = f"org:{org} is:pr is:merged merged:{a.isoformat()}..{b.isoformat()}"
            row[f"{org}_all"] = count(base)
            row[f"{org}_public"] = count(base + " is:public")
        row["both_all"] = sum(row[f"{o}_all"] for o in ORGS)
        rows.append(row)
        print(row, flush=True)
    with open(os.path.join(ROOT, "data", "merged_prs_monthly.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(ROOT, "data", "merged_prs_fetched_at.txt"), "w") as f:
        f.write(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")


if __name__ == "__main__":
    main()
