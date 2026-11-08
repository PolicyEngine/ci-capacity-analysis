"""Draw the two figures as SVG, then rasterize them to 1600x900 PNG with rsvg-convert.

figures/merged_prs_per_month: stacked columns of merged PRs per month by org, October 2025
  to October 2026 (data/merged_prs_monthly.csv; the partial November row is left out).
figures/us_pr_check_time: one dot per sampled passing policyengine-us PR run, by window,
  on one hours axis, jittered vertically by a seeded generator, with each window's median
  marked (data/us_pr_ci_summary.json). Dots take a 1 px surface ring rather than 2 px, since the
  after-window cluster packs over a hundred dots into about 50 px.
Colors and marks follow the dataviz reference palette (light surface): categorical slots
1 and 2 for the two orgs; two steps of the blue ramp for before and after.
"""

import csv
import json
import os
import random
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIG = os.path.join(ROOT, "figures")

SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
PE, AXIOM = "#2a78d6", "#eb6834"
BEFORE, AFTER = "#86b6ef", "#2a78d6"
FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"
W, H = 800, 450
MONTH_NAMES = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def text(x, y, s, size=12, fill=INK_2, anchor="start", weight=None, halo=False):
    extra = f' font-weight="{weight}"' if weight else ""
    if halo:
        extra += f' stroke="{SURFACE}" stroke-width="5" stroke-linejoin="round" paint-order="stroke"'
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{extra}>{s}</text>'


def header(title, subtitle):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">',
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        text(24, 40, title, size=20, fill=INK, weight=600),
        text(24, 62, subtitle, size=13),
    ]


def column(x, y_top, y_bottom, bar, fill, rounded, radius=4):
    if not rounded:
        return f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{bar}" height="{y_bottom - y_top:.1f}" fill="{fill}"/>'
    r = min(radius, y_bottom - y_top)
    return (f'<path d="M{x:.1f},{y_bottom:.1f} L{x:.1f},{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} '
            f'L{x + bar - r:.1f},{y_top:.1f} Q{x + bar:.1f},{y_top:.1f} {x + bar:.1f},{y_top + r:.1f} '
            f'L{x + bar:.1f},{y_bottom:.1f} Z" fill="{fill}"/>')


def merged_prs():
    rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "data", "merged_prs_monthly.csv"))) if r["partial"] == "False"]
    import datetime as dt
    day = dt.date.fromisoformat(open(os.path.join(ROOT, "data", "merged_prs_fetched_at.txt")).read().strip()[:10])
    fetched = f"{MONTH_NAMES[day.month - 1]} {day.day}, {day.year}"
    left, right, top, bottom, bar, gap = 60, 776, 124, 372, 24, 2
    y_max = 4000
    ys = lambda v: bottom - (bottom - top) * v / y_max  # noqa: E731
    out = header("Merged pull requests per month", "PolicyEngine and Axiom on GitHub, October 2025 to October 2026")
    lx, ly = 24, 88
    out += [f'<rect x="{lx}" y="{ly - 9}" width="10" height="10" rx="2" fill="{PE}"/>', text(lx + 16, ly, "PolicyEngine"),
            f'<rect x="{lx + 104}" y="{ly - 9}" width="10" height="10" rx="2" fill="{AXIOM}"/>', text(lx + 120, ly, "Axiom")]
    for tick in (1000, 2000, 3000, 4000):
        out.append(f'<line x1="{left}" x2="{right}" y1="{ys(tick):.1f}" y2="{ys(tick):.1f}" stroke="{GRID}" stroke-width="1"/>')
    for tick in (0, 1000, 2000, 3000, 4000):
        out.append(text(left - 8, ys(tick) + 4, f"{tick:,}", fill=MUTED, anchor="end"))
    slot = (right - left) / len(rows)
    totals = [int(r["PolicyEngine_all"]) + int(r["TheAxiomFoundation_all"]) for r in rows]
    peak = max(range(len(rows)), key=lambda i: totals[i])
    labeled = {0, peak, len(rows) - 1}
    for i, r in enumerate(rows):
        cx = left + slot * (i + 0.5)
        pe, ax = int(r["PolicyEngine_all"]), int(r["TheAxiomFoundation_all"])
        x = cx - bar / 2
        draw_ax = (bottom - top) * ax / y_max >= 1.5  # a month with one or three Axiom PRs has no drawable body
        out.append(column(x, ys(pe), bottom, bar, PE, rounded=not draw_ax))
        if draw_ax:
            y_b = ys(pe) - gap if (bottom - top) * ax / y_max >= 6 else ys(pe) - 1
            out.append(column(x, ys(pe + ax), y_b, bar, AXIOM, rounded=True))
        if i in labeled:
            out.append(text(cx, ys(pe + ax) - 8, f"{pe + ax:,}", size=13, fill=INK, anchor="middle", weight=600, halo=True))
        y, m = map(int, r["month"].split("-"))
        out.append(text(cx, bottom + 20, MONTH_NAMES[m - 1], anchor="middle"))
        if i == 0 or m == 1:
            out.append(text(cx, bottom + 36, str(y), fill=MUTED, anchor="middle"))
    out.append(f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}" stroke-width="1"/>')
    out.append(text(24, H - 18, f"Source: GitHub search, org:&lt;org&gt; is:pr is:merged, by month merged, counted {fetched}. "
                    "github.com/PolicyEngine/ci-capacity-analysis", size=11, fill=MUTED))
    out.append("</svg>")
    return "\n".join(out)


