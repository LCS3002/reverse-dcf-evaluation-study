# What does the market have to believe?

**Working out what growth each company's share price already assumes — using data straight
from their SEC filings.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Data](https://img.shields.io/badge/data-SEC%20EDGAR-informational)
![Tests](https://img.shields.io/badge/tests-37-28a745)

## The idea

The usual way to value a company is to guess how much cash it will make in future, work
out what that's worth today, and compare the result to the share price. The problem is
that the guess does all the work. Change your growth assumption from 5% to 7% and the
answer moves by a third.

**So this does it backwards.** Instead of guessing growth, it takes the actual share price
as a given and works out what growth rate would justify it. Then it compares that to how
fast the company has actually been growing.

The output isn't an opinion about what a share is worth. It's a statement about what the
market currently assumes — which you can check against the company's real record.

## What it found

Eight large US companies, prices on 7 October 2026.

| | Price assumes | Actually delivered | Difference |
|---|---:|---:|---:|
| **Walmart** | 20.7% a year | **−4.0%** | **+24.7pp** |
| **Coca-Cola** | 20.3% | 1.4% | **+18.8pp** |
| **J&J** | 12.3% | 1.6% | +10.7pp |
| **Apple** | 17.4% | 8.9% | +8.5pp |
| **Microsoft** | 19.1% | 11.1% | +8.0pp |
| **Alphabet** | 19.7% | 16.8% | +2.8pp |
| **Exxon** | 8.1% | 13.1% | **−5.0pp** |

*"Delivered" is how fast the company's cash actually grew over ten years. "pp" means
percentage points.*

**Seven of the eight are priced for faster growth than they have ever managed.** Exxon is
the only one priced below its own record.

**The surprising part is that it's inverted.** The biggest gaps are at the safe, boring
companies. Walmart's share price assumes 20.7% growth from a business whose cash has been
*shrinking*. The smallest gap is Alphabet — which actually does grow fast, at 16.8% — asked
for 19.7%, roughly in line with what it does.

So the companies people buy for safety are carrying the most demanding expectations
relative to their own history.

📄 **[Read the full write-up](notes/research-note.md)**

![What the market has to believe](results/exhibit_1_growth_gap.png)

---

## The most important caveat

Apple's figure is 17.4%. That depends on a "discount rate" — how much less a pound in the
future is worth than a pound today. I used 9%.

Change only that number, to values any analyst would defend:

| Discount rate | Apple's assumed growth |
|---|---|
| 7% | **11.9%** |
| 9% | 17.4% |
| 11% | **22.0%** |

**The answer nearly doubles based on an assumption nobody can measure.**

So the honest version isn't "Apple's price assumes 17.4% growth." It's "depending on
reasonable assumptions, somewhere between 12% and 22%." The range matters more than the
single number, which is why the code reports the whole grid rather than one figure.

## Three other things worth knowing

**Coca-Cola's number is distorted.** Its cash flow looks unusually low because of a one-off
tax payment. Using a more normal figure, its assumed growth drops from 20.3% to 15.4% —
still far above its 1.4% record, but a different number. The model can't tell an odd year
from a trend.

**Walmart is penalised for investing.** It's spending heavily on automation and delivery.
That spending gets subtracted when calculating free cash flow, so the model punishes it for
building the thing the market is paying for.

**Most of the answer comes from beyond the forecast.** The model forecasts ten years
explicitly, then adds a lump for everything after that. For every company here, that lump
is **60–74%** of the total. That's a warning about the method itself — if three-quarters of
your answer comes from a formula about the distant future, you aren't really forecasting
the business.

---

## Why one discount rate for all eight

A more careful job would use a different rate per company, based on how risky each is. I
deliberately didn't.

The reason: the discount rate is the easiest thing to quietly adjust until the answer looks
how you want. Using one rate for everyone, and then showing the full range, is harder to
fiddle than a per-company rate nobody can check.

## How "free cash flow" is defined here

Cash from running the business, minus money spent on equipment and property. Nothing else.

No "adjusted" version, and nothing excluded because a company would rather you ignored it.
This definition is slightly generous to tech companies, for technical reasons involving
share-based pay. But the alternative is making different choices for different companies,
and one consistent definition is more useful in a comparison than eight tailored ones.

---

## Where the data comes from

Straight from **SEC EDGAR**, the US regulator's database where every listed company files
its accounts. It's free and machine-readable. No Bloomberg, no data provider — every
number traces back to an actual filing.

Three things made that harder than expected. Each one produced an answer that *looked*
fine but was wrong:

**Companies change their labels.** Nvidia filed capital spending under one label until 2012
and a different one from 2022. Taking the first label found gave a cash flow history wrong
by a factor of a hundred — $0.6B instead of $61.5B — and nothing about it looked broken.
Fixed by combining labels across the whole history.

**Financial years don't line up with calendar years.** Johnson & Johnson's 2009 financial
year ended on **3 January 2010**. Labelling it by calendar year invented a missing year and
a duplicate one, which turned nineteen years of history into three.

**Sometimes the data genuinely isn't there.** Nvidia has no standard capital-spending label
at all between 2013 and 2021. The code reports it as "not enough history" rather than
pretending to span the gap.

One more, for anyone else using EDGAR: **it rejects any request whose User-Agent contains a
URL** — which is a natural thing to put in one. Took a while to find.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

37 tests, no internet needed.

The valuation maths is checkable rather than just plausible. At zero growth the whole model
collapses to a simple division — cash flow divided by the discount rate — no matter how
many years you forecast. That identity catches any mistake in the discounting or the
end-of-forecast formula. The backwards solver is also checked against the forwards one at
six different growth rates, since each could be self-consistent while disagreeing with the
other.

Every test on the filings side is a real failure found against real company data, not an
imagined one.

## Running it

```bash
pip install -r requirements.txt
python -m valuation.run
```

Filings are cached, so only the first run contacts SEC. Prices are cached by date, so every
figure in one run refers to the same moment.

```
valuation/
├── config.py       every assumption, in one place
├── edgar.py        downloads filings from SEC
├── financials.py   builds cash flow history, debt, share count
├── dcf.py          the valuation maths and the backwards solver
├── market.py       current share prices
├── exhibits.py     the two charts
└── run.py
```

## What this is not

**Not a buy or sell signal.** A high assumed growth rate doesn't mean a share is
overvalued — it might be entirely achievable. Nvidia's 26% would have looked absurd in 2019
and turned out to be far too low.

It tells you what you'd have to believe. Not whether to believe it.
