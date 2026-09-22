"""Charts for the report, written as SVG (PDF) and PNG (Markdown, workbook).

Palette: warm paper surface and near-black ink with Jev magenta leading the
categorical order. The categorical order was validated with the dataviz
palette checker (adjacent pairs pass CVD and normal-vision floors; the first
three pass all-pairs). Severity uses the reserved status colours and always
carries a text label. Magnitude uses a single magenta ramp.
"""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Wedge  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

SURFACE = "#fcfcfb"
PANEL = "#f4f3ef"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
MAGENTA = "#d45bb6"
CATEGORICAL = ["#d45bb6", "#1baf7a", "#4a3aa7", "#eb6834", "#2a78d6", "#eda100"]
OTHER = "#c3c2b7"
STATUS = {"critical": "#d03b3b", "high": "#ec835a", "medium": "#fab219", "low": "#8fb3d9", "good": "#0ca30c", "info": "#c3c2b7"}
RAMP = ["#fbeaf5", "#f2c4e4", "#e691cf", "#d45bb6", "#a83a8c", "#6e2059"]
CMAP = LinearSegmentedColormap.from_list("jev", RAMP)
PRIORITY = {"P1": RAMP[5], "P2": RAMP[3], "P3": RAMP[1]}

FONT = "Inter" if any("Inter" == f.name for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
plt.rcParams.update({
    "font.family": FONT,
    "font.size": 9,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "axes.edgecolor": GRID,
    "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "svg.fonttype": "none",
})


def place_labels(ax, fig, items: list[tuple[float, float, str]], fontsize: float = 6.8, limit: int = 12) -> None:
    """Greedy, collision-free labels: try positions around each point in display space;
    skip a label rather than draw it over another label or outside the plot."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axbox = ax.get_window_extent(renderer)
    taken = []
    offsets = [(6, 4, "left", "bottom"), (6, -4, "left", "top"), (-6, 4, "right", "bottom"), (-6, -4, "right", "top"), (0, 9, "center", "bottom"), (0, -9, "center", "top")]
    placed = 0
    for x, y, text in items:
        if placed >= limit:
            break
        for dx, dy, ha, va in offsets:
            t = ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", fontsize=fontsize, ha=ha, va=va, color=INK, zorder=5)
            bb = t.get_window_extent(renderer).expanded(1.08, 1.15)
            inside = axbox.x0 - 2 <= bb.x0 and bb.x1 <= axbox.x1 + 40 and axbox.y0 - 2 <= bb.y0 and bb.y1 <= axbox.y1 + 2
            if inside and not any(bb.overlaps(o) for o in taken):
                taken.append(bb)
                placed += 1
                break
            t.remove()


class ChartSet:
    def __init__(self, out: Path):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.svg: dict[str, str] = {}
        self.png: dict[str, Path] = {}

    def save(self, name: str, fig) -> None:
        buf = io.StringIO()
        fig.savefig(buf, format="svg", bbox_inches="tight", pad_inches=0.05)
        svg = buf.getvalue()
        self.svg[name] = svg[svg.index("<svg"):]
        path = self.out / f"{name}.png"
        fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.05)
        self.png[name] = path
        plt.close(fig)


def _clean(ax, grid_axis: str | None = None):
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5)) if grid_axis == "y" else None
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=6)) if grid_axis == "x" else None
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(length=0)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)


def gauge(cs: ChartSet, value: int, grade: str, partial: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(2.6, 2.6))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(Wedge((0, 0), 1, 0, 360, width=0.16, color=GRID))
    ax.add_patch(Wedge((0, 0), 1, 90 - 360 * value / 100, 90, width=0.16, color=MAGENTA))
    ax.text(0, 0.08, f"{value}", ha="center", va="center", fontsize=40, fontweight="bold", color=INK)
    ax.text(0, -0.38, f"grade {grade}  ·  out of 100", ha="center", va="center", fontsize=8.5, color=INK2)
    if partial:
        ax.text(0, -0.58, "partial audit", ha="center", va="center", fontsize=8.5, fontweight="bold", color=STATUS["critical"])
    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-1.05, 1.05)
    cs.save("gauge", fig)


def category_bars(cs: ChartSet, scores: dict, names: dict) -> None:
    items = list(scores["categories"].items())
    fig, ax = plt.subplots(figsize=(6.4, 0.42 * len(items) + 0.4))
    labels = [names[c] for c, _ in items][::-1]
    vals = [v for _, v in items][::-1]
    for i, v in enumerate(vals):
        ax.barh(i, 100, color=PANEL, height=0.56)
        if v is None:
            ax.text(2, i, "not assessed", va="center", fontsize=8, color=MUTED)
            continue
        ax.barh(i, v, color=CMAP(0.35 + 0.65 * v / 100), height=0.56)
        ax.text(v + 1.5, i, f"{v}", va="center", fontsize=9, fontweight="bold", color=INK)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlim(0, 108)
    ax.set_xticks([0, 25, 50, 75, 100])
    _clean(ax)
    ax.spines["left"].set_visible(False)
    cs.save("categories", fig)


def donut(cs: ChartSet, name: str, counts: list[tuple[str, int]], colors: list[str] | None = None, center: str = "") -> None:
    counts = [(k, v) for k, v in counts if v]
    if not counts:
        return
    if colors is None:
        if len(counts) > len(CATEGORICAL):
            rest = sum(v for _, v in counts[len(CATEGORICAL) - 1 :])
            counts = counts[: len(CATEGORICAL) - 1] + [("other", rest)]
        colors = CATEGORICAL[: len(counts)]
        if counts[-1][0] == "other":
            colors[-1] = OTHER
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    total = sum(v for _, v in counts)
    wedges, _ = ax.pie([v for _, v in counts], colors=colors, startangle=90, counterclock=False, wedgeprops={"width": 0.34, "edgecolor": SURFACE, "linewidth": 2})
    ax.text(0, 0.06, f"{total}", ha="center", va="center", fontsize=18, fontweight="bold")
    ax.text(0, -0.2, center, ha="center", va="center", fontsize=7.5, color=INK2)
    ax.legend(wedges, [f"{k.replace('_', ' ')}  {v}" for k, v in counts], loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=8, handlelength=0.9, handleheight=0.9)
    ax.set_aspect("equal")
    cs.save(name, fig)


def severity_by_category(cs: ChartSet, actions: list[dict], names: dict) -> None:
    sev = ["critical", "high", "medium", "low"]
    cats = [c for c in names if any(a["category"] == c for a in actions)]
    if not cats:
        return
    fig, ax = plt.subplots(figsize=(6.4, 0.42 * len(cats) + 0.7))
    left = [0] * len(cats)
    for s in sev:
        vals = [sum(1 for a in actions if a["category"] == c and a["severity"] == s) for c in cats]
        if not any(vals):
            continue
        ax.barh(range(len(cats)), vals, left=left, color=STATUS[s], height=0.56, label=s, edgecolor=SURFACE, linewidth=1.5)
        left = [l + v for l, v in zip(left, vals)]
    for i, total in enumerate(left):
        ax.text(total + 0.1, i, str(total), va="center", fontsize=8.5, fontweight="bold")
    ax.set_yticks(range(len(cats)), [names[c] for c in cats])
    ax.invert_yaxis()
    ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=8, handlelength=0.9)
    ax.set_xlabel("actions")
    _clean(ax, "x")
    ax.spines["left"].set_visible(False)
    cs.save("severity_by_category", fig)


def impact_effort(cs: ChartSet, actions: list[dict]) -> None:
    if not actions:
        return
    fig, ax = plt.subplots(figsize=(6.4, 2.85))
    ax.axvspan(0.5, 2.5, ymin=0.5, ymax=1, color="#f7e3f1", zorder=0)
    ax.text(0.6, 103, "QUICK WINS", fontsize=7.5, fontweight="bold", color=RAMP[4])
    ax.text(4.4, 103, "BIG BETS", fontsize=7.5, fontweight="bold", color=INK2, ha="right")
    ax.text(0.6, 2, "FILL-INS", fontsize=7.5, fontweight="bold", color=MUTED)
    ax.text(4.4, 2, "LATER", fontsize=7.5, fontweight="bold", color=MUTED, ha="right")
    ax.axhline(50, color=GRID, lw=0.8)
    ax.axvline(2.5, color=GRID, lw=0.8)
    seen: dict[tuple, int] = {}
    labels = []
    for a in actions[:30]:
        key = (a["effort"], round(a["impact"] / 6))
        k = seen.get(key, 0)
        seen[key] = k + 1
        x = a["effort"] + (k % 4 - 1.5) * 0.14
        ax.scatter(x, a["impact"], s=90, color=PRIORITY[a["priority"]], edgecolor=SURFACE, linewidth=1.5, zorder=3)
        if a["priority"] == "P1" or a["impact"] >= 45:
            labels.append((x, a["impact"], a["action_id"].replace("JEV-", "")))
    for p, c in PRIORITY.items():
        ax.scatter([], [], s=50, color=c, label=p)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=False, fontsize=8, handletextpad=0.2)
    ax.set_xlim(0.5, 4.5)
    ax.set_ylim(0, 110)
    place_labels(ax, fig, labels, fontsize=7, limit=15)
    ax.set_xticks([1, 2, 3, 4], ["Hours", "A day", "Days", "A project"])
    ax.set_xlabel("effort (planning estimate)")
    ax.set_ylabel("relative impact")
    _clean(ax)
    cs.save("impact_effort", fig)


def bars(cs: ChartSet, name: str, labels: list[str], values: list[int], xlabel: str = "", highlight: set | None = None, horizontal: bool = False) -> None:
    if not values:
        return
    fig, ax = plt.subplots(figsize=(3.2, 2.3))
    colors = [MAGENTA if not highlight or l in highlight else OTHER for l in labels]
    if horizontal:
        ax.barh(range(len(values)), values, color=colors, height=0.6)
        ax.set_yticks(range(len(labels)), labels)
        ax.invert_yaxis()
        for i, v in enumerate(values):
            ax.text(v, i, f" {v}", va="center", fontsize=8)
        _clean(ax, "x")
    else:
        ax.bar(range(len(values)), values, color=colors, width=0.62)
        ax.set_xticks(range(len(labels)), labels)
        for i, v in enumerate(values):
            ax.text(i, v, f"{v}", ha="center", va="bottom", fontsize=8)
        _clean(ax, "y")
    ax.set_xlabel(xlabel)
    cs.save(name, fig)


def histogram(cs: ChartSet, name: str, values: list[int], bins: list[int], marker: int | None = None, xlabel: str = "") -> None:
    if not values:
        return
    fig, ax = plt.subplots(figsize=(3.2, 2.3))
    ax.hist(values, bins=bins, color=MAGENTA, edgecolor=SURFACE, linewidth=1.5)
    if marker is not None:
        ax.axvline(marker, color=INK2, lw=1, ls=(0, (3, 2)))
        ax.text(marker, ax.get_ylim()[1] * 0.95, f" {marker}", fontsize=7.5, color=INK2, va="top")
    ax.set_xlabel(xlabel)
    _clean(ax, "y")
    cs.save(name, fig)


def heatmap(cs: ChartSet, rows: list[str], cols: list[str], matrix: list[list[float | None]]) -> None:
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(6.6, 0.26 * len(rows) + 0.9))
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            face = PANEL if v is None else CMAP(v)
            ax.add_patch(FancyBboxPatch((j + 0.06, i + 0.08), 0.88, 0.84, boxstyle="round,pad=0,rounding_size=0.08", color=face, linewidth=0))
            label = "–" if v is None else f"{v:.2f}"
            ax.text(j + 0.5, i + 0.5, label, ha="center", va="center", fontsize=7, color=INK if v is None or v < 0.6 else "#ffffff")
    ax.set_xlim(0, len(cols))
    ax.set_ylim(len(rows), 0)
    ax.set_xticks([j + 0.5 for j in range(len(cols))], cols, fontsize=7.5)
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(rows))], rows, fontsize=7.5)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    cs.save("jev_heatmap", fig)


def confidence_bars(cs: ChartSet, rows: list[tuple[str, int, int]]) -> None:
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(6.4, 0.19 * len(rows) + 0.6))
    labels = [r[0] for r in rows]
    dec = [r[1] for r in rows]
    rev = [r[2] for r in rows]
    ax.barh(range(len(rows)), dec, color=MAGENTA, height=0.58, label="decisive", edgecolor=SURFACE, linewidth=1.5)
    ax.barh(range(len(rows)), rev, left=dec, color=GRID, height=0.58, label="needs a human check", edgecolor=SURFACE, linewidth=1.5)
    ax.set_yticks(range(len(rows)), labels)
    ax.invert_yaxis()
    ax.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=8, handlelength=0.9)
    ax.set_xlabel("pages")
    _clean(ax, "x")
    ax.spines["left"].set_visible(False)
    cs.save("jev_confidence", fig)


def lighthouse(cs: ChartSet, run_mobile: dict | None, run_desktop: dict | None) -> None:
    cats = ["performance", "accessibility", "best-practices", "seo"]
    runs = [(n, r) for n, r in (("mobile", run_mobile), ("desktop", run_desktop)) if r and r.get("scores")]
    if not runs:
        return
    fig, ax = plt.subplots(figsize=(6.4, 2.4))
    w = 0.36
    for k, (name, r) in enumerate(runs):
        vals = [r["scores"].get(c, 0) for c in cats]
        xs = [i + (k - (len(runs) - 1) / 2) * w for i in range(len(cats))]
        ax.bar(xs, vals, width=w - 0.04, color=CATEGORICAL[k], label=name)
        for x, v in zip(xs, vals):
            ax.text(x, v + 1, str(v), ha="center", fontsize=8)
    ax.set_xticks(range(len(cats)), [c.replace("-", " ") for c in cats])
    ax.set_ylim(0, 112)
    ax.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=8, handlelength=0.9)
    _clean(ax, "y")
    cs.save("lighthouse", fig)


def cwv_bullets(cs: ChartSet, field: dict | None) -> None:
    if not field or not field.get("metrics"):
        return
    metrics = [(m, v) for m, v in field["metrics"].items() if m in ("LCP", "INP", "CLS", "FCP", "TTFB")]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(6.4, 0.55 * len(metrics) + 0.2))
    if len(metrics) == 1:
        axes = [axes]
    for ax, (m, v) in zip(axes, metrics):
        good, poor = v["good_max"], v["poor_min"]
        top = max(poor * 1.4, v["p75"] * 1.1)
        ax.barh(0, good, color="#dff3df", height=0.7)
        ax.barh(0, poor - good, left=good, color="#fdf0d0", height=0.7)
        ax.barh(0, top - poor, left=poor, color="#f8dcdc", height=0.7)
        ax.plot([v["p75"]], [0], marker="D", color=INK, markersize=7)
        unit = v["unit"]
        ax.text(-top * 0.02, 0, m, ha="right", va="center", fontsize=9, fontweight="bold")
        ax.text(top * 1.01, 0, f"{v['p75']}{unit}  {v['rating']}", va="center", fontsize=8, color=INK2)
        ax.set_xlim(0, top)
        ax.set_yticks([])
        ax.set_xticks([])
        for s in ax.spines.values():
            s.set_visible(False)
    cs.save("cwv", fig)


def site_map(cs: ChartSet, nodes: list[dict], edges: list[tuple[str, str]], home: str) -> None:
    """Pages on evenly spaced rings by click depth, sized by Jev importance, coloured by Jev page type.
    The outer dashed ring holds pages no crawled page links to."""
    import math

    if len(nodes) < 2:
        return
    counts: dict[str, int] = {}
    for n in nodes:
        if n["type"]:
            counts[n["type"]] = counts.get(n["type"], 0) + 1
    top = sorted(counts, key=lambda t: -counts[t])[:3]
    colour = {t: CATEGORICAL[i] for i, t in enumerate(top)}
    rings: dict[int, list[dict]] = {}
    for n in nodes:
        if n["url"] == home:
            continue
        d = n["depth"] if n["depth"] is not None and n["depth"] < 99 else -1
        rings.setdefault(d, []).append(n)
    order = sorted(d for d in rings if d >= 0) + ([-1] if -1 in rings else [])
    radius = {d: (i + 1) / len(order) for i, d in enumerate(order)}
    pos = {home: (0.0, 0.0)}
    for d in order:
        members = sorted(rings[d], key=lambda n: n["url"])
        for i, n in enumerate(members):
            a = 2 * math.pi * i / len(members) + 0.35 * radius[d]
            pos[n["url"]] = (radius[d] * math.cos(a), radius[d] * math.sin(a))
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    for d in order:
        orphan = d == -1
        ax.add_patch(plt.Circle((0, 0), radius[d], fill=False, color=STATUS["critical"] if orphan else GRID, lw=0.7, ls=(0, (2, 2)), alpha=0.6 if orphan else 1))
    if -1 in rings:
        ax.text(0, -1.09, "not linked from crawled pages", ha="center", fontsize=7, color=STATUS["critical"])
    alpha = max(0.08, min(0.6, 25 / max(len(edges), 1)))
    for a, b in edges:
        if a in pos and b in pos and a != b:
            ax.plot([pos[a][0], pos[b][0]], [pos[a][1], pos[b][1]], color=INK2, lw=0.4, alpha=alpha, zorder=1)
    size_scale = 1.0 if len(nodes) <= 25 else 0.55
    for n in nodes:
        if n["url"] not in pos:
            continue
        x, y = pos[n["url"]]
        is_home = n["url"] == home
        size = (40 + 240 * (n["importance"] if n["importance"] is not None else 0.3)) * size_scale
        ax.scatter(x, y, s=size * (1.6 if is_home else 1), color=INK if is_home else colour.get(n["type"], OTHER), edgecolor=SURFACE, linewidth=1.2, zorder=3)
    ax.set_xlim(-1.25, 1.25)
    ax.set_ylim(-1.18, 1.18)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.annotate("Homepage", (0, 0), xytext=(0, -13), textcoords="offset points", ha="center", fontsize=7, fontweight="bold", color=INK, zorder=6,
                bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1, "alpha": 0.85})
    ranked = sorted((n for n in nodes if n["url"] != home and n["url"] in pos), key=lambda n: -(n["importance"] or 0))
    names = []
    for n in ranked:
        name = n["label"].rstrip("/").rsplit("/", 1)[-1] or n["label"]
        names.append((*pos[n["url"]], name[:20] + ("…" if len(name) > 20 else "")))
    place_labels(ax, fig, names, fontsize=6.6, limit=8)
    ax.scatter([], [], s=45, color=INK, label="homepage")
    for t in top:
        ax.scatter([], [], s=45, color=colour[t], label=t.replace("_", " "))
    if any(n["type"] not in colour for n in nodes if n["url"] != home):
        ax.scatter([], [], s=45, color=OTHER, label="other types")
    ax.legend(loc="upper left", bbox_to_anchor=(0.98, 1.0), frameon=False, fontsize=7.5)
    cs.save("site_map", fig)


def funnel(cs: ChartSet, stages: list[tuple[str, int]]) -> None:
    stages = [(k, v) for k, v in stages if v is not None]
    if not stages:
        return
    fig, ax = plt.subplots(figsize=(6.4, 0.42 * len(stages) + 0.3))
    top = max(v for _, v in stages) or 1
    for i, (label, v) in enumerate(stages):
        w = max(v / top, 0.02)
        ax.barh(i, w, left=(1 - w) / 2, color=CMAP(0.35 + 0.6 * i / max(len(stages) - 1, 1)), height=0.7)
        ax.text(0.5, i, f"{v}", ha="center", va="center", fontsize=9, fontweight="bold", color="#ffffff" if w > 0.12 else INK)
        ax.text(-0.02, i, label, ha="right", va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(-0.02, 1.02)
    ax.invert_yaxis()
    ax.axis("off")
    cs.save("funnel", fig)


def invest_matrix(cs: ChartSet, points: list[dict]) -> None:
    """Jev importance against judged quality: important but weak pages sit top left."""
    if len(points) < 2:
        return
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    ax.fill_between([0, 0.5], 0.5, 1.1, color="#f7e3f1", zorder=0, lw=0)  # data units: quality < 0.5, importance >= 0.5
    ax.axhline(0.5, color=GRID, lw=0.8)
    ax.axvline(0.5, color=GRID, lw=0.8)
    kw = {"transform": ax.transAxes, "fontsize": 7.5, "fontweight": "bold"}
    ax.text(0.0, 1.02, "INVEST HERE: important, weak", color=RAMP[4], **kw)
    ax.text(1.0, 1.02, "PROTECT: important, strong", color=INK2, ha="right", **kw)
    ax.text(0.01, 0.03, "LOW PRIORITY", color=MUTED, **kw)
    ax.text(0.99, 0.03, "FINE AS IS", color=MUTED, ha="right", **kw)
    for p in points:
        weak_core = p["importance"] >= 0.5 and p["quality"] < 0.5
        ax.scatter(p["quality"], p["importance"], s=80, color=RAMP[5] if weak_core else MAGENTA if p["importance"] >= 0.5 else OTHER, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.1)
    # Label the weakest important pages first: they are the point of this chart.
    order = sorted(points, key=lambda p: (not (p["importance"] >= 0.5 and p["quality"] < 0.5), -p["importance"] + p["quality"]))
    place_labels(ax, fig, [(p["quality"], p["importance"], p["label"][:28]) for p in order], limit=8)
    ax.set_xlabel("judged quality (mean of helpfulness, specificity, trust)")
    ax.set_ylabel("Jev importance")
    _clean(ax)
    cs.save("invest", fig)


def positions(cs: ChartSet, overview: dict | None) -> None:
    if not overview:
        return
    buckets = [("1", ["pos_1"]), ("2-3", ["pos_2_3"]), ("4-10", ["pos_4_10"]), ("11-20", ["pos_11_20"]), ("21-50", ["pos_21_30", "pos_31_40", "pos_41_50"]),
               ("51-100", ["pos_51_60", "pos_61_70", "pos_71_80", "pos_81_90", "pos_91_100"])]
    labels = [b for b, _ in buckets]
    values = [sum(overview.get(k) or 0 for k in keys) for _, keys in buckets]
    fig, ax = plt.subplots(figsize=(3.2, 2.3))
    ax.bar(range(len(values)), values, color=[RAMP[5], RAMP[4], RAMP[3], RAMP[2], OTHER, OTHER], width=0.62)
    for i, v in enumerate(values):
        ax.text(i, v, f"{v}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_xlabel("Google position (organic)")
    _clean(ax, "y")
    cs.save("positions", fig)


def referring_domains(cs: ChartSet, rows: list[dict], own: str) -> None:
    rows = [r for r in rows if r.get("referring_domains") is not None]
    if len(rows) < 2:
        return
    rows.sort(key=lambda r: -r["referring_domains"])
    fig, ax = plt.subplots(figsize=(3.2, 0.32 * len(rows) + 0.7))
    vals = [max(r["referring_domains"], 1) for r in rows]
    ax.barh(range(len(rows)), vals, color=[MAGENTA if r["domain"] == own else OTHER for r in rows], height=0.6)
    ax.set_xscale("log")
    for i, r in enumerate(rows):
        ax.text(vals[i] * 1.15, i, f"{r['referring_domains']:,}", va="center", fontsize=7.5)
    ax.set_yticks(range(len(rows)), [r["domain"][:22] for r in rows], fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(1, max(vals) * 8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k" if v >= 1000 else f"{v:,.0f}"))
    ax.set_xlabel("referring domains (log scale)")
    _clean(ax)
    cs.save("referring_domains", fig)


def opportunities(cs: ChartSet, rows: list[dict]) -> None:
    """Relevant keywords: difficulty against monthly searches, sized by Jev relevance."""
    import math

    rows = [r for r in rows if r.get("volume")]
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(6.4, 2.7))
    ax.axvspan(0, 30, color="#f7e3f1", zorder=0)
    ax.text(1, 1.02, "EASIER TO WIN", transform=ax.get_xaxis_transform(), fontsize=7.5, fontweight="bold", color=RAMP[4])
    unknown = False
    for r in rows:
        c = RAMP[5] if r.get("new_page") else MAGENTA
        size = 30 + 170 * (r.get("relevance") or 0.5)
        if r.get("difficulty") is None:
            unknown = True  # no difficulty from DataForSEO: drawn hollow at 50, never as a measured value
            ax.scatter(50, r["volume"], s=size, facecolor="none", edgecolor=c, linewidth=1.5, zorder=3)
        else:
            ax.scatter(r["difficulty"], r["volume"], s=size, color=c, edgecolor=SURFACE, linewidth=1.5, zorder=3, alpha=0.9)
    top = sorted(rows, key=lambda r: -r["volume"] * (1 - min(r.get("difficulty") if r.get("difficulty") is not None else 50, 100) / 100))
    if any(not r.get("new_page") for r in rows):
        ax.scatter([], [], s=50, color=MAGENTA, label="an existing page fits")
    if any(r.get("new_page") for r in rows):
        ax.scatter([], [], s=50, color=RAMP[5], label="needs a new page")
    if unknown:
        ax.scatter([], [], s=50, facecolor="none", edgecolor=INK2, label="difficulty unknown (placed at 50)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=False, fontsize=7.5)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlim(-2, 102)
    place_labels(ax, fig, [((r.get("difficulty") if r.get("difficulty") is not None else 50), r["volume"], r["keyword"][:26]) for r in top], limit=9)
    ax.set_xlabel("keyword difficulty (DataForSEO, 0 to 100)")
    ax.set_ylabel("monthly searches (log)")
    _clean(ax)
    cs.save("opportunities", fig)
