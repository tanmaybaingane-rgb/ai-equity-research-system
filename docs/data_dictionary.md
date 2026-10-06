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
