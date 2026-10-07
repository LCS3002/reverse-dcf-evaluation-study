"""SEC EDGAR XBRL client.

Pulls company facts straight from `data.sec.gov` and caches the raw JSON, so every figure
in this project traces back to a filing rather than to a data vendor's interpretation of
one. The responses are a few megabytes each and never change for closed periods, so they
are cached to disk and the network is touched once.

The awkward part of XBRL is that companies tag the same economic quantity differently, and
change tags over time. Exxon reports `RevenueFromContractWithCustomerExcludingAssessedTax`;
Microsoft reports `Revenues`. Neither is wrong. So every metric is defined as an ordered
list of candidate concepts and the first one that yields data wins, with the choice
recorded so it can be audited rather than silently assumed.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

import requests

from valuation.config import (
    DATA_DIR,
    DEFAULT_USER_AGENT,
    SEC_RATE_LIMIT_SECONDS,
)

logger = logging.getLogger(__name__)

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Ordered fallbacks. First concept that returns annual data is used.
CONCEPTS: dict[str, list[tuple[str, str]]] = {
    "cfo": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ],
    "capex": [
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets"),
    ],
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
    ],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ],
    "short_term_investments": [
        ("us-gaap", "MarketableSecuritiesCurrent"),
        ("us-gaap", "ShortTermInvestments"),
        ("us-gaap", "AvailableForSaleSecuritiesCurrent"),
    ],
    "long_term_debt": [
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebt"),
    ],
    "short_term_debt": [
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "DebtCurrent"),
        ("us-gaap", "ShortTermBorrowings"),
    ],
    "shares": [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ],
}


class EdgarClient:
    def __init__(self, user_agent: str | None = None, cache_dir: Path | None = None):
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.cache_dir = cache_dir or (DATA_DIR / "edgar")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

    def company_facts(self, cik: str, force: bool = False) -> dict:
        """All XBRL facts SEC holds for one filer, cached as raw JSON."""
        cik = str(cik).zfill(10)
        path = self.cache_dir / f"CIK{cik}.json"

        if path.exists() and not force:
            return json.loads(path.read_text(encoding="utf-8"))

        # SEC asks for no more than ten requests a second
        elapsed = time.monotonic() - self._last_request
        if elapsed < SEC_RATE_LIMIT_SECONDS:
            time.sleep(SEC_RATE_LIMIT_SECONDS - elapsed)

        logger.info("Fetching company facts for CIK %s", cik)
        response = requests.get(
            COMPANY_FACTS_URL.format(cik=cik),
            headers={"User-Agent": self.user_agent},
            timeout=60,
        )
        self._last_request = time.monotonic()
        response.raise_for_status()

        payload = response.json()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload


def _annual_observations(fact: dict) -> list[dict]:
    """Annual, audited observations from one concept's fact block.

    Four filters, each for a specific failure:

    · **10-K only.** Quarterly figures tagged with the same concept would otherwise be
      mixed in with annual ones and quietly understate every total.
    · **Roughly a year long** for flow concepts. XBRL carries year-to-date and multi-year
      durations under the same tag; a 9-month figure read as a year is a 25% error.
    · **One value per period**, preferring the most recently filed. Restatements appear as
      a second observation for a period that already has one.
    · **USD only.** Foreign filers report multiple currencies against one concept.
    """
    out: dict[str, dict] = {}

    for unit, entries in fact.get("units", {}).items():
        if unit != "USD" and not unit.startswith("shares"):
            continue
        for entry in entries:
            if entry.get("form") not in ("10-K", "10-K/A", "20-F"):
                continue

            end = entry.get("end")
            start = entry.get("start")
            if not end:
                continue

            if start:  # a flow (cash flow, revenue) — must span about a year
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                if not 330 <= days <= 400:
                    continue

            previous = out.get(end)
            if previous is None or (entry.get("filed", "") > previous.get("filed", "")):
                out[end] = entry

    return sorted(out.values(), key=lambda e: e["end"])


def extract(facts: dict, metric: str) -> tuple[list[dict], str | None]:
    """Annual series for `metric`, merged across every candidate concept.

    Merging rather than first-match matters more than it looks. Companies switch tags
    mid-history: NVIDIA reports capital expenditure as
    `PaymentsToAcquirePropertyPlantAndEquipment` until 2012 and
    `PaymentsToAcquireProductiveAssets` from 2022. Taking the first concept that returns
    anything picked the three-year stub and silently produced a free cash flow history
    that was wrong by two orders of magnitude — while looking perfectly well-formed.

    Where two concepts cover the same year, the one earlier in the candidate list wins,
    so the ordering expresses preference rather than mere availability. The returned label
    names every concept that contributed, because which tags a company used across its
    history is something a reader should be able to audit.
    """
    if metric not in CONCEPTS:
        raise KeyError(f"unknown metric {metric!r}")

    merged: dict[str, dict] = {}
    used: list[str] = []

    for taxonomy, concept in CONCEPTS[metric]:
        block = facts.get("facts", {}).get(taxonomy, {}).get(concept)
        if not block:
            continue
        contributed = False
        for observation in _annual_observations(block):
            if observation["end"] not in merged:   # earlier candidates take precedence
                merged[observation["end"]] = observation
                contributed = True
        if contributed:
            used.append(concept)

    if not merged:
        logger.warning("No data for metric %r in any candidate concept", metric)
        return [], None

    return (
        sorted(merged.values(), key=lambda e: e["end"]),
        " + ".join(used),
    )
