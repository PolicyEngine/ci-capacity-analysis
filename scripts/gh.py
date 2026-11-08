"""Thin read-only wrappers around `gh api` (REST GET and GraphQL queries only)."""

import json
import subprocess
import time


NETWORK = ("network is unreachable", "tls handshake timeout", "connection reset", "i/o timeout",
           "no such host", "connection refused", "eof", "502", "503", "504")


def rest(path, retries=7, network_retries=25):
    """GET a REST path; returns parsed JSON. Read-only by construction.

    Rate-limit errors back off a minute per attempt. Connection failures (a flaky network)
    retry up to network_retries times with a capped backoff; other errors retry `retries` times.
    """
    other = net = 0
    while True:
        p = subprocess.run(
            ["gh", "api", "-X", "GET", path], capture_output=True, text=True
        )
        if p.returncode == 0:
            return json.loads(p.stdout) if p.stdout.strip() else None
        err = p.stderr
        low = err.lower()
        if "rate limit" in low or "secondary" in low:
            other += 1
            if other > retries:
                break
            time.sleep(60 * other)
            continue
        if "404" in err or "Not Found" in err:
            return None
        if any(k in low for k in NETWORK):
            net += 1
            if net > network_retries:
                break
            time.sleep(min(4 * net, 30))
            continue
        other += 1
        if other > retries:
            break
        time.sleep(3 * other)
    raise RuntimeError(f"gh api failed for {path}: {err[:300]}")


def graphql(query, retries=4, **variables):
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is None:
            continue
        flag = "-F" if isinstance(v, (int, bool)) else "-f"
        args += [flag, f"{k}={v}"]
    for attempt in range(retries):
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode == 0:
            return json.loads(p.stdout)
        err = p.stderr + p.stdout[:300]
        if "rate limit" in err.lower() or "secondary" in err.lower():
            time.sleep(60 * (attempt + 1))
            continue
        time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"graphql failed: {err[:400]}")


def core_remaining():
    d = rest("rate_limit")
    return d["resources"]["core"]["remaining"], d["resources"]["graphql"]["remaining"]