def check_time():
    s = json.load(open(os.path.join(ROOT, "data", "us_pr_ci_summary.json")))
    left, right, top = 236, 776, 120
    row_h, x_max_h = 104, 7
    xs = lambda m: left + (right - left) * min(m / 60, x_max_h) / x_max_h  # noqa: E731
    out = header("Time for a pull request to pass its checks",
                 "PolicyEngine's US model (policyengine-us): one dot per sampled run that passed, first job queued to last job done")
    for hour in range(0, x_max_h + 1):
        x = xs(hour * 60)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{top + 2 * row_h - 6}" stroke="{GRID}" stroke-width="1"/>')
        out.append(text(x, top + 2 * row_h + 12, f"{hour} h" if hour else "0", fill=MUTED, anchor="middle"))
    rows = [("before", BEFORE, "Oct 9–22", "GitHub Team, 60 jobs at once"),
            ("after", AFTER, "Oct 25–Nov 7", "GitHub Enterprise, 500 jobs at once")]
    for k, (name, color, dates, plan) in enumerate(rows):
        w = s[name]
        cy = top + row_h * k + row_h / 2 - 6
        out.append(text(24, cy - 2, dates, size=13, fill=INK, weight=600))
        out.append(text(24, cy + 16, plan, size=11))
        rng = random.Random(f"jitter|{name}")
        for m in w["passing_check_minutes_all"]:
            out.append(f'<circle cx="{xs(m):.1f}" cy="{cy + rng.uniform(-22, 22):.1f}" r="4" fill="{color}" '
                       f'stroke="{SURFACE}" stroke-width="1"/>')
        med = w["passing_check_minutes"]["median"]
        mx = xs(med)
        out.append(f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="{cy - 32:.1f}" y2="{cy + 32:.1f}" stroke="{INK}" stroke-width="2"/>')
        out.append(text(mx, cy - 40, f"median {med / 60:.1f} h", size=13, fill=INK, anchor="middle", weight=600, halo=True))
    over = sum(1 for n in ("before", "after") for m in s[n]["passing_check_minutes_all"] if m > x_max_h * 60)
    edge = f" {over} run{'s' if over != 1 else ''} over {x_max_h} hours sit{'' if over != 1 else 's'} at the right edge." if over else ""
    notes = [
        f"Sample: {s['before']['strict_success_runs']} and {s['after']['strict_success_runs']} runs that passed on the first try, "
        f"from 200 random completed runs per window.{edge}",
        "On Oct 23 and 24, we also started running more test jobs at once (policyengine-us#10416 and #10439).",
        "Source: GitHub Actions API. github.com/PolicyEngine/ci-capacity-analysis",
    ]
    for i, n in enumerate(notes):
        out.append(text(24, H - 50 + 16 * i, n, size=11, fill=MUTED))
    out.append("</svg>")
    return "\n".join(out)


def save(name, svg):
    path = os.path.join(FIG, f"{name}.svg")
    open(path, "w", encoding="utf-8").write(svg)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", "1600", "-h", "900", path, "-o", os.path.join(FIG, f"{name}.png")], check=True)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(FIG, exist_ok=True)
    save("merged_prs_per_month", merged_prs())
    if os.path.exists(os.path.join(ROOT, "data", "us_pr_ci_summary.json")):
        save("us_pr_check_time", check_time())
