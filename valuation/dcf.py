"""Discounted cash flow, run forwards and — the point of this project — backwards.

A forward DCF takes a growth assumption and produces a value. Every input is a judgement,
the output is a single number with a currency sign in front of it, and the arithmetic
confers an authority the assumptions have not earned. Change growth by two points and the
answer moves by a third.

Run backwards, the same machinery asks a better question: **given what the market is
paying, what growth rate does that price already imply?** That number can then be set
against what the company has actually delivered. It is not a valuation, and it does not
tell you whether to buy anything. It tells you what you would have to believe — which is
falsifiable in a way a price target is not.

Model:

    EV  =  Σ(t=1..N) FCF₀(1+g)ᵗ / (1+r)ᵗ  +  TV / (1+r)ᴺ
    TV  =  FCF₀(1+g)ᴺ × (1+gₜ) / (r − gₜ)

with FCF₀ the smoothed base, g the explicit-period growth, r the discount rate and gₜ the
terminal growth rate. Equity value is EV less net debt; per share, that divided by the
share count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from valuation.config import (
    DISCOUNT_RATE,
    FORECAST_YEARS,
    IMPLIED_GROWTH_BOUNDS,
    SOLVER_TOLERANCE,
    TERMINAL_GROWTH,
)

logger = logging.getLogger(__name__)


@dataclass
class Valuation:
    enterprise_value: float
    equity_value: float
    per_share: float
    terminal_share: float       # fraction of EV sitting in the terminal value


def enterprise_value(
    base_fcf: float,
    growth: float,
    discount_rate: float = DISCOUNT_RATE,
    terminal_growth: float = TERMINAL_GROWTH,
    years: int = FORECAST_YEARS,
) -> tuple[float, float]:
    """Enterprise value and the share of it held in the terminal value.

    The terminal share is returned because it is the single most useful diagnostic a DCF
    produces and the one most often left out. When 80% of a valuation sits beyond the
    forecast horizon, the explicit forecast is decoration — and the reader deserves to
    know that before being shown a number.
    """
    if discount_rate <= terminal_growth:
        raise ValueError(
            f"discount rate {discount_rate:.3f} must exceed terminal growth "
            f"{terminal_growth:.3f} — otherwise the terminal value is infinite, which is "
            "a statement about the assumptions rather than about the company"
        )

    explicit = 0.0
    cash_flow = base_fcf
    for year in range(1, years + 1):
        cash_flow = base_fcf * (1.0 + growth) ** year
        explicit += cash_flow / (1.0 + discount_rate) ** year

    terminal = (
        cash_flow * (1.0 + terminal_growth) / (discount_rate - terminal_growth)
    ) / (1.0 + discount_rate) ** years

    total = explicit + terminal
    share = terminal / total if total != 0 else float("nan")
    return total, share


def value(
    base_fcf: float,
    growth: float,
    net_debt: float,
    shares: float,
    discount_rate: float = DISCOUNT_RATE,
    terminal_growth: float = TERMINAL_GROWTH,
    years: int = FORECAST_YEARS,
) -> Valuation:
    """Full forward valuation at one growth assumption."""
    if shares <= 0:
        raise ValueError("share count must be positive")

    ev, terminal_share = enterprise_value(
        base_fcf, growth, discount_rate, terminal_growth, years
    )
    equity = ev - net_debt
    return Valuation(
        enterprise_value=ev,
        equity_value=equity,
        per_share=equity / shares,
        terminal_share=terminal_share,
    )


def implied_growth(
    price: float,
    base_fcf: float,
    net_debt: float,
    shares: float,
    discount_rate: float = DISCOUNT_RATE,
    terminal_growth: float = TERMINAL_GROWTH,
    years: int = FORECAST_YEARS,
    bounds: tuple[float, float] = IMPLIED_GROWTH_BOUNDS,
    tolerance: float = SOLVER_TOLERANCE,
) -> float | None:
    """The explicit-period growth rate that reconciles the model to the market price.

    Solved by bisection, which is slower than Newton's method and cannot diverge — the
    right trade when the function is cheap and a silent failure would be reported as a
    finding.

    Per-share value is strictly increasing in growth (for a positive base cash flow), so a
    sign change across the bracket guarantees exactly one root. Returns `None` when the
    price lies outside the bracket entirely: an implied growth of 80% a year for a decade
    is not an expectation anyone holds, it is the model telling you it has stopped
    applying, and extrapolating past that would dress a breakdown up as a result.
    """
    if base_fcf <= 0:
        logger.warning("Base free cash flow is not positive — implied growth undefined")
        return None

    low, high = bounds

    def gap(growth: float) -> float:
        return value(
            base_fcf, growth, net_debt, shares, discount_rate, terminal_growth, years
        ).per_share - price

    gap_low, gap_high = gap(low), gap(high)
    if gap_low > 0:
        logger.info(
            "Price is below the model's value even at %.0f%% decline — "
            "outside the solvable range", low * 100,
        )
        return None
    if gap_high < 0:
        logger.info(
            "Price exceeds the model's value even at %.0f%% growth — "
            "outside the solvable range", high * 100,
        )
        return None

    for _ in range(200):
        mid = (low + high) / 2.0
        gap_mid = gap(mid)
        if abs(gap_mid) < tolerance or (high - low) < tolerance:
            return mid
        if gap_mid < 0:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0
