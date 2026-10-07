"""Runner: pull filings, solve for implied growth, write results and exhibits.

    python -m valuation.run

Writes results/results.json. Every figure in the note comes from that file.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import numpy as np

from valuation import config
from valuation.dcf import implied_growth, value
from valuation.edgar import EdgarClient
from valuation.financials import build
from valuation.market import fetch_prices

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s  %(name)-20s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    for noisy in ("yfinance", "urllib3", "peewee"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def _safe(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        return None if not np.isfinite(value) else value
    return obj


def sensitivity(financials, price: float) -> list[dict]:
    """Implied growth across the discount-rate and terminal-growth grid.

    This is the honest output of the whole exercise. A single implied growth figure
    invites the reader to treat it as measured; the grid shows how much of it is the
    assumptions. Where the discount rate does not exceed terminal growth the cell is
    undefined rather than filled with something plausible-looking.
    """
    rows = []
    for discount_rate in config.WACC_GRID:
        for terminal in config.TERMINAL_GROWTH_GRID:
            if discount_rate <= terminal:
                rows.append(
                    {
                        "discount_rate": discount_rate,
                        "terminal_growth": terminal,
                        "implied_growth": None,
                        "note": "discount rate must exceed terminal growth",
                    }
                )
                continue
            rows.append(
                {
                    "discount_rate": discount_rate,
                    "terminal_growth": terminal,
                    "implied_growth": implied_growth(
                        price,
                        financials.base_fcf,
                        financials.net_debt,
                        financials.shares,
                        discount_rate=discount_rate,
                        terminal_growth=terminal,
                    ),
                }
            )
    return rows


def run(force_data: bool = False) -> dict:
    client = EdgarClient()
    prices = fetch_prices(list(config.COMPANIES), force=force_data)

    results: dict = {
        "as_of": prices["as_of"],
        "assumptions": {
            "discount_rate": config.DISCOUNT_RATE,
            "terminal_growth": config.TERMINAL_GROWTH,
            "forecast_years": config.FORECAST_YEARS,
            "fcf_smoothing_years": config.FCF_SMOOTHING_YEARS,
            "history_years": config.HISTORY_YEARS,
            "wacc_grid": list(config.WACC_GRID),
            "terminal_growth_grid": list(config.TERMINAL_GROWTH_GRID),
        },
        "companies": {},
        "excluded": {},
    }

    for ticker, cik in config.COMPANIES.items():
        if ticker not in prices["prices"]:
            results["excluded"][ticker] = "no market price"
            continue
        try:
            financials = build(ticker, client.company_facts(cik, force=force_data))
        except ValueError as e:
            logger.warning("%s excluded: %s", ticker, e)
            results["excluded"][ticker] = str(e)
            continue

        price = prices["prices"][ticker]
        implied = implied_growth(
            price, financials.base_fcf, financials.net_debt, financials.shares
        )
        realised = financials.realised_growth()
        valuation = value(
            financials.base_fcf,
            implied if implied is not None else 0.0,
            financials.net_debt,
            financials.shares,
        )

        results["companies"][ticker] = {
            "entity": financials.entity,
            "price": price,
            "market_cap": price * financials.shares,
            "shares": financials.shares,
            "net_debt": financials.net_debt,
            "balance_sheet_date": financials.balance_sheet_date,
            "base_fcf": financials.base_fcf,
            "latest_fcf": financials.latest_fcf,
            "fcf_multiple": (price * financials.shares) / financials.base_fcf
            if financials.base_fcf > 0
            else None,
            "history_years": int(len(financials.history)),
            "first_year": int(financials.history["fiscal_year"].min()),
            "last_year": int(financials.history["fiscal_year"].max()),
            "implied_growth": implied,
            "realised_growth": realised,
            "growth_gap": (implied - realised)
            if (implied is not None and realised is not None)
            else None,
            "terminal_value_share": valuation.terminal_share,
            "concepts": financials.concepts,
            "sensitivity": sensitivity(financials, price),
            "history": financials.history.to_dict("records"),
        }

    return results


def report(results: dict) -> None:
    print(f"\n{'='*92}")
    print(f"WHAT THE MARKET HAS TO BELIEVE — prices as of {results['as_of']}")
    a = results["assumptions"]
    print(
        f"discount rate {a['discount_rate']:.0%} · terminal growth "
        f"{a['terminal_growth']:.1%} · {a['forecast_years']}-year explicit forecast · "
        f"FCF base = {a['fcf_smoothing_years']}-year average"
    )
    print(f"{'='*92}")
    print(
        f"{'':6}{'price':>9}{'mkt cap':>10}{'base FCF':>10}{'x FCF':>8}"
        f"{'implied g':>11}{'realised g':>12}{'gap':>9}{'terminal':>10}"
    )
    print("-" * 92)

    rows = sorted(
        results["companies"].items(),
        key=lambda kv: kv[1]["growth_gap"] if kv[1]["growth_gap"] is not None else -99,
        reverse=True,
    )
    for ticker, c in rows:
        ig = f"{c['implied_growth']:.1%}" if c["implied_growth"] is not None else "n/a"
        rg = f"{c['realised_growth']:.1%}" if c["realised_growth"] is not None else "n/a"
        gap = f"{c['growth_gap']:+.1%}" if c["growth_gap"] is not None else "n/a"
        mult = f"{c['fcf_multiple']:.0f}x" if c["fcf_multiple"] else "n/a"
        print(
            f"{ticker:6}{c['price']:>9.2f}{c['market_cap']/1e12:>9.2f}T"
            f"{c['base_fcf']/1e9:>9.1f}B{mult:>8}{ig:>11}{rg:>12}{gap:>9}"
            f"{c['terminal_value_share']:>10.0%}"
        )

    if results["excluded"]:
        print(f"\nExcluded: {results['excluded']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse DCF on SEC filings")
    parser.add_argument("--force-data", action="store_true", help="refetch filings and prices")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = run(force_data=args.force_data)

    out = config.RESULTS_DIR / "results.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=_safe)

    try:
        from valuation.exhibits import build_all

        build_all(results, config.RESULTS_DIR)
    except ImportError:
        logger.warning("Exhibits unavailable")

    report(results)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
