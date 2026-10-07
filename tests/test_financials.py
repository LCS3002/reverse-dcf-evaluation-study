"""Filing extraction: the layer where a wrong answer looks exactly like a right one.

Every case here is a real failure found against real filings, not a hypothetical.
"""

import pandas as pd
import pytest

from valuation.edgar import _annual_observations, extract
from valuation.financials import build, fiscal_year


# ── Fiscal year labelling ─────────────────────────────────────────────────────


def test_fiscal_year_handles_a_year_end_falling_in_january():
    """Johnson & Johnson's fiscal 2009 ended on 2010-01-03. Labelling it 2010 invented a
    gap at 2009 and a duplicate at 2012, which turned a contiguous nineteen-year history
    into a three-year one."""
    assert fiscal_year("2010-01-03") == 2009
    assert fiscal_year("2012-01-01") == 2011
    assert fiscal_year("2012-12-30") == 2012


def test_fiscal_year_leaves_mid_year_ends_alone():
    """Microsoft's June year-end and Apple's September one are labelled as the companies
    label them."""
    assert fiscal_year("2026-06-30") == 2026
    assert fiscal_year("2025-09-27") == 2025
    assert fiscal_year("2025-12-31") == 2025


def test_fiscal_year_is_contiguous_across_a_52_53_week_calendar():
    """The real JNJ sequence, which must come out as consecutive years."""
    ends = ["2007-12-30", "2008-12-28", "2010-01-03", "2011-01-02",
            "2012-01-01", "2012-12-30", "2013-12-29"]
    years = [fiscal_year(e) for e in ends]

    assert years == [2007, 2008, 2009, 2010, 2011, 2012, 2013]
    assert len(set(years)) == len(years), "no duplicates"


# ── Concept merging ───────────────────────────────────────────────────────────


def _fact(values, start_offset=True):
    """Build a minimal XBRL fact block. `values` maps end-date -> value."""
    units = []
    for end, val in values.items():
        entry = {"end": end, "val": val, "form": "10-K", "filed": "2026-01-01"}
        if start_offset:
            entry["start"] = f"{int(end[:4]) - 1}{end[4:]}"
        units.append(entry)
    return {"units": {"USD": units}}


def test_concepts_are_merged_across_a_mid_history_tag_change():
    """NVIDIA reports capex as PaymentsToAcquirePropertyPlantAndEquipment until 2012 and
    PaymentsToAcquireProductiveAssets from 2022. Taking the first concept with any data
    picked the three-year stub and produced a free cash flow history wrong by two orders
    of magnitude — while looking entirely well-formed."""
    facts = {
        "facts": {
            "us-gaap": {
                "PaymentsToAcquirePropertyPlantAndEquipment": _fact(
                    {"2011-12-31": 100.0, "2012-12-31": 110.0}
                ),
                "PaymentsToAcquireProductiveAssets": _fact(
                    {"2022-12-31": 500.0, "2023-12-31": 600.0}
                ),
            }
        }
    }

    observations, label = extract(facts, "capex")
    assert len(observations) == 4, "both tags must contribute"
    assert "PaymentsToAcquirePropertyPlantAndEquipment" in label
    assert "PaymentsToAcquireProductiveAssets" in label


def test_earlier_candidate_wins_where_concepts_overlap():
    """Ordering expresses preference, not merely availability."""
    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _fact(
                    {"2023-12-31": 999.0}
                ),
                "Revenues": _fact({"2023-12-31": 111.0}),
            }
        }
    }
    observations, _ = extract(facts, "revenue")
    assert observations[0]["val"] == 999.0


def test_unknown_metric_raises():
    with pytest.raises(KeyError):
        extract({"facts": {}}, "ebitda_adjusted_for_vibes")


# ── Annual observation filtering ──────────────────────────────────────────────


def test_quarterly_periods_are_rejected():
    """Quarterly figures carry the same concept; counted as annual they understate
    every total."""
    block = {"units": {"USD": [
        {"start": "2023-01-01", "end": "2023-03-31", "val": 25.0, "form": "10-K", "filed": "2024-01-01"},
        {"start": "2023-01-01", "end": "2023-12-31", "val": 100.0, "form": "10-K", "filed": "2024-01-01"},
    ]}}
    observations = _annual_observations(block)
    assert len(observations) == 1
    assert observations[0]["val"] == 100.0


def test_non_10k_forms_are_rejected():
    block = {"units": {"USD": [
        {"start": "2023-01-01", "end": "2023-12-31", "val": 100.0, "form": "10-Q", "filed": "2024-01-01"},
    ]}}
    assert _annual_observations(block) == []


