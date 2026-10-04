# Survivorship: evidence, allowed claims and the point-in-time plug-in point

> **Every result produced from this dataset is `SURVIVOR-BIASED`.** The label is mandatory in
> reports, the README and the dashboard (Master Guide Decision D1). The universe rules of
> Stage S2 reduce some hindsight effects but **do not cure survivorship bias**.

## 1. Evidence (measured on the frozen dataset)

Source: Master Guide Part I section I.3. The points marked (re-checked) were re-measured on
`prices_silver.parquet` when S2 was built; the full set is reproduced by `needs_data` tests and by
`docs/data_quality_report.md`.

- All 100 tickers end on 2026-02-18: no delistings, no acquisitions, no bankruptcies (re-checked:
  0 tickers end before the global last date).
- All 55 tickers present on 2000-01-03 have a positive total return to 2026; the weakest compound
  growth rate is about 2.4% a year (INTC) (re-checked).
- The file matches no single-date Nasdaq-100 membership. It contains the six names removed
  effective 22 December 2025 (BIIB, CDW, GFS, LULU, ON, TTD) and none of the six added (ALNY, FER,
  INSM, MPWR, STX, WDC) (re-checked). It also lacks MSTR, AXON, CSCO and CSX.
- Several tickers appear to carry stitched predecessor-company histories (CCEP, KDP, WBD, LIN, BKR,
  MDLZ). This is inferred, not verified; they are marked `stitching_suspect` in the curated file.

**Consequence.** Absolute returns, base rates and SELL/AVOID-signal validation are optimistic or
unreliable because the loser tail is missing and names entered the file with hindsight. Relative
comparisons between models on identical data, dates and folds are more robust.

## 2. What the S2 universe does and does not do

Eligibility of (ticker, date) is decided in one place (`data/universe.py::build_universe`) from
information dated on or before that date:

| Rule | Column | Purpose |
|---|---|---|
| Ticker allowed by the security master (curated exclusions, zero-volume quality rule, optional cohort filter, optional stitched-name drop) | `fail_master` | Remove duplicate share class and illiquid non-representative series |
| More than 252 own observations | `fail_seasoning` | Reduce the hindsight of very recent listings |
| Split-adjusted `close >= 5.0` | `fail_min_close` | Data-quality mask for price quantisation (known compromise C10) |
| `volume > 0` | `fail_zero_volume` | Remove non-trading days |
| Trailing 63-observation median dollar volume `>= $1M` (NaN fails) | `fail_liquidity` | Remove illiquid history |

It does **not**: add the names that left the index, restore the missing delisted losers, or make the
list of 2026-era survivors a point-in-time membership. Rows are flagged, never deleted: ineligible
rows stay in `universe.parquet` with their `fail_*` reasons.

### Known limitations of the curation layer

1. **`include_in_universe` is a static, whole-history decision.** The zero-volume quality rule uses
   each ticker's full-history `zero_volume_share`, and the curated exclusions (AZN, GOOG) were chosen
   by looking at the whole file. This is by specification and is a deliberate curation step, not a
   per-date rule. Today only AZN (34.1% zero-volume days) is affected by the quality rule. The
   per-date rules in the table above are time-safe and covered by the leakage test L2.
2. **Descriptors are not rules.** `first_date`, `last_date`, `n_obs` and
   `median_dollar_volume_last_year` in `security_master.csv` describe the whole history for reports.
   The universe builder never reads them (a unit test tampers with them and checks the output is
   identical).
3. **The $5 mask uses the split-adjusted price,** which reflects future splits, so it removes early
   rows of later heavy splitters (C10). The threshold is configurable (`universe.min_close`) and its
   sensitivity is a Stage S13 robustness item.
4. **Cohort and stitching variants** (`universe.cohort_filter`, `universe.drop_stitched`) change the
   universe and must be run under a separate `project.variant` so base artifacts are never
   overwritten. `cohort_filter: original55` selects the 55 tickers whose first date is 2000-01-03
   (`cohort = orig2000` in the security master).

## 3. Claims policy (Master Guide section IV.4)

| May say | Must not say |
|---|---|
| "A leakage-controlled research pipeline evaluated on a fixed universe of 2026-era large-cap Nasdaq survivors" | "Would have beaten the Nasdaq-100" |
| "Model X ranks stocks better than baseline Y on identical data, dates and folds (interval shown)" | "Achieves N% annual return" as a historical fact about investable performance |
| "Results survive costs up to Z bps and a top-contributor-removal/cohort stress test" | "SELL/AVOID signals avoid real losers" (the loser tail is missing) |
| "The signal rules reduced turnover/drawdown within this universe (intervals shown)" | "The historical backtest predicts future performance" |
| "The model did not reliably beat simple baselines" (when true) | Presenting a positive dev or locked result as proof of skill |

Mandatory in every report: the `SURVIVOR-BIASED` label; the dev-versus-locked label; data hash and
config hash; number of trials; effective number of independent windows; cost assumptions stated as
assumptions; intervals next to every headline metric; and the statement that results are simulations
and not investment advice.

## 4. Plug-in point for point-in-time membership (Advanced track A1)

If a point-in-time, delisting-inclusive dataset becomes available, it enters at exactly one place:

1. A provider supplies a table keyed by (`ticker`, `date`) with one boolean, `in_index_pit`
   (True when the ticker was an index member on that date, using information available on that date).
2. `build_universe` merges it and sets `eligible = not any(fail_*) and in_index_pit`.
   `in_index_pit` would be recorded next to the `fail_*` columns, which is a schema change that
   requires a Master Guide update first.
3. Nothing downstream changes: labels, features, validation and the backtest read `eligible` only
   through `load_universe`.

Until then no code in this repository reads or assumes `in_index_pit`.

## 5. Where things live

| Item | Location |
|---|---|
| Hand-curated exceptions (tracked) | `data/reference/security_master_curated.csv` |
| Derived security master | `data/reference/security_master.csv` (`python -m nasdaq100.cli build-master`) |
| Universe table | `data/processed/{variant}/universe.parquet` (`python -m nasdaq100.cli build-universe`) |
| Single access point for later stages | `nasdaq100.data.universe.load_universe(cfg)` |
| Data-quality report | `docs/data_quality_report.md` (generated by S1) |
