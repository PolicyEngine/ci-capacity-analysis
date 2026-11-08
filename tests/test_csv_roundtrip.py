"""Differential check: the committed CSVs reproduce the waits and wall times computed from the
raw API samples they came from. Skips when data/raw is absent (a fresh clone without a pull)."""

import json
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import analyze_ci  # noqa: E402
import metrics  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")


@pytest.mark.skipif(not os.path.exists(os.path.join(RAW, "sample-after.jsonl")), reason="no raw pull")
def test_csv_matches_raw_samples():
    from_csv = {r["id"]: r for r in analyze_ci.load()}
    for name in ("before", "after"):
        for line in open(os.path.join(RAW, f"sample-{name}.jsonl")):
            raw = json.loads(line)
            got = from_csv[raw["id"]]
            assert got["window"] == name
            assert metrics.job_waits(got) == metrics.job_waits(raw)
            assert metrics.strict_success(got) == metrics.strict_success(raw)
            assert metrics.wall(got) == metrics.wall(raw)
