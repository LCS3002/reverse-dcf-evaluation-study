# reverse-dcf — INCOMPLETE SCAFFOLD

**Status: not finished. Do not publish.** Only the SEC EDGAR layer exists.

## What this is meant to be

A reverse DCF on real SEC filings: instead of forecasting cash flows and producing a price
target, solve for **the growth rate the current share price already implies**, then compare
it against what the company has actually delivered over the last decade. The research
question is "what does the market have to believe?" rather than "what is this worth" —
harder to fudge, and it inverts the overconfidence a conventional DCF invites.

It is the rebuild of `finance-sandbox/m&a/mna_analysis.py`, whose flaw was structural: it
fit a regression to data the script itself generated, then printed a "90% confidence
interval for valuation" that reflected only input-shock variance. Not patchable — the
circularity is the design. This replaces it with real filings and reports **parameter
sensitivity**, explicitly not a confidence interval.

## Done

- `valuation/config.py` — all assumptions in one place, fixed a priori
- `valuation/edgar.py` — SEC XBRL client with per-metric concept fallback chains
  (companies tag the same quantity differently: Exxon uses
  `RevenueFromContractWithCustomerExcludingAssessedTax`, Microsoft uses `Revenues`),
  10-K-only filtering, ~365-day duration filtering for flows, restatement handling,
  and on-disk caching

## Not done

- `financials.py` — FCF history (CFO − capex), net debt, share count
- `dcf.py` — forward DCF and the numerical solve for implied growth
- `market.py` — current price and market cap
- `exhibits.py` — WACC × terminal-growth sensitivity grid, implied vs realised growth
- tests, note, runner

## Gotcha worth keeping

SEC returns **403 for any User-Agent containing a URL**. `"LCS3002 reverse-dcf research
script"` works; the same string with a GitHub link appended does not. Tested both ways.
