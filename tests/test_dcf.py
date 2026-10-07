"""Valuation arithmetic.

A DCF is easy to get subtly wrong and hard to notice, because every wrong answer is still
a plausible-looking number with a currency sign in front of it. Two things make it
checkable: at zero growth the model collapses to a closed form, and the reverse solve must
round-trip against the forward model exactly.
"""

import pytest

from valuation.dcf import enterprise_value, implied_growth, value


# ── Closed forms ──────────────────────────────────────────────────────────────


def test_zero_growth_collapses_to_a_perpetuity():
    """With g = 0 and terminal growth = 0 the explicit period and the terminal value sum
    to exactly FCF/r, whatever the horizon. Any error in the discounting, the terminal
    formula or the off-by-one on the first year breaks this identity."""
    fcf, rate = 100.0, 0.09

    for years in (1, 5, 10, 30):
        ev, _ = enterprise_value(fcf, 0.0, rate, 0.0, years)
        assert ev == pytest.approx(fcf / rate, rel=1e-12), f"{years} years"


def test_terminal_share_at_zero_growth_is_the_discount_factor():
    """Under the same conditions the terminal value's share of EV is exactly (1+r)^-N."""
    rate, years = 0.09, 10
    _, share = enterprise_value(100.0, 0.0, rate, 0.0, years)
    assert share == pytest.approx((1 + rate) ** -years, rel=1e-12)


def test_value_scales_linearly_with_base_cash_flow():
    a = enterprise_value(100.0, 0.05, 0.09, 0.025, 10)[0]
    b = enterprise_value(250.0, 0.05, 0.09, 0.025, 10)[0]
    assert b == pytest.approx(2.5 * a, rel=1e-12)


# ── Monotonicity and guards ───────────────────────────────────────────────────


def test_value_increases_with_growth():
    """Strict monotonicity is what guarantees the reverse solve has exactly one root."""
    previous = None
    for growth in (-0.10, 0.0, 0.05, 0.10, 0.20):
        ev, _ = enterprise_value(100.0, growth, 0.09, 0.025, 10)
        if previous is not None:
            assert ev > previous
        previous = ev


def test_value_decreases_as_the_discount_rate_rises():
    high = enterprise_value(100.0, 0.05, 0.12, 0.025, 10)[0]
    low = enterprise_value(100.0, 0.05, 0.08, 0.025, 10)[0]
    assert high < low


def test_discount_rate_below_terminal_growth_raises():
    """A terminal growth rate at or above the discount rate implies infinite value. That
    is a statement about the assumptions, and it should stop rather than produce a
    number."""
    with pytest.raises(ValueError, match="must exceed terminal growth"):
        enterprise_value(100.0, 0.05, 0.02, 0.03, 10)

    with pytest.raises(ValueError):
        enterprise_value(100.0, 0.05, 0.025, 0.025, 10)


def test_net_debt_reduces_equity_value_one_for_one():
    ev = enterprise_value(100.0, 0.05, 0.09, 0.025, 10)[0]
    with_debt = value(100.0, 0.05, net_debt=500.0, shares=10.0)
    assert with_debt.equity_value == pytest.approx(ev - 500.0, rel=1e-12)
    assert with_debt.per_share == pytest.approx((ev - 500.0) / 10.0, rel=1e-12)


def test_net_cash_increases_equity_value():
    """Net debt is negative for a company holding more cash than debt."""
    ev = enterprise_value(100.0, 0.05, 0.09, 0.025, 10)[0]
    v = value(100.0, 0.05, net_debt=-300.0, shares=10.0)
    assert v.equity_value == pytest.approx(ev + 300.0, rel=1e-12)


def test_zero_shares_raises():
    with pytest.raises(ValueError, match="share count"):
        value(100.0, 0.05, net_debt=0.0, shares=0.0)


# ── The reverse solve ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("growth", [-0.05, 0.0, 0.03, 0.08, 0.15, 0.30])
def test_implied_growth_round_trips_against_the_forward_model(growth):
    """Price the company at a known growth rate, then solve for it. Recovering the input
    is the only check that the solver and the model agree — each could be internally
    consistent while disagreeing with the other."""
    base, net_debt, shares = 1_000.0, 2_000.0, 100.0

    price = value(base, growth, net_debt, shares).per_share
    recovered = implied_growth(price, base, net_debt, shares)

    assert recovered is not None
    assert recovered == pytest.approx(growth, abs=1e-5)


def test_implied_growth_rises_with_price():
    base, net_debt, shares = 1_000.0, 0.0, 100.0
    cheap = implied_growth(100.0, base, net_debt, shares)
    dear = implied_growth(300.0, base, net_debt, shares)

    assert cheap is not None and dear is not None
    assert dear > cheap


def test_price_above_the_bracket_returns_none_rather_than_extrapolating():
    """An implied growth beyond the solvable range means the model has stopped applying.
    Reporting a number there would dress a breakdown up as a finding."""
    assert implied_growth(1e9, 1_000.0, 0.0, 100.0) is None


def test_price_below_the_bracket_returns_none():
    assert implied_growth(1e-6, 1_000.0, 0.0, 100.0) is None


def test_non_positive_base_cash_flow_returns_none():
    """Growth from a negative base is not a meaningful quantity."""
    assert implied_growth(100.0, -50.0, 0.0, 100.0) is None
    assert implied_growth(100.0, 0.0, 0.0, 100.0) is None


def test_implied_growth_respects_the_assumptions_it_is_given():
    """The same price implies different growth under different discount rates — which is
    the entire reason the study reports a sensitivity grid rather than one number."""
    base, net_debt, shares = 1_000.0, 0.0, 100.0
    price = 200.0

    at_seven = implied_growth(price, base, net_debt, shares, discount_rate=0.07)
    at_eleven = implied_growth(price, base, net_debt, shares, discount_rate=0.11)

    assert at_seven is not None and at_eleven is not None
    # a higher discount rate demands more growth to justify the same price
    assert at_eleven > at_seven
