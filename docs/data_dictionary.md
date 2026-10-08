# Data dictionary

Column-level documentation of the processed tables. Each stage adds its tables; the Master Guide
(Part II, Section II.5) is the specification, this file records what the code actually writes.
`{h}` stands for a horizon from `labels.horizons` (default `[20]`, so `ret_fwd_h{h}` is
`ret_fwd_h20`).

## `data/processed/{variant}/labels.parquet` (Stage S4)

Written by `python -m nasdaq100.cli build-labels`; read through `load_labels(cfg)` in
`src/nasdaq100/labels/forward_returns.py`. One row per (`ticker`, `date`), with exactly the row set
of `adjusted_prices.parquet` and `universe.parquet` (rows are never dropped). Sorted by
(`ticker`, `date`). Columns: `ticker`, `date`, then the seven columns below for each horizon, in
the order of `labels.horizons`.

**Time convention (D4).** The decision is taken at the close of day `t`. The order fills at the
adjusted open of `t+1`; the position is closed at the adjusted open of `t+1+h`. Labels use
`adj_open` only (never close-to-close, never raw prices, never adjusted price levels as features).
A label is the only place where future data appears; nothing after `t+1+h` is ever read.

| Column | Type | Definition |
|---|---|---|
| `ret_fwd_h{h}` | float64 | `ln(adj_open[t+1+h]) - ln(adj_open[t+1])` for the same ticker. NaN exactly when `has_label_h{h}` is False. Kept for ineligible rows (diagnostics only; never train or evaluate on them). |
| `excess_h{h}` | float64 | `ret_fwd_h{h}` minus the mean of `ret_fwd_h{h}` over the eligible, labelled names of the same date. **Unclipped.** NaN if the row is ineligible, unlabelled, or its date has fewer than 20 eligible labelled names. |
| `y_reg_h{h}` | float64 | `excess_h{h}` clipped, per date, at the `labels.winsor_pct` quantiles (default 1% / 99%), in raw return units (not standardised). NaN where `excess_h{h}` is NaN. |
| `y_cls_h{h}` | float64 | `1.0` if `excess_h{h} > 0`, else `0.0`; NaN where `excess_h{h}` is NaN. |
| `rank_pct_h{h}` | float64 | Per-date percentile rank of `ret_fwd_h{h}` among the same eligible, labelled names (average rank for ties); `1.0` = best. NaN where `excess_h{h}` is NaN. |
| `label_exit_idx_h{h}` | int32 | `t_idx + 1 + h`. Always populated, also beyond the end of the calendar. |
| `has_label_h{h}` | bool | `label_exit_idx_h{h}` is on the trading calendar **and** both `adj_open` prices (`t+1`, `t+1+h`) exist for the ticker. Always populated; independent of eligibility. |

**Evaluation uses `excess_h{h}` (unclipped); training uses `y_reg_h{h}` (clipped).** Never mix the
two. Cross-sectional columns are computed only over rows with `eligible == True` and
`has_label_h{h} == True`, separately for every date; no statistic is ever pooled across dates.

**Boundaries on the real dataset (2000-01-03 to 2026-02-18, 6,571 dates).** The last decision date
with `has_label_h20` is 2026-01-16 (`t_idx` 6549); the last `h+1 = 21` dates of every ticker are
unlabelled. The first decision date with cross-sectional labels is 2001-01-02 (`t_idx` 252; the
first 252 dates have no eligible name because of the seasoning rule).

**Not applied here.** The locked-test guard (decision D19: no decision date on or after
2020-01-02, no label resolving on or after it) and the dev label masking belong to S6/S16, which
must wrap `load_labels`. `labels.parquet` contains labels for all dates.

## `data/processed/{variant}/market_series.parquet` (Stage S5)

Written by `python -m nasdaq100.cli build-features`; read through `load_market_series(cfg)` in
`src/nasdaq100/features/build.py`. One row per trading date (all 6,571 dates of the calendar),
sorted by `date`.

| Column | Type | Definition |
|---|---|---|
| `date` | datetime64[ns] | Trading date. |
| `mkt_logret` | float64 | Mean of `logret_cc` on the date over the names that were **eligible at the previous trading date** (composition fixed before the return happens; names without a defined return that day are not averaged in). NaN while no name was eligible the day before (the first 253 dates on the real data: nothing is invented during seasoning). |
| `mkt_index` | float64 | Cumulative `exp` of `mkt_logret`, i.e. an equal-weight total-return index that starts at 1 just before the first defined return. NaN where `mkt_logret` is NaN. |
| `n_eligible` | int32 | Number of names eligible **on** the date itself (0 during seasoning). |

## `data/processed/{variant}/features_raw.parquet` and `features_model.parquet` (Stage S5)

Written by `build-features`; read through `load_features_raw(cfg)` and `load_features_model(cfg)`.
One row per (`ticker`, `date`) with exactly the row set of `adjusted_prices.parquet` and
`universe.parquet` (rows are never dropped), sorted by (`ticker`, `date`). Columns: `ticker`,
`date`, `eligible` (from the universe), then the stock-level features and the market-level
features of the families selected in `features.families`, in the order of the table below. With
all five families that is 18 + 6 = 24 feature columns.

