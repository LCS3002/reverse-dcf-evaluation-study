"""Two exhibits. Each answers a question the table alone leaves open.

Colours come from a validated categorical palette in fixed slot order. The growth gap is
a **signed** quantity — the market asks more of most of these companies than they have
delivered, and less of one — so it takes the diverging blue/red pair with a neutral
midpoint rather than a categorical hue. Magnitude in the sensitivity grid takes a single
sequential hue, light to dark, never a rainbow.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from valuation.config import RESULTS_DIR  # noqa: E402

logger = logging.getLogger(__name__)

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8980"
GRID = "#e8e7e3"

REALISED = "#2a78d6"      # categorical slot 1
IMPLIED = "#eb6834"       # categorical slot 2
POS, NEG = "#2a78d6", "#e34948"   # diverging poles
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def _style(ax, *, xlabel="", ylabel=""):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK_SECONDARY, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_SECONDARY, fontsize=10)


def _title(ax, title, subtitle=""):
    ax.set_title(title, color=INK_PRIMARY, fontsize=13, fontweight="bold",
                 loc="left", pad=20 if subtitle else 10)
    if subtitle:
        ax.text(0.0, 1.015, subtitle, transform=ax.transAxes, color=INK_SECONDARY,
                fontsize=9.5, va="bottom", ha="left")


def _save(fig, name, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    logger.info("Wrote %s", path)
    return path


# ── Exhibit 1: the gap ────────────────────────────────────────────────────────


def growth_gap(results: dict, out_dir: Path = RESULTS_DIR) -> Path:
    """What each company has delivered against what its price asks for.

    A dumbbell rather than paired bars: the quantity of interest is the *distance*
    between two rates for the same company, and a connecting line shows a distance
    directly where two bars make the reader compute it.
    """
    rows = [
        (t, c["realised_growth"], c["implied_growth"], c["growth_gap"])
        for t, c in results["companies"].items()
        if c["realised_growth"] is not None and c["implied_growth"] is not None
    ]
    rows.sort(key=lambda r: r[3])

    fig, ax = plt.subplots(figsize=(9.5, 5.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)

    for i, (ticker, realised, implied, gap) in enumerate(rows):
        colour = POS if gap > 0 else NEG
        ax.plot([realised * 100, implied * 100], [i, i], color=colour,
                linewidth=2.4, alpha=0.45, zorder=2, solid_capstyle="round")
        ax.scatter([realised * 100], [i], s=90, color=REALISED, zorder=4,
                   edgecolor=SURFACE, linewidth=1.6)
        ax.scatter([implied * 100], [i], s=90, color=IMPLIED, zorder=4,
                   edgecolor=SURFACE, linewidth=1.6)
        ax.annotate(f"{gap*100:+.1f}pp", xy=(max(realised, implied) * 100, i),
                    xytext=(10, 0), textcoords="offset points", va="center",
                    color=INK_PRIMARY, fontsize=9, fontweight="bold")

    ax.axvline(0, color=INK_MUTED, linewidth=1.0, zorder=1)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=10, color=INK_PRIMARY)
    ax.set_xlim(-8, max(r[2] for r in rows) * 100 + 9)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    _style(ax, xlabel="Annual free cash flow growth (%)")
    _title(ax, "What the market has to believe",
           f"Realised growth vs the rate the share price implies · {results['as_of']}")

    ax.scatter([], [], s=90, color=REALISED, label="Delivered (10-year realised)")
    ax.scatter([], [], s=90, color=IMPLIED, label="Implied by today's price")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY,
              loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2)
    fig.subplots_adjust(bottom=0.18)

    return _save(fig, "exhibit_1_growth_gap.png", out_dir)


# ── Exhibit 2: how much of it is the assumptions ──────────────────────────────


def sensitivity_grid(results: dict, ticker: str = "AAPL",
                     out_dir: Path = RESULTS_DIR) -> Path | None:
    """Implied growth across the discount-rate and terminal-growth grid.

    The headline implied figure is a point estimate resting on two assumptions nobody can
    observe. This shows how much of it is those assumptions, which is the difference
    between reporting a result and reporting a number.
    """
    company = results["companies"].get(ticker)
    if not company:
        logger.warning("No results for %s", ticker)
        return None

    waccs = sorted({row["discount_rate"] for row in company["sensitivity"]})
    terminals = sorted({row["terminal_growth"] for row in company["sensitivity"]})
    grid = np.full((len(waccs), len(terminals)), np.nan)

    for row in company["sensitivity"]:
        if row["implied_growth"] is None:
            continue
        grid[waccs.index(row["discount_rate"]), terminals.index(row["terminal_growth"])] = (
            row["implied_growth"] * 100
        )

    fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=160)
    fig.patch.set_facecolor(SURFACE)

    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    image = ax.imshow(grid, cmap=cmap, aspect="auto", origin="lower")

    for i in range(len(waccs)):
        for j in range(len(terminals)):
            if np.isnan(grid[i, j]):
                ax.text(j, i, "—", ha="center", va="center", color=INK_MUTED, fontsize=10)
                continue
            # ink against the cell, not a fixed colour: dark text vanishes on dark steps
            span = np.nanmax(grid) - np.nanmin(grid)
            light = span > 0 and (grid[i, j] - np.nanmin(grid)) / span > 0.55
            ax.text(j, i, f"{grid[i, j]:.1f}%", ha="center", va="center",
                    color="#ffffff" if light else INK_PRIMARY,
                    fontsize=10, fontweight="bold")

    ax.set_xticks(range(len(terminals)))
    ax.set_xticklabels([f"{t:.1%}" for t in terminals])
    ax.set_yticks(range(len(waccs)))
    ax.set_yticklabels([f"{w:.0%}" for w in waccs])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
    ax.set_xlabel("Terminal growth rate", color=INK_SECONDARY, fontsize=10)
    ax.set_ylabel("Discount rate", color=INK_SECONDARY, fontsize=10)

    bar = fig.colorbar(image, ax=ax, shrink=0.85)
    bar.set_label("Implied growth (%)", color=INK_SECONDARY, fontsize=9)
    bar.ax.tick_params(colors=INK_SECONDARY, labelsize=8, length=0)
    bar.outline.set_visible(False)

    _title(ax, f"How much of {ticker}'s implied growth is the assumptions?",
           "Implied annual FCF growth across the discount rate and terminal growth grid")

    return _save(fig, "exhibit_2_sensitivity.png", out_dir)


def build_all(results: dict, out_dir: Path = RESULTS_DIR) -> dict:
    return {
        "gap": growth_gap(results, out_dir),
        "sensitivity": sensitivity_grid(results, "AAPL", out_dir),
    }
