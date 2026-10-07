"""Current share price, cached with the date it was taken.

Market data is the one input here that is not a filing, and the only one that changes
between runs. Everything else in this project is auditable against a 10-K; the price is
auditable only against a timestamp, so the timestamp is stored with it and reported in
the note. A valuation quoted without the date of the price it was compared against is not
reproducible, and the reader has no way to know whether a result has simply aged.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from valuation.config import DATA_DIR

logger = logging.getLogger(__name__)

PRICE_CACHE = DATA_DIR / "prices.json"


def fetch_prices(tickers: list[str], force: bool = False) -> dict:
    """Latest close per ticker, as {"as_of": ISO date, "prices": {ticker: price}}.

    Cached by date: rerunning on the same day reuses the stored prices so every figure in
    one run refers to the same moment, rather than drifting as the session goes on.
    """
    today = date.today().isoformat()

    if PRICE_CACHE.exists() and not force:
        cached = json.loads(PRICE_CACHE.read_text(encoding="utf-8"))
        if cached.get("as_of") == today and set(tickers).issubset(cached["prices"]):
            logger.info("Using cached prices from %s", today)
            return cached

    import yfinance as yf

    logger.info("Fetching prices for %d ticker(s)", len(tickers))
    raw = yf.download(
        tickers, period="5d", auto_adjust=False, progress=False, group_by="column"
    )

    closes = raw["Close"] if "Close" in raw else raw
    prices: dict[str, float] = {}

    for ticker in tickers:
        try:
            series = closes[ticker] if hasattr(closes, "columns") else closes
            last = series.dropna()
            if not last.empty:
                prices[ticker] = float(last.iloc[-1])
        except (KeyError, TypeError):
            logger.warning("No price for %s", ticker)

    missing = sorted(set(tickers) - set(prices))
    if missing:
        # Loud rather than quiet: a company silently dropped here would simply vanish
        # from the results table with nothing to say it had ever been requested.
        logger.warning("No price data for %s — excluded from results", missing)

    payload = {"as_of": today, "prices": prices}
    PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PRICE_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