- **`features_raw`**: every feature as defined below, for every row where it is computable
  (ineligible rows included, for diagnostics; never train or evaluate on ineligible rows).
- **`features_model`** (model input): for the 18 stock-level features, **per date and only among
  `eligible` rows**, each feature is clipped at the `features.winsor_pct` quantiles of that date
  (default 1% / 99%, linear interpolation) and then rank-gaussed,
  `z = Phi^-1((rank - 0.5) / n)`, with `rank` the average rank (ties share it) and `n` the number
  of non-NaN values of that feature on that date. Stock-level features of ineligible rows are NaN.
  The 6 market-level features are copied raw (no transformation) on every row.
- All windows are **trailing, in trading observations of the ticker**, and include day `t`. A
  feature is NaN unless its full window is available. `logret` is `logret_cc`. Only adjusted series
  are read; prices enter only through ratios. No feature is ever infinite: a logarithm of a
  non-positive argument (a window with zero dollar volume, zero volatility) is NaN.
- Never built: absolute price levels, calendar or seasonality features, oscillators (RSI, MACD,
  Bollinger, ATR; ablation only).

`Warm-up` is the number of leading NaN rows (stock-level: per ticker; market-level: counted from
the first date on which the market series is defined). The first row of a ticker has no
`logret_cc`, which is why the volatility and liquidity warm-ups are one longer than the window
where `logret_cc` enters.

| Family | Feature | Definition | Window | Warm-up |
|---|---|---|---|---|
| momentum | `ret_5`, `ret_21`, `ret_63`, `ret_126`, `ret_252` | `ln(adj_close_t / adj_close_{t-k})`, k = 5, 21, 63, 126, 252 | k | k |
| momentum | `mom_12_1` | `ln(adj_close_{t-21} / adj_close_{t-252})` (12-month momentum skipping the latest month) | 252 | 252 |
| volatility | `vol_21`, `vol_63` | sample std (ddof 1) of `logret` over the window x sqrt(252) | 21, 63 | 21, 63 |
| volatility | `downvol_63` | `sqrt(mean(min(logret, 0)^2) over 63) x sqrt(252)` | 63 | 63 |
| volatility | `vol_ratio_21_63` | `ln(vol_21 / vol_63)`; NaN if either is 0 | 63 | 63 |
| volatility | `parkinson_21` | `sqrt(mean(ln(adj_high / adj_low)^2 over 21) / (4 ln 2)) x sqrt(252)` | 21 | 20 |
| volatility | `beta_126` | `cov(logret, mkt_logret) / var(mkt_logret)` over 126 days (sample moments); NaN if any return in the window is missing or the market variance is (numerically) zero | 126 | 126 |
| trend | `px_sma_50`, `px_sma_200` | `ln(adj_close_t / mean(adj_close over the last 50 / 200 observations))` | 50, 200 | 49, 199 |
| trend | `dist_52w_high` | `ln(adj_close_t / max(adj_close over the last 252 observations))` (<= 0) | 252 | 251 |
| liquidity | `log_dvol_63` | `ln(mean(dollar_volume over 63))`; NaN if the mean is 0 | 63 | 62 |
| liquidity | `rel_dvol_21_63` | `ln(mean(dollar_volume, 21) / mean(dollar_volume, 63))`; NaN if either mean is 0 | 63 | 62 |
| liquidity | `amihud_63` | `ln(1 + 1e6 x mean(abs(logret) / dollar_volume over 63))`, using only days with `dollar_volume > 0`; NaN if there is none | 63 | 63 |
| market | `mkt_ret_21`, `mkt_ret_63` | sum of `mkt_logret` over the trailing 21 / 63 dates | 21, 63 | 20, 62 |
| market | `mkt_vol_21` | sample std of `mkt_logret` over 21 dates x sqrt(252) | 21 | 20 |
| market | `mkt_trend_200` | `ln(mkt_index_t / mean(mkt_index over 200 dates))` | 200 | 199 |
| market | `mkt_breadth_50` | share of eligible names on date `t` (with a defined `px_sma_50`) with `px_sma_50 > 0` | 50 | 0 |
| market | `xs_disp_21` | cross-sectional sample std (ddof 1) of `ret_21` among eligible names on date `t` | 21 | 0 |

**Notes.**

- `beta_126` uses the market series, which includes the stock itself (accepted, documented).
- Because the market series is undefined until the first name is eligible (252 observations of
  seasoning), the market features that need a window of market returns and `beta_126` are NaN for
  the first dates after the first eligible date (real data: `mkt_ret_21` from 2001-02-01,
  `mkt_ret_63` from 2001-04-03, `beta_126` from 2001-07-03, `mkt_trend_200` from 2001-10-23).
  The stock-level momentum, volatility, trend and liquidity features are available on every
  eligible row from the first eligible date 2001-01-02 (`t_idx` 252).
- Features that are exactly tied across names (for example `dist_52w_high = 0` for every name at
  its 52-week high) share one average rank, so their per-date scores have a slightly smaller
  standard deviation and a non-zero mean on such dates.
- The locked-test guard (decision D19) and the dev masking belong to S6/S16, which must wrap the
  loaders.
