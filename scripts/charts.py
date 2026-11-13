"""Draw the two figures as SVG, then rasterize them to 1600x1600 PNG with rsvg-convert.

Both figures are square with large type, so their labels stay readable in a phone's feed
(a 390 px wide screen shows them at about half the SVG's size).
figures/merged_prs_per_month: stacked columns of merged PRs per month by org, October 2025
  to October 2026 (data/merged_prs_monthly.csv; the partial November row is left out).
figures/us_pr_check_time: one dot per sampled policyengine-us PR run that passed on the first
  try, by window, on one hours axis, jittered vertically by a seeded generator, with each
  window's median marked (data/us_pr_ci_summary.json).
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
W, H = 800, 800
TITLE, SUB, LABEL, VALUE, SOURCE = 36, 23, 22, 26, 18
MONTH_NAMES = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
REPO_URL = "github.com/PolicyEngine/ci-capacity-analysis"


def text(x, y, s, size=LABEL, fill=INK_2, anchor="start", weight=None, halo=False):
    extra = f' font-weight="{weight}"' if weight else ""
    if halo:
        extra += f' stroke="{SURFACE}" stroke-width="7" stroke-linejoin="round" paint-order="stroke"'
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{extra}>{s}</text>'


def header(title, subtitle):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">',
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        text(32, 64, title, size=TITLE, fill=INK, weight=600),
        text(32, 100, subtitle, size=SUB),
    ]


def footer(first_line):
    return [text(32, H - 58, first_line, size=SOURCE, fill=MUTED), text(32, H - 32, REPO_URL, size=SOURCE, fill=MUTED)]


def column(x, y_top, y_bottom, bar, fill, rounded, radius=5):
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
    left, right, top, bottom, bar, gap = 92, 776, 214, 640, 38, 2
    y_max = 4000
    ys = lambda v: bottom - (bottom - top) * v / y_max  # noqa: E731
    out = header("Merged pull requests per month", "PolicyEngine and Axiom, October 2025 to October 2026")
    lx, ly = 32, 152
    out += [f'<rect x="{lx}" y="{ly - 17}" width="18" height="18" rx="3" fill="{PE}"/>', text(lx + 28, ly, "PolicyEngine"),
            f'<rect x="{lx + 190}" y="{ly - 17}" width="18" height="18" rx="3" fill="{AXIOM}"/>', text(lx + 218, ly, "Axiom")]
    for tick in (1000, 2000, 3000, 4000):
        out.append(f'<line x1="{left}" x2="{right}" y1="{ys(tick):.1f}" y2="{ys(tick):.1f}" stroke="{GRID}" stroke-width="1.5"/>')
    for tick in (0, 1000, 2000, 3000, 4000):
        out.append(text(left - 12, ys(tick) + 7, f"{tick:,}", fill=MUTED, anchor="end", size=20))
    slot = (right - left) / len(rows)
    totals = [int(r["PolicyEngine_all"]) + int(r["TheAxiomFoundation_all"]) for r in rows]
    peak = max(range(len(rows)), key=lambda i: totals[i])
    labeled = {0, peak, len(rows) - 1}
    for i, r in enumerate(rows):
        cx = left + slot * (i + 0.5)
        pe, ax = int(r["PolicyEngine_all"]), int(r["TheAxiomFoundation_all"])
        x = cx - bar / 2
        draw_ax = (bottom - top) * ax / y_max >= 2  # a month with one or three Axiom PRs has no drawable body
        out.append(column(x, ys(pe), bottom, bar, PE, rounded=not draw_ax))
        if draw_ax:
            y_b = ys(pe) - gap if (bottom - top) * ax / y_max >= 8 else ys(pe) - 1
            out.append(column(x, ys(pe + ax), y_b, bar, AXIOM, rounded=True))
        if i in labeled:
            out.append(text(cx, ys(pe + ax) - 12, f"{pe + ax:,}", size=VALUE, fill=INK, anchor="middle", weight=600, halo=True))
        y, m = map(int, r["month"].split("-"))
        out.append(text(cx, bottom + 32, MONTH_NAMES[m - 1], anchor="middle", size=20))
        if i == 0 or m == 1:
            out.append(text(cx, bottom + 58, str(y), fill=MUTED, anchor="middle", size=20))
    out.append(f'<line x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}" stroke-width="1.5"/>')
    out += footer(f"Source: GitHub search, public and private repositories, counted {fetched}")
    out.append("</svg>")
    return "\n".join(out)


def check_time():
    s = json.load(open(os.path.join(ROOT, "data", "us_pr_ci_summary.json")))
    left, right, x_max_h = 44, 756, 7
    xs = lambda m: left + (right - left) * min(m / 60, x_max_h) / x_max_h  # noqa: E731
    out = header("Time for pull request checks to pass",
                 "PolicyEngine's US model. Each dot: one run that passed on the first try.")
    rows = [("before", BEFORE, 306, "Oct 9–22, 2026", "GitHub Team: 60 jobs at once"),
            ("after", AFTER, 572, "Oct 25–Nov 7, 2026", "GitHub Enterprise: 500 at once, our job caps lifted, longest tests split")]
    grid_top, grid_bottom = 246, 640
    for hour in range(0, x_max_h + 1):
        x = xs(hour * 60)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{grid_top}" y2="{grid_bottom}" stroke="{GRID}" stroke-width="1.5"/>')
        out.append(text(x, grid_bottom + 30, f"{hour} h" if hour else "0", fill=MUTED, anchor="middle", size=20))
    for name, color, cy, dates, plan in rows:
        w = s[name]
        out.append(text(32, cy - 138 if name == "before" else cy - 100, dates, size=24, fill=INK, weight=600))
        out.append(text(32, cy - 110 if name == "before" else cy - 72, plan, size=19 if len(plan) > 40 else 21))
        rng = random.Random(f"jitter|{name}")
        for m in w["passing_check_minutes_all"]:
            out.append(f'<circle cx="{xs(m):.1f}" cy="{cy + rng.uniform(-40, 40):.1f}" r="6" fill="{color}" '
                       f'stroke="{SURFACE}" stroke-width="1.5"/>')
        med = w["passing_check_minutes"]["median"]
        mx = xs(med)
        out.append(f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="{cy - 54}" y2="{cy + 54}" stroke="{INK}" stroke-width="3"/>')
        label = f"median {med / 60:.1f} hours" if med >= 90 else f"median {med + 0.5:.0f} minutes"
        if name == "before":
            out.append(text(mx, cy - 64, label, size=VALUE, fill=INK, anchor="middle", weight=600, halo=True))
        else:
            out.append(text(xs(max(w["passing_check_minutes_all"])) + 22, cy + 9, label, size=VALUE, fill=INK, weight=600, halo=True))
    out += footer("Source: GitHub Actions API, 200 random completed runs per period")
    out.append("</svg>")
    return "\n".join(out)


def save(name, svg):
    path = os.path.join(FIG, f"{name}.svg")
    open(path, "w", encoding="utf-8").write(svg)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", "1600", "-h", "1600", path, "-o", os.path.join(FIG, f"{name}.png")], check=True)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(FIG, exist_ok=True)
    save("merged_prs_per_month", merged_prs())
    if os.path.exists(os.path.join(ROOT, "data", "us_pr_ci_summary.json")):
        save("us_pr_check_time", check_time())
