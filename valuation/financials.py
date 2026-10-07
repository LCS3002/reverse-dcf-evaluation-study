"""Turn raw XBRL facts into the three inputs a DCF actually needs.

Free cash flow, net debt, and share count. Everything else a valuation model appears to
need is either derived from these or is an assumption dressed up as an input.

Two decisions worth stating because they change the answer:

**FCF is cash from operations less capital expenditure**, and nothing else. Not
"adjusted" FCF, not FCF before some category of spending the company would rather you
ignored. Stock-based compensation stays as the non-cash add-back the cash flow statement
makes it, which flatters technology companies — but the alternative is to start making
judgement calls per company, and an inconsistent definition across a comparison table is
worse than a generous one applied uniformly.

**The base is a multi-year average, not the latest year.** A single year's FCF moves
materially on one capex cycle or working-capital swing, and anchoring a ten-year
projection to a noisy number produces a valuation that says more about the base year than
about the business.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from valuation.config import FCF_SMOOTHING_YEARS, HISTORY_YEARS
from valuation.edgar import extract

logger = logging.getLogger(__name__)


@dataclass
class Financials:
    ticker: str
    entity: str
    history: pd.DataFrame          # fiscal_year, end, cfo, capex, fcf, revenue
    shares: float
    net_debt: float
    balance_sheet_date: str | None
    concepts: dict[str, str | None] = field(default_factory=dict)

    @property
    def base_fcf(self) -> float:
        """Average FCF over the smoothing window — the anchor for the projection."""
        recent = self.history["fcf"].dropna().tail(FCF_SMOOTHING_YEARS)
        if recent.empty:
            raise ValueError(f"{self.ticker}: no usable free cash flow history")
        return float(recent.mean())

    @property
    def latest_fcf(self) -> float:
        return float(self.history["fcf"].dropna().iloc[-1])

    def realised_growth(self, years: int = HISTORY_YEARS) -> float | None:
        """Compound annual growth in FCF over `years`, smoothed at both ends.

        Both endpoints are three-year averages rather than single years. A CAGR measured
        between two individual years is largely a statement about those two years — pick a
        trough as the start and almost anything looks like a growth company.

        Returns None when the starting window is negative, where a growth rate is not
        defined rather than merely large.
        """
        fcf = self.history.dropna(subset=["fcf"])
        if len(fcf) < years:
            years = len(fcf)
        if years < FCF_SMOOTHING_YEARS * 2:
            return None

        window = fcf.tail(years)["fcf"]
        start = float(window.head(FCF_SMOOTHING_YEARS).mean())
        end = float(window.tail(FCF_SMOOTHING_YEARS).mean())
        span = years - FCF_SMOOTHING_YEARS

        if start <= 0 or end <= 0 or span <= 0:
            return None
        return (end / start) ** (1.0 / span) - 1.0


def fiscal_year(end: str) -> int:
    """The fiscal year a period ending on `end` belongs to.

    Not simply the calendar year of the end date. Companies on a 52/53-week calendar
    drift: Johnson & Johnson's fiscal 2009 ended on 2010-01-03, and naming it 2010
    invented a gap at 2009 and a duplicate at 2012 — which in turn made a perfectly
    contiguous nineteen-year history look like a three-year one.

    Shifting back a fortnight before taking the year handles the drift without
    disturbing the ordinary case, and leaves mid-year fiscal ends (Microsoft's June,
    Apple's September) labelled as the company labels them.
    """
    return (date.fromisoformat(end) - timedelta(days=15)).year


def _series(facts: dict, metric: str) -> tuple[pd.Series, str | None]:
    observations, concept = extract(facts, metric)
    if not observations:
        return pd.Series(dtype=float), None
    return (
        pd.Series(
            {obs["end"]: float(obs["val"]) for obs in observations}, dtype=float
        ).sort_index(),
        concept,
    )


def _latest(series: pd.Series) -> tuple[float, str | None]:
    if series.empty:
        return 0.0, None
    return float(series.iloc[-1]), str(series.index[-1])


def build(ticker: str, facts: dict) -> Financials:
    """Assemble one company's financial history from its XBRL facts."""
    concepts: dict[str, str | None] = {}

    cfo, concepts["cfo"] = _series(facts, "cfo")
    capex, concepts["capex"] = _series(facts, "capex")
    revenue, concepts["revenue"] = _series(facts, "revenue")

    if cfo.empty or capex.empty:
        raise ValueError(f"{ticker}: missing cash flow or capital expenditure data")

    # Inner join: a year without both legs cannot produce a free cash flow figure, and
    # treating a missing capex as zero would overstate it by the whole capex line.
    history = pd.DataFrame({"cfo": cfo, "capex": capex}).dropna()
    history["fcf"] = history["cfo"] - history["capex"]
    history["revenue"] = revenue.reindex(history.index)

    history = history.reset_index().rename(columns={"index": "end"})
    history["fiscal_year"] = history["end"].map(fiscal_year)
    history = history[["fiscal_year", "end", "cfo", "capex", "fcf", "revenue"]]

    # A history with a hole in it is not a history. NVIDIA, for instance, has no
    # standard-tagged capital expenditure concept at all between 2013 and 2021 — merging
    # candidate concepts recovers both ends but cannot invent the middle, and a CAGR
    # measured across that gap would be meaningless. Keep only the contiguous run ending
    # at the most recent year, and let the caller decide whether what remains is enough.
    years = history["fiscal_year"].tolist()
    contiguous = 1
    for i in range(len(years) - 1, 0, -1):
        if years[i] - years[i - 1] != 1:
            break
        contiguous += 1
    if contiguous < len(history):
        logger.warning(
            "%s: fiscal years %d-%d have gaps — using the contiguous run from %d",
            ticker, years[0], years[-1], years[len(years) - contiguous],
        )
        history = history.tail(contiguous).reset_index(drop=True)

    # Balance sheet: point-in-time, so take the most recent reported figures
    cash, concepts["cash"] = _series(facts, "cash")
    investments, concepts["short_term_investments"] = _series(facts, "short_term_investments")
    long_debt, concepts["long_term_debt"] = _series(facts, "long_term_debt")
    short_debt, concepts["short_term_debt"] = _series(facts, "short_term_debt")
    share_count, concepts["shares"] = _series(facts, "shares")

    cash_value, cash_date = _latest(cash)
    investments_value, _ = _latest(investments)
    long_debt_value, _ = _latest(long_debt)
    short_debt_value, _ = _latest(short_debt)
    shares_value, _ = _latest(share_count)

    if shares_value <= 0:
        raise ValueError(f"{ticker}: no share count")

    # Short-term investments count as cash for this purpose: they are liquid and held
    # against the same obligations. Excluding them would overstate net debt at every
    # company that parks its surplus in treasuries rather than a deposit account.
    net_debt = (long_debt_value + short_debt_value) - (cash_value + investments_value)

    logger.info(
        "%-6s %d years of FCF (%d-%d) · shares %.2fB · net debt $%.1fB",
        ticker, len(history),
        history["fiscal_year"].min(), history["fiscal_year"].max(),
        shares_value / 1e9, net_debt / 1e9,
    )

    return Financials(
        ticker=ticker,
        entity=facts.get("entityName", ticker),
        history=history,
        shares=shares_value,
        net_debt=net_debt,
        balance_sheet_date=cash_date,
        concepts=concepts,
    )
