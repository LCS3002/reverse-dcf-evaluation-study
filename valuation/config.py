"""Assumptions, all declared in one place and fixed before any result was computed.

A valuation model has more degrees of freedom than a backtest, and every one of them is a
place to arrive at a predetermined answer. Keeping them here — rather than scattered
through the code — is what makes it possible to check that none was moved to make a number
come out nicely.

The discount rate and terminal growth below are deliberately *uniform across companies*.
A per-company WACC would be more defensible in a real engagement and is also the easiest
lever to quietly tune, so the study uses one rate and then shows the full sensitivity
grid instead of hiding behind a point estimate.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

# ── SEC access ────────────────────────────────────────────────────────────────

# SEC rejects requests with no User-Agent and asks for a contact in it as a matter of
# fair-access policy. Set SEC_USER_AGENT to your own name and email if you pull at any
# volume.
#
# One trap worth knowing: SEC returns 403 for any User-Agent **containing a URL**, which
# is a natural thing to put in one. "reverse-dcf research script" returns 200; the same
# string with a GitHub link appended returns 403. Tested both ways.
DEFAULT_USER_AGENT = "LCS3002 reverse-dcf research script"
SEC_RATE_LIMIT_SECONDS = 0.15      # SEC asks for <= 10 requests/second

# ── Universe ──────────────────────────────────────────────────────────────────

# Deliberately mixed: expensive growth names alongside cheap mature ones, because the
# interesting output is the *spread* in what the market is asking each to deliver.
COMPANIES = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "GOOGL": "0001652044",
    "JNJ": "0000200406",
    "KO": "0000021344",
    "XOM": "0000034088",
    "WMT": "0000104169",
}

# ── Model ─────────────────────────────────────────────────────────────────────

FORECAST_YEARS = 10          # explicit forecast horizon before the terminal value
DISCOUNT_RATE = 0.09         # ~ long-run equity cost of capital for US large caps
TERMINAL_GROWTH = 0.025      # below long-run nominal GDP; a firm cannot outgrow the
                             # economy forever, and assuming otherwise is the single
                             # most common way a DCF manufactures value

# History used to compute realised growth, the benchmark the implied figure is judged
# against. Ten years spans at least one full cycle for most of these names.
HISTORY_YEARS = 10

# Free cash flow is smoothed over this many years before being used as the base. A
# single year's FCF is noisy — one large capex cycle or working-capital swing moves it
# materially — and anchoring a ten-year projection to a noisy number is how a DCF ends
# up saying more about the base year than about the business.
FCF_SMOOTHING_YEARS = 3

# ── Sensitivity grid ──────────────────────────────────────────────────────────

# The honest output. Implied growth is highly sensitive to both of these, so the result
# is reported across the grid rather than as a point estimate.
WACC_GRID = (0.07, 0.08, 0.09, 0.10, 0.11)
TERMINAL_GROWTH_GRID = (0.015, 0.020, 0.025, 0.030, 0.035)

# Bounds for the numerical solve. An implied growth rate outside these is reported as
# "outside the solvable range" rather than extrapolated — a model that returns 60% implied
# growth is telling you the model has stopped applying, not that the market expects 60%.
IMPLIED_GROWTH_BOUNDS = (-0.50, 0.60)
SOLVER_TOLERANCE = 1e-7