def test_restatements_prefer_the_later_filing():
    block = {"units": {"USD": [
        {"start": "2023-01-01", "end": "2023-12-31", "val": 100.0, "form": "10-K", "filed": "2024-01-01"},
        {"start": "2023-01-01", "end": "2023-12-31", "val": 95.0, "form": "10-K", "filed": "2025-01-01"},
    ]}}
    observations = _annual_observations(block)
    assert len(observations) == 1
    assert observations[0]["val"] == 95.0, "the restated figure should win"


def test_non_usd_units_are_rejected():
    block = {"units": {"EUR": [
        {"start": "2023-01-01", "end": "2023-12-31", "val": 100.0, "form": "10-K", "filed": "2024-01-01"},
    ]}}
    assert _annual_observations(block) == []


# ── Assembly ──────────────────────────────────────────────────────────────────


def _company(cfo: dict, capex: dict, shares=1_000.0, cash=0.0, debt=0.0):
    instant = lambda v: {"units": {"USD": [  # noqa: E731
        {"end": "2025-12-31", "val": v, "form": "10-K", "filed": "2026-01-01"}
    ]}}
    return {
        "entityName": "Test Co",
        "facts": {
            "us-gaap": {
                "NetCashProvidedByUsedInOperatingActivities": _fact(cfo),
                "PaymentsToAcquirePropertyPlantAndEquipment": _fact(capex),
                "CashAndCashEquivalentsAtCarryingValue": instant(cash),
                "LongTermDebtNoncurrent": instant(debt),
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [
                        {"end": "2025-12-31", "val": shares, "form": "10-K", "filed": "2026-01-01"}
                    ]}
                }
            },
        },
    }


def test_free_cash_flow_is_operating_cash_less_capex():
    facts = _company(
        cfo={"2023-12-31": 1000.0, "2024-12-31": 1100.0, "2025-12-31": 1200.0},
        capex={"2023-12-31": 200.0, "2024-12-31": 220.0, "2025-12-31": 240.0},
    )
    f = build("TEST", facts)

    assert list(f.history["fcf"]) == [800.0, 880.0, 960.0]
    assert f.latest_fcf == 960.0
    assert f.base_fcf == pytest.approx((800 + 880 + 960) / 3)


def test_a_year_missing_capex_is_dropped_not_treated_as_zero():
    """Treating absent capex as zero would overstate free cash flow by the whole line."""
    facts = _company(
        cfo={"2023-12-31": 1000.0, "2024-12-31": 1100.0, "2025-12-31": 1200.0},
        capex={"2023-12-31": 200.0, "2025-12-31": 240.0},
    )
    f = build("TEST", facts)
    assert 1100.0 not in list(f.history["cfo"]), "the year without capex must be dropped"


def test_net_debt_nets_cash_against_debt():
    facts = _company(
        cfo={"2024-12-31": 1000.0, "2025-12-31": 1000.0},
        capex={"2024-12-31": 100.0, "2025-12-31": 100.0},
        cash=5_000.0, debt=2_000.0,
    )
    f = build("TEST", facts)
    assert f.net_debt == pytest.approx(2_000.0 - 5_000.0), "net cash is negative net debt"


def test_missing_cash_flow_data_raises_rather_than_returning_an_empty_company():
    facts = _company(cfo={}, capex={"2025-12-31": 100.0})
    with pytest.raises(ValueError, match="missing cash flow"):
        build("TEST", facts)


def test_history_with_a_gap_keeps_only_the_contiguous_recent_run():
    """NVIDIA has no standard-tagged capex between 2013 and 2021. A CAGR measured across
    that hole would be meaningless, so only the run ending at the latest year survives."""
    facts = _company(
        cfo={"2011-12-31": 100.0, "2012-12-31": 110.0,
             "2024-12-31": 900.0, "2025-12-31": 1000.0},
        capex={"2011-12-31": 10.0, "2012-12-31": 11.0,
               "2024-12-31": 90.0, "2025-12-31": 100.0},
    )
    f = build("TEST", facts)

    assert list(f.history["fiscal_year"]) == [2024, 2025]


def test_realised_growth_is_none_when_history_is_too_short():
    facts = _company(
        cfo={"2024-12-31": 1000.0, "2025-12-31": 1100.0},
        capex={"2024-12-31": 100.0, "2025-12-31": 110.0},
    )
    assert build("TEST", facts).realised_growth() is None


def test_realised_growth_recovers_a_known_compound_rate():
    """Ten years compounding at exactly 10%, with both endpoints smoothed."""
    cfo, capex = {}, {}
    for i in range(10):
        year = 2016 + i
        cfo[f"{year}-12-31"] = 1000.0 * (1.10 ** i)
        capex[f"{year}-12-31"] = 0.0

    f = build("TEST", _company(cfo=cfo, capex=capex))
    growth = f.realised_growth(years=10)

    assert growth == pytest.approx(0.10, abs=1e-9)
