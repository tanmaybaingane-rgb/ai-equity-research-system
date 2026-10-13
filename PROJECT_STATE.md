# Project State: AI-Driven Equity Research & Portfolio Decision Support System

> **Purpose:** This file is the concise, accurate handoff for the next implementation stage. `MASTER_PROJECT_BUILD_GUIDE.md` remains the authoritative specification for stage requirements. This file records what is implemented, verified, committed, known to differ from the guide, and what must happen next.
>
> **Maintenance rule:** Update this file only after the stage implementation has been tested on the project owner's local environment, committed, and pushed. Then commit and push the state-file update before starting the next stage. Do not treat assistant-sandbox test results as local verification.

## 1. Current project snapshot

- **Project:** AI-driven equity research and portfolio decision support system.
- **Repository:** <https://github.com/tanmaybaingane-rgb/ai-equity-research-system>
- **Branch:** `master`
- **Current stage:** S6 complete and pushed; **S7 has not started**.
- **Last stage implementation commit:** `ac02dbb` â€” `S6: validation framework and locked-test guard` (pushed).
- **M1 baseline/tag:** S5 commit `7e0d5ab615ca9cb65b6f3ef494ceedac2ca750c0` (`7e0d5ab` in the commit list).
- **Repository checkpoint before this state-file revision:** `dd68e3215d213b64e382a4bea6525915c8c40514` (`dd68e32`) â€” `docs: record S6 verification status`. The GitHub screenshots and the earlier local `git ls-remote` output show this checkpoint on `origin/master`.
- **Environment used for S6 verification:** Windows, Python 3.14, project `.venv`.
- **Project path used in the local workflow:** `C:\Users\Asus\Projects\ai-equity-research-system`.
- **Last updated:** 2026-10-12.

**How to interpret the commit fields:** The commit containing a future revision of this file cannot record its own final hash without requiring another documentation commit. Therefore, this file records the last stage implementation commit and the checkpoint from which this revision was prepared; use `git log -1` and `git ls-remote origin refs/heads/master` for the exact current Git head. Git is authoritative for current branch state.

## 2. Stage Checklist

| Stage | Scope | Status | Implementation commit | Verification record in this file |
|---|---|---|---|---|
| S0 | Foundations, configuration, tooling | Complete and pushed | `93f1abb` foundations; `86767bb` close-out | Implementation, conventions, and remaining caveats: Â§4.1. Historical sandbox counts are not local evidence. |
| S1 | Ingestion, validation, quality flags | Complete and pushed | `c251ae3` | Outputs, frozen-data rules, archive findings, and test inventory: Â§4.2. Historical metrics are labelled by provenance. |
| S2 | Security master and universe | Complete and pushed | `102b7c8` | Curation, eligibility rules, universe counts, and test inventory: Â§4.3. |
| S3 | Adjusted prices and returns | Complete and pushed | `bbde223` | Output schema, formulas, numerical edge-case handling, and test inventory: Â§4.4. |
| S4 | Label generation | Complete and pushed | `9dbc5ec` | Label formulas, schemas, minimum cross-section rule, and leakage implications: Â§4.5. |
| S5 | Feature engineering | Complete and pushed; M1 | `7e0d5ab` | Feature groups, normalisation, causal constraints, caveats, and known local verification summary: Â§4.6. |
| S6 | Validation folds, locked-test guard, leakage tooling | **Complete, locally verified, committed and pushed** | `ac02dbb` | Implementation, fold contracts, local verification, and deviations: Â§4.7. The previous state-documentation checkpoint is `dd68e32`. |
| S7 | Predictive evaluation library and baseline models | **Not started** | â€” | Next stage. Follow `MASTER_PROJECT_BUILD_GUIDE.md` for scope and acceptance criteria. |
| S8 | Models, tuning, calibration, walk-forward training | Not started | â€” | Milestone M2. |
| S9 | Signal engine | Not started | â€” | â€” |
| S10 | Risk layer and portfolio construction | Not started | â€” | â€” |
| S11 | Backtest engine: execution, costs, benchmarks | Not started | â€” | â€” |
| S12 | Rule-based market regimes | Not started | â€” | â€” |
| S13 | Strategy evaluation, ablations, robustness, development evidence | Not started | â€” | Milestone M3. |
| S14 | Explainability | Not started | â€” | â€” |
| S15 | Streamlit dashboard | Not started | â€” | â€” |
| S16 | Locked test and final report | Not started | â€” | Milestone M4; single controlled run. See S6 constraints in Â§4.7 and Â§5. |
| S17 | Packaging, documentation, reproducibility | Not started | â€” | â€” |

### Verification evidence policy

1. A stage's implementation being committed/pushed and that stage's local tests passing are separate facts; record both separately.
2. Record exact commands run in the owner's real Windows `.venv`, their actual outputs, and whether the frozen real archive was used.
3. **Assistant-sandbox results are not local verification.** If retained for historical context, label them explicitly as sandbox-only and keep them outside the authoritative local verification table. Sandbox use of dependency stand-ins is not equivalent to testing against the real installed dependencies.
4. Do not leave â€œrun locallyâ€, â€œpush pendingâ€, or â€œawaiting local verificationâ€ notes once that work has actually been completed. Conversely, do not mark a check passed unless its real command was run and observed.
5. Marker-specific pytest results can overlap. Never add marker-suite counts and describe the sum as a unique full-suite count unless a command explicitly measured the full suite.
6. If reliable older local logs are not available, say that detailed historic totals are unavailable rather than inventing them. This revision deliberately does not relabel old sandbox counts as local runs.

## 3. Frozen data and research constraints

### Historical archive facts

The project uses the frozen historical archive referenced by the S1 verification record:

- 514,075 daily rows.
- 100 tickers.
- 6,571 trading-calendar dates.
- Recorded date span: 2000-01-03 through 2026-02-18.
- Recorded ZIP SHA-256 begins `e70ce876` and ends `e8d2`; use the archive manifest for the full digest.
- The archive is **survivorship-biased**. This limitation is documented in `docs/survivorship.md`; do not describe the universe or results as survivorship-bias-free.

### Universe facts

- The security master has 100 tickers, with 98 included by the current curated and quality rules.
- `AZN` is excluded by curation and the whole-history zero-volume quality rule; `GOOG` is a curated exclusion linked to issuer `GOOGL`.
- `include_in_universe` is a static master/curation decision. Per-date eligibility is computed by the universe builder using the configured per-date rules. Do not replace this with a whole-history look-ahead feature or silently alter the curation decisions.
- `data/reference/security_master_curated.csv` is tracked and contains the curated exceptions.

### Pipeline sequence

| Stage | Main output / responsibility | Core implementation |
|---|---|---|
| S1 | Ingestion, manifest/hashes, calendar, silver quality flags and validation | `src/nasdaq100/data/ingest.py`, `flags.py`, `validate.py`; `src/nasdaq100/utils/calendar.py` |
| S2 | Security master and per-date eligible universe | `src/nasdaq100/data/security_master.py`, `universe.py` |
| S3 | Adjusted OHLC and close-to-close log returns | `src/nasdaq100/data/adjust.py` |
| S4 | Forward-return labels and cross-sectional labels | `src/nasdaq100/labels/forward_returns.py` |
| S5 | Registered stock and market features, raw/model feature panels and per-date normalisation | `src/nasdaq100/features/registry.py`, `stock_features.py`, `market_features.py`, `normalize.py`, `build.py` |
| S6 | Temporal folds, split guards, panel loader and leakage checks | `src/nasdaq100/validation/`, `src/nasdaq100/data/loaders.py` |

Rows are generally preserved through the pipeline; warm-up periods and unavailable forward labels are represented by NaNs/flags rather than dropping rows. Use the Master Build Guide and each module's contract for exact schemas.

## 4. Completed stage history: S0â€“S6

Use this section as the chronological record of what each completed stage introduced and which interfaces, decisions, and limitations later stages must preserve. The Master Project Build Guide remains the full specification; the repository implementation and tests are authoritative for what exists.

**Verification provenance:** the original state file mixed local checklists with assistant-sandbox test tables and stale â€œrun locallyâ€ instructions. Therefore, the summaries below preserve implementation facts and selected data observations, but do not reinterpret old sandbox results as local passes. Per-stage historical local test totals for S0â€“S4 are not reliably reconstructable from that file. S5's former record explicitly says its local lint, real-data build, leakage checks, and locally run S5 tests passed, but it did not record an aggregate test count. All future verification must be recorded from actual local command output.

### 4.1 S0 â€” Foundations and repository conventions

**Implementation checkpoints:** `93f1abb` (`S0: foundations`) and `86767bb` (`S0: close-out`), both present in the shared Git history.

**Delivered:**
- `src/nasdaq100/` package structure; working `config.py`, `paths.py`, `cli.py`, and `utils/{hashing,io,logging,seeds}.py`.
- `configs/base.yaml` and `configs/data_expectations.yaml`; package metadata and tooling in `pyproject.toml`, `Makefile`, `.gitignore`, and `.github/workflows/ci.yml`.
- README survivorship notice; decision-record template under `docs/decisions/`; header-only `experiments/registry.csv`.
- Test configuration/fixtures including `tests/conftest.py`, `tests/fixtures/toy_data.py`, and unit tests for configuration, paths, utilities, toy data, CLI and `needs_data` behaviour.

**Conventions introduced:**
- Configuration precedence is `configs/base.yaml` < `--config` < `--override`. A `--config` file is an overlay, not a replacement for the base config.
- `needs_data` tests are skipped when the real raw archive/CSV is unavailable; data-independent unit tests should still run.
- Data/artifact path helpers are variant-aware. Preserve variant namespacing and pass `cfg.project.variant` where required.
- `experiments/registry.csv` is append-only, but data-build stages do not create an experiment record merely because they built a table.
- The project reports survivorship bias explicitly; do not make bias-free-universe claims.

**Known S0 caveats still relevant later:**
- Pydantic defaults repeat values from `base.yaml`, so there are two sources of truth; a drift guard was proposed but not recorded as implemented.
- `paths.py` hard-codes the raw archive/CSV names even though `data.raw_zip` and `data.raw_csv_name` config keys exist. Do not assume those keys currently control path resolution.
- `append_registry` validates registry columns but does not enforce duplicate-run/type constraints; `write_parquet` sorting is not guaranteed stable for ties.
- Enum-like config strings are not fully validated at config load time; some stage builders validate their own accepted values.
- The `status` CLI prints this project-state file. Commands for stages not yet implemented may still be stubs that exit nonzero.
- Toy/planted fixtures were initially simpler than later modelling stages require; extend fixtures intentionally when the relevant stage calls for it.
- Local development uses Windows/Python 3.14, while the recorded CI matrix is Python 3.11 and 3.12. Compatibility of later optional packages such as LightGBM/SHAP on Python 3.14 was not established by S0â€“S6. The virtual environment was created with `--system-site-packages`, so global packages may be visible.
- A lock file, pre-commit configuration and Dockerfile were not included in S0; packaging/reproducibility belongs to S17.

**Test/infrastructure inventory and old verification record:** `tests/unit/`, the `tests/fixtures/toy_data.py` generators, and `tests/conftest.py` are the foundation for subsequent stages. The original S0 log recorded `pip install -e ".[dev]"` as passed locally, 19 baseline tests passed at the initial `93f1abb` baseline, and `python -m nasdaq100.cli status` working. The later S0 close-out table reported 24 passing tests in the assistant sandbox using dependency stand-ins; that is not a local result. A clean final Ruff run after the S0 close-out was not captured in that older record. These facts describe the historical record only; use fresh local regression checks as the current verification.

### 4.2 S1 â€” Data ingestion, validation and quality flags

**Implementation commit:** `c251ae3` (`S1: ingestion, validation, flags`).

**Delivered:**
- `src/nasdaq100/data/ingest.py`: extracts only the CSV bytes from `data/raw/archive.zip` (not a general `extractall`), validates expected columns, assigns explicit dtypes, sorts by `(ticker, date)`, creates bronze data and the trading calendar, and writes `MANIFEST.json` with file hashes. Includes `read_manifest`, `data_hash`, and the frozen-dataset guard (`FrozenDatasetError`); schema failures use `SchemaError`.
- `src/nasdaq100/data/flags.py`: builds the silver table by adding `n_obs` and five `flag_*` quality columns, and identifies potential corporate-action events. Flags are diagnostics; rows are not removed.
- `src/nasdaq100/data/validate.py`: hard schema/data checks and soft diagnostics; writes `validation_report.json` and `docs/data_quality_report.md`, including the `SURVIVOR-BIASED` disclosure. A failed hard check produces diagnostic reports, does not write silver, and exits nonzero.
- `src/nasdaq100/utils/calendar.py`: calendar construction and `TradingCalendar` methods (`idx_of`, `date_at`, `offset`, `rebalance_dates`), plus the configured rebalance-date helper.
- CLI commands `ingest` and `validate`; relevant tests include `tests/unit/test_{calendar,flags,ingest,validate,cli_s1}.py`, `tests/fixtures/s1_prices.py`, and `tests/integration/test_s1_real_data.py` (`needs_data`).

**Frozen archive facts recorded by the earlier real-archive analysis (historical measurement, not a local S1 test claim):** 514,075 rows, 100 tickers, 6,571 calendar dates, dates 2000-01-03 through 2026-02-18; ZIP SHA-256 starts `e70ce876` and ends `e8d2` (full digest belongs in the manifest). That analysis recorded zero hard-check failures, zero tickers ending early, 48,646 rows with `close < 5`, 1,594 zero-volume rows (1,459 AZN), 27 rows with absolute close returns above 40%, and GOOG/GOOGL correlation of 0.9971. Historical flag totals were 48,646 tick-noise, 1,594 zero-volume, 4,546 flat-bar, 19 corporate-action-suspect and 30 extreme-move rows. The zero-volume-share warning for AZN was expected; it was a soft warning.

**Interpretations and constraints:**
- The top-level manifest fields describe the source file (usually the ZIP); a nested CSV block records the extracted CSV's hash/size. `data_hash()` returns the ZIP hash when the manifest was created from a ZIP.
- Frozen-data validation compares the CSV hash and, for ZIP-based manifests, the ZIP hash. Re-ingesting identical data should not rewrite the manifest timestamp unnecessarily.
- `rebalance_dates(cfg, calendar)` returns `date` and `t_idx`, using configured backtest anchor/stride. The calendar defaults to the processed calendar file.
- S1 does not filter/remove rows and does not write an experiment-registry row. `make data` originally stopped at later commands until those stages were implemented.
- `Close` and `Adj Close` are rounded vendor values, so `adj_close / close` is noisy at low prices. Keep the minimum-close eligibility rule and corporate-action flags as distinct concerns; a flag is not itself a reason to silently drop a row.
- Corporate-action-suspect events include documented reference events (KDP, BKR, MDLZ, TMUS) and other possible events; they are flags for downstream interpretation, not automatic corrections.

### 4.3 S2 â€” Security master and per-date universe eligibility

**Implementation commit:** `102b7c8` (`S2: security master and universe`).

**Delivered:**
- `src/nasdaq100/data/security_master.py`: loads/validates curated exceptions and builds the security master with first/last dates, observation counts, cohort, zero-volume share, trailing dollar-volume statistic, include decision and status reason. Includes deterministic CSV writer/reader and silver-table reader.
- `src/nasdaq100/data/universe.py`: builds per-row eligibility; `load_universe(cfg)` respects the configured variant and does not silently apply an additional filter; `master_fail_by_ticker` supports diagnostics.
- `data/reference/security_master_curated.csv` is tracked. Current exceptions exclude AZN and GOOG; GOOG is linked to issuer `GOOGL`, GOOGL is class A, and stitching-suspect indicators are recorded for CCEP, KDP, WBD, LIN, BKR and MDLZ.
- `docs/survivorship.md` documents the dataset limitation, what eligibility does/does not mean, allowed research claims and the `in_index_pit` plug-in point.
- CLI commands `build-master` and `build-universe`; relevant tests include `tests/unit/test_{security_master,universe,cli_s2,survivorship_doc}.py`, `tests/leakage/test_universe_time_safety.py` (L2), `tests/fixtures/s2_silver.py`, and `tests/integration/test_s2_real_data.py` (`needs_data`).

**Counts recorded by the earlier real-archive analysis (historical context):** 100 tickers (55 `orig2000`, 45 `later`), 98 included. AZN is excluded by curation and the whole-history zero-volume quality rule; GOOG is a curated exclusion. The universe contains 514,075 rows, with 436,753 eligible (about 85%). Historical fail-reason row counts were master 9,688, seasoning 25,200, minimum-close 48,646, zero-volume 1,594 and liquidity 14,715. Under `cohort_filter=original55` (security-master cohort `orig2000`), the earlier run counted 317,109 eligible rows; this variant did not overwrite base outputs.

**Interpretations and constraints:**
- `cohort_filter` accepts `original55` and `later`, mapping to `orig2000` and `later`; invalid values raise `UniverseError` in the builder.
- `median_dollar_volume_last_year` is calculated over each ticker's last 252 observations, not by using a calendar-year slice.
- `include_in_universe` is a static security-master/curation decision and its zero-volume quality criterion uses full-history ticker data. This is deliberately documented as a limitation, not a point-in-time membership series. Per-date eligibility rules (seasoning, min close, zero volume, liquidity) are time-safe and covered by L2 tests.
- The security master is not variant-specific, but its result depends on `flags.max_zero_volume_share_ticker`; rebuild it after changing that setting. Universe outputs are variant-specific.
- Universe rows that fail eligibility stay present with `eligible=False` and `fail_*` reasons. S1 quality flags stay in silver rather than being copied into the universe schema.
- The current data do not provide a full historical point-in-time Nasdaq-100 membership history. The project must continue to disclose survivorship bias and must not overstate the universe as a fully historical membership reconstruction.

### 4.4 S3 â€” Adjusted prices and close-to-close returns

**Implementation commit:** `bbde223` (`S3: adjusted series`).

**Delivered:** `src/nasdaq100/data/adjust.py` provides `build_adjusted`, `run_build_adjusted`, `load_adjusted`, `AdjustError` and `ADJUSTED_COLUMNS`. It writes `data/processed/{variant}/adjusted_prices.parquet`; tests include `tests/unit/test_{adjust,cli_s3}.py`, `tests/leakage/test_adjusted_scale_invariance.py` (L3), and `tests/integration/test_s3_real_data.py` (`needs_data`). CLI: `build-adjusted`.

**Output schema and calculations:** `ticker, date, t_idx, adj_factor, adj_open, adj_high, adj_low, adj_close, volume, dollar_volume, logret_cc`. `adj_factor = adj_close / close`; adjusted open/high/low use the factor and vendor `adj_close` is retained as supplied; `dollar_volume = close * volume`; `logret_cc = ln(adj_close_t / adj_close_{t-1})` per ticker, NaN on each ticker's first row. `t_idx` is supplied from the calendar and must be consecutive within each ticker. S3 preserves the row set from silver; quality flags are not carried to this table.

**Numerical and pipeline decisions:**
- The builder enforces `adj_low <= adj_open, adj_close <= adj_high`. Since vendor `adj_close` can differ from `close * adj_factor` by a floating-point unit, adjusted high/low use max/min safeguards against tiny ordering violations. Values remain equal to the factor product within the documented numerical tolerance.
- Adjusted levels should not be interpreted as absolute comparable prices. S4 uses ratios of adjusted open; S5 uses adjusted-close ratios and `logret_cc`.
- The builder requires S1 silver and calendar only; it does not require the S2 universe and can run before or after `build-universe`. Output path still follows the variant.
- Invalid input (missing columns, NaN, non-positive values, duplicate keys, dates outside the calendar or non-consecutive `t_idx`) raises `AdjustError`; the CLI fails rather than silently repairing it.
- A non-unit `adj_factor` on a ticker's last date is a warning, not an automatic hard failure.

**Real-archive observations recorded by the earlier analysis (historical context):** output had 514,075 rows with keys matching the universe; exactly 100 first-row `logret_cc` NaNs were observed and none elsewhere; final-date `adj_factor` was 1.0 for every ticker; historical `logret_cc` extrema were approximately -0.833 to +0.562. Low-price rounding can make early-history close returns noisy; S2's `min_close` eligibility rule helps keep such rows out of the modelling panel.

### 4.5 S4 â€” Forward-return and cross-sectional labels

**Implementation commit:** `9dbc5ec` (`S4: label generation`).

**Delivered:** `src/nasdaq100/labels/forward_returns.py` provides `build_labels`, `run_build_labels`, `load_labels`, `label_columns` and `LabelError`; CLI: `build-labels`. Tests include `tests/unit/test_{forward_returns,cli_s4,data_dictionary_doc}.py`, `tests/leakage/test_label_poisoned_future.py` (L1), `tests/integration/test_s4_real_data.py` (`needs_data`), and `tests/fixtures/s4_labels.py`. The data dictionary documents the label schema.

**Label contract:** for each horizon `h` (default `[20]`), columns include `ret_fwd_h{h}`, `excess_h{h}`, `y_reg_h{h}`, `y_cls_h{h}`, `rank_pct_h{h}`, `label_exit_idx_h{h}` and `has_label_h{h}`. The forward return is `ln(adj_open[t+1+h]) - ln(adj_open[t+1])`; `label_exit_idx_h = t_idx + 1 + h`. A forward label exists only when the exit date is on the calendar and both required prices exist. Cross-sectional labels are computed per date over `eligible & has_label` rows: `excess` subtracts that date's eligible labelled mean, `y_reg` clips excess to date-wise quantiles, `y_cls = 1[excess > 0]`, and `rank_pct` is the average-rank percentile of `ret_fwd` (1.0 is the highest rank). Cross-sectional labels are NaN when fewer than 20 eligible labelled names exist. Rows are retained; label availability is represented through `has_label` and NaNs.

**Important constraints for S6 and later:**
- `label_exit_idx_h` is the temporal dependency boundary for purge/embargo. The label for decision date `t` uses adjusted opens at `t+1` and `t+1+h`; it does not use close-to-close labels.
- `ret_fwd` may be present on ineligible rows for diagnostics, but cross-sectional targets must only be defined for eligible, labelled rows. Do not treat a missing/unavailable label as a negative class.
- `labels.parquet` does not include `t_idx`, `eligible` or S1 quality flags; join through the calendar/universe when needed.
- S4 itself does not apply the S6 locked-test guard or dev label mask. S6 must wrap the lower-level label reader for modelling/evaluation use.
- No experiment-registry row is written because label generation is not an experiment result.

**Real-archive observations recorded by the earlier analysis (historical context):** the labels table had 514,075 rows; for `h=20`, 511,975 rows had forward returns (the trailing 21 rows per ticker lacked an exit price); 434,695 rows had cross-sectional labels; the first cross-sectional-label date was 2001-01-02; the recorded `y_cls_h20` mean was 0.5009, `excess_h20` standard deviation about 0.0853 and per-date excess means were numerically zero. The clipped regression target differed from excess on 12,596 rows in that analysis. These are historical real-archive observations, not proof of a particular current local command run.

### 4.6 S5 â€” Feature engineering and M1 labelled feature panel

**Implementation commit / milestone:** `7e0d5ab` (`S5: feature engineering`), tagged M1. Full baseline hash: `7e0d5ab615ca9cb65b6f3ef494ceedac2ca750c0`.

**Delivered:**
- `src/nasdaq100/features/registry.py`: registry for 24 MVP features, families, required-feature checks and registry validation.
- `src/nasdaq100/features/stock_features.py`: 18 trailing stock-level features, including causal two-pass beta.
- `src/nasdaq100/features/market_features.py`: six market-level features and point-in-time eligible-name market aggregates.
- `src/nasdaq100/features/normalize.py`: eligible-only, per-date winsorisation and rank-Gauss transformation, average ranks for ties.
- `src/nasdaq100/features/build.py`: orchestrates the feature build and writes raw/model feature panels and market series without dropping rows.
- CLI: `build-features`; feature definitions and columns documented in `docs/data_dictionary.md`.
- Tests cover registry, stock and market features, normalisation, orchestration, CLI/docs, real-data integration and future-poisoning/leakage cases.

**Contracts and observations:**
- All feature panels preserve the full row set; missing warm-up values remain NaN rather than being filled from future observations or causing rows to be dropped.
- Stock features use trailing/causal inputs. Market features use the names eligible at `t-1`, avoiding contemporaneous eligibility look-ahead, and date-level market values are copied to rows for that date.
- Normalisation is per date and only over eligible, non-NaN stock feature values. Average ranks handle ties.
- `features_model` holds per-date rank-Gauss-transformed model features; `features_raw` is a distinct unnormalised/raw feature panel. Do not interchange them casually or apply the same normalisation twice.
- `beta_126` and rolling market features have natural warm-up NaNs. The first modelling stage that needs finite input values must state its feature/row eligibility policy explicitly.
- Market-level series may be NaN before the first eligible market composition exists; `mkt_index` is based on cumulative `mkt_logret` and remains NaN while that return is unavailable. The implemented column is `n_eligible` (some guide wording calls it `n_eligible_t`).
- Standard deviations use sample (`ddof=1`) behaviour. `beta_126` needs a full return window and non-zero market variance. Invalid log arguments result in NaN rather than infinity.
- S5 includes dedicated leakage tests, but the general `check-leakage` CLI and locked-test framework belong to S6. S5 does not open/protect the locked test set, does not alter the survivorship limitation, and does not write an experiment registry row.

**Verification provenance:** the older state explicitly recorded that locally run S5 tests passed, a real-data feature build passed, the leakage tests passed, `ruff check .` passed and `git diff --check` passed. It did not preserve exact command totals. Keep those qualitative results, but do not invent an aggregate S5 test count.

**M1 meaning:** S5 established the clean labelled feature panel needed as the starting point for predictive evaluation. S6 adds temporal validation and guarded panel access on top of this M1 baseline.


### 4.7 S6 â€” Validation folds, locked-test guard, and leakage tooling

**Baseline:** M1, S5 commit `7e0d5ab615ca9cb65b6f3ef494ceedac2ca750c0`.

**Implementation commit:** `ac02dbb` â€” `S6: validation framework and locked-test guard` (pushed to `origin/master`). The documentation checkpoint prepared for this revision is `dd68e32` â€” `docs: record S6 verification status`. The exact head advances when this revised state file is committed; use Git to confirm the newest hash.

**Delivered:**
- `src/nasdaq100/validation/folds.py`: `Fold`, `make_fold`, `make_dev_folds`, `make_tuning_folds`, `make_locked_folds`, `build_fold_plan`, `write_fold_plan`, `purge_gap`, and `year_bounds`.
- `src/nasdaq100/validation/guards.py`: `LockedTestError`, `assert_not_locked`, `open_locked_test`, `require_token`, `is_valid_token`, access tokens, protocol logging, and boundary helpers.
- `src/nasdaq100/validation/leakage.py`: `assert_folds_valid`, `poison_future`, the `null_panel_test` scaffold for later model validation, `SpyEstimator`, and `run_leakage_suite`.
- `src/nasdaq100/data/loaders.py`: `build_panel` and the supported `load_panel(cfg, features, split, labels=True, ...)` API for assembling split-safe feature/label panels.
- `src/nasdaq100/cli.py`: `check-leakage`, which writes a fold plan and runs `pytest -m leakage` from the repository root.
- Tests in `tests/unit/test_{folds,guards,loaders,leakage_tools,cli_s6}.py`, `tests/leakage/test_{fold_validity,dev_label_masking,locked_guard}.py`, and `tests/integration/test_s6_real_data.py`; fixtures in `tests/fixtures/s6_validation.py`. The `docs/data_dictionary.md` documents the panel and fold plan.

**Temporal boundaries verified against the project's real calendar:**

| Boundary | Current reference value |
|---|---|
| Locked-test start | `t_idx = 5031`, date `2020-01-02` |
| Last development decision date | `t_idx = 5030`, date `2019-12-31` |
| Last development decision index with an available 20-trading-day label | `t_idx = 5009`, date `2019-11-29` |
| Tuning cap | `t_idx = 1988`, date `2007-11-29` |
| First training index under current configuration | `252` |
| Current configured purge/embargo gap | `26` trading-calendar indices |

- `make_dev_folds` creates 12 development folds for test years 2008â€“2019.
- `make_tuning_folds` creates three folds for 2005â€“2007 without a calibration block; the final tuning fold is capped at `t_idx = 1988`.
- The locked range spans 2020â€“2026, represented as seven locked folds. These folds are not listed in the ordinary development/tuning fold-plan output.
- The locally inspected `dev_2008` plan showed `train_end_idx = 1983`, `gap = 26`, 241 sampled core dates, and 101 sampled calibration dates with the current stride. Treat these values as regression references for the present configuration, not constants for generic fold logic.

**Loader and leakage contracts:**
- Fold boundaries are defined on calendar `t_idx`. Fold builders use the configured calendar, horizon, gap, train stride, calibration settings, and window settings; do not replace this with row-count splits.
- S7 and later modelling/evaluation code must read features and labels through `load_panel` and use the S6 folds. The lower-level S4/S5 readers still exist and are not themselves guarded; do not use them directly in new modelling/evaluation code.
- `split="dev"` and `split="tuning"` enforce their temporal boundaries. In dev mode, true target fields (`ret_fwd`, `excess`, `y_reg`, `y_cls`, `rank_pct`) are masked beyond `t_idx = 5009`, and `has_label` is false there. `label_exit_idx_h20` remains an integer dependency index and is not price information.
- `split="locked"` requires a valid token. `open_locked_test` checks the frozen-data configuration and records the opening event in the protocol. **Do not access/open locked-test data during S7â€“S15.** The deliberate open procedure belongs to S16.
- Evaluate only rows with valid labels (`has_label`); predictions may exist for eligible decision rows whose future labels are unavailable/masked. Unlabelled rows are not negative labels and are not valid evaluation observations.
- `null_panel_test` is a scaffold for S8: its intended pipeline result includes `ic_by_date` and may include `auc`. S8 must implement the guide's full null-panel acceptance criteria rather than assuming the scaffold alone proves validity.

**Local verification on the Windows `.venv` (Python 3.14), against the real project archive:**

| Command/check | Observed result |
|---|---|
| `python -m pytest -m "not needs_data and not slow"` | **411 passed, 62 deselected** |
| `python -m pytest -m leakage` | **169 passed, 304 deselected** |
| `python -m pytest -m needs_data` | **62 passed, 411 deselected** |
| `python -m nasdaq100.cli check-leakage` | Passed; fold plan was generated and the CLI leakage-test step returned successfully. |
| `Test-Path .\artifacts\base\fold_plan.json` | `True`; the expected variant-namespaced file existed. |
| `ruff check .` | Passed. |
| `git diff --check` | Passed. |
| `git apply -R --check ..\S6-validation-framework.patch` | Passed; the patch could be reversed cleanly as a check. The patch was not reversed. |

**Counting note:** These marker queries can select overlapping tests. Do not add their counts and present the sum as a unique total. A fully unfiltered suite run and the `slow` tests are not recorded as run for S6.

**Known S6 deviations and limitations:**
1. **Fold-plan path mismatch:** the CLI uses `paths.fold_plan_path(variant)`, so the base-variant output is `artifacts/base/fold_plan.json`. The guide and `.gitignore` refer to `artifacts/fold_plan.json`. This discrepancy is known and documented; do not silently claim the paths match or change this convention incidentally during S7.
2. **Process-local tokens:** the locked-test token registry is process-local. It is a deliberate-access guard with protocol logging, not a cryptographic barrier against a determined user.
3. **Structural allow-list:** the current structural tests restrict use of `open_locked_test` to `src/nasdaq100/validation/guards.py`. S16 must intentionally extend the allow-list for its approved locked-test command; S7â€“S15 must not.
4. **Unchanged lower-level readers:** S6 did not rewrite `load_labels`, `load_features_model`, `load_features_raw`, or `load_universe` into guarded APIs. `load_panel` is the supported modelling/evaluation entry point.
5. **CLI scope:** `check-leakage` runs `python -m pytest -m leakage -q` in a subprocess from the repository root. Its successful local run is recorded above; the old sandbox log did not independently verify the pytest subprocess half.
6. **Warm-up features:** `beta_126` and rolling market features have legitimate warm-up NaNs. S7/S8 must explicitly follow the guide's policy for finite model inputs and evaluation samples; do not silently fill them with future-informed data.

**Observations for later stages:**
- Development predictions may be generated on eligible decision rows in each test year, including December 2019 rows whose forward labels are masked. Evaluation uses only valid labels. Development evaluation/backtest results must not treat decisions after `t_idx = 5009` as having observed 20-trading-day outcomes.
- Fold training blocks define decision dates; the later trainer selects `eligible & has_label` observations within those blocks. `Fold.base_rate` is populated at fit time in S8.
- S6 added only the `check-leakage` CLI implementation and panel/fold documentation to already-existing areas. The recorded S6 change did not intentionally change S0â€“S5 data schemas or pipeline behavior.

---

## 5. Implementation contracts and known deviations

### Rules for all work from S7 onward

- `MASTER_PROJECT_BUILD_GUIDE.md` is the specification for stage scope, design, schemas, and acceptance criteria; this file is a status/handoff record, not a substitute for the guide.
- Implement **only the requested stage** in a stage patch. Do not implement parts of later stages early or change earlier-stage behavior unless the guide explicitly requires it and the change is documented.
- S7 and later must read feature/label panels via `src/nasdaq100/data/loaders.py::load_panel` and use the S6 fold definitions. Do not directly use the unguarded lower-level feature/label readers in new modelling/evaluation code.
- Do not access locked-test data during S7. Do not call or import `open_locked_test` from S7 or other pre-S16 code.
- Evaluate only rows with valid labels (`has_label`); predictions may be generated for eligible decision rows even when their future labels are masked. Do not mistake unlabeled rows for negative labels or valid evaluation observations.
- Treat warm-up NaNs in `beta_126` and rolling market features explicitly; do not silently fill them with future-informed values. If a minimum-feature/row eligibility policy is required, follow the stage specification and document the policy.
- Keep variant-specific outputs variant-namespaced using the existing helpers in `src/nasdaq100/paths.py` unless a later stage explicitly changes the convention.
- The raw archive's survivorship limitation must remain visible in reports and claims.

### Known deviations or limitations to preserve/document

1. **Fold-plan path mismatch:** `check-leakage` currently writes via `paths.fold_plan_path(variant)` to `artifacts/{variant}/fold_plan.json` (for the base variant, `artifacts/base/fold_plan.json`). The guide and `.gitignore` refer to `artifacts/fold_plan.json`. This deviation is known and documented; do not silently claim the paths are identical or change them incidentally during S7.
2. **Process-local locked-test token:** S6 token validation is a deliberate-access guard, not a cryptographic security boundary. The token is valid only in the issuing process; opening the test is logged in the protocol. S16 owns the controlled locked-test workflow and any rerun bookkeeping.
3. **Structural allow-list:** Current structural checks limit `open_locked_test` usage to `src/nasdaq100/validation/guards.py`. S16 must intentionally extend the allow-list for the approved locked-test command; pre-S16 stages must not.
4. **Lower-level readers:** The S4/S5 lower-level loaders still exist for pipeline/building-block uses and are not themselves guarded. `load_panel` is the only supported entry point for modelling/evaluation code from S7 onward.
5. **Warm-up rows:** The first training period may contain NaNs in rolling/market features. The stage requiring model fitting must make its missing-feature policy explicit instead of assuming those values are all finite.
6. **Configuration/environment:** The local development environment uses Python 3.14; the project's CI matrix recorded in the earlier state was Python 3.11 and 3.12. Compatibility of packages that may be needed in later stages (for example, LightGBM/SHAP on Python 3.14) has not been established by S6.
7. **Earlier-stage verification detail:** The previous version of this file contained inconsistent â€œlocally verifiedâ€ checklist statuses next to â€œlocal pendingâ€ rows and old sandbox test results for S0â€“S4. Those stale claims are intentionally not carried forward as evidence. Implementation commit history is retained; exact historical local totals should only be added if supported by actual local logs.

## 6. Important project files and commands

| Path | Purpose / status |
|---|---|
| `MASTER_PROJECT_BUILD_GUIDE.md` | Authoritative stage plan and requirements. Read the full S7 section before planning or implementing S7. |
| `PROJECT_STATE.md` | This living implementation status and handoff. |
| `configs/base.yaml` | Default configuration. |
| `src/nasdaq100/config.py` | Configuration loading and hashing. |
| `src/nasdaq100/paths.py` | Variant-namespaced artifact/data paths. |
| `src/nasdaq100/cli.py` | CLI entry point; includes `status`, S1â€“S6 data commands and `check-leakage`. Commands for later stages may still be stubs. |
| `src/nasdaq100/data/loaders.py` | S6 `load_panel` and panel builder; required for S7+ modelling/evaluation reads. |
| `src/nasdaq100/validation/folds.py` | Fold and fold-plan logic. |
| `src/nasdaq100/validation/guards.py` | Locked-test guard and protocol/token operations. |
| `src/nasdaq100/validation/leakage.py` | Leakage-validation helpers. |
| `docs/data_dictionary.md` | Column-level documentation for processed tables, features, labels, panel and fold plan. |
| `docs/survivorship.md` | Survivorship evidence and claims policy. |
| `data/reference/security_master_curated.csv` | Tracked hand-curated security-master exceptions. |
| `tests/` | Unit, leakage and integration tests. `needs_data` tests exercise the real local archive; check the marker before interpreting test totals. |
| `experiments/registry.csv` | Append-only experiment registry; header-only so far. Data build stages have not added rows. |

Useful verified CLI commands as of S6:

```powershell
python -m nasdaq100.cli status
python -m nasdaq100.cli ingest
python -m nasdaq100.cli validate
python -m nasdaq100.cli build-master
python -m nasdaq100.cli build-universe
python -m nasdaq100.cli build-adjusted
python -m nasdaq100.cli build-labels
python -m nasdaq100.cli build-features
python -m nasdaq100.cli check-leakage
```

Run commands from the repository root with the intended virtual environment activated. Some later-stage commands are expected to remain stubs until their stage is implemented.

## 7. Standard stage workflow (repeat for every stage)

### Before asking Claude for the next stage

1. Confirm the latest branch state locally. Use `git status -sb`, `git log -1 --oneline`, and fetch/compare with `origin/master` as appropriate. Start from a clean working tree and the latest pushed commit.
2. Provide Claude the current `MASTER_PROJECT_BUILD_GUIDE.md`, this `PROJECT_STATE.md`, and the intended stage handoff/archive. State explicitly which stage is in scope and which future stages are out of scope.
3. Ask for a patch against the provided committed base. Do not let the patch describe sandbox results as owner-local test results.

### After receiving and applying the stage patch locally

1. Review the patch/stat and apply it to the clean branch.
2. Run the required tests and CLI checks locally in the real `.venv`, including relevant `needs_data` integration tests when the real archive is available, leakage tests, Ruff, and `git diff --check`. Capture the actual commands and final output. Run additional tests required by the stage guide.
3. Fix failures before treating the stage as complete. Update `PROJECT_STATE.md` locally with **observed** verification evidence only; no guessed or copied sandbox counts.
4. Commit and push the stage implementation. Verify the push and remote branch state. Record the stage implementation commit hash in the state file.
5. Make the final documentation-only update to `PROJECT_STATE.md`, reconcile outdated earlier-stage statuses/next steps, then commit and push that documentation update before starting the next stage.
6. Read the final state file from the pushed branch before creating the next stage handoff. Git history, not a hard-coded â€œcurrent HEADâ€ field in this file, is the source of truth for the latest hash.

### What the stage verification table should contain

For each stage, record only relevant checks and distinguish these fields:

- **Command/check** (exact spelling and marker).
- **Observed result** (exact count/status).
- **Environment/data** (real local `.venv`, Python version, frozen archive used where applicable).
- **Stage implementation commit** and whether the push was confirmed.

Do not copy the whole assistant-sandbox test table into the main project state. If a sandbox result is useful for historical context, place it in a separate clearly labelled note and never use it as evidence that the owner's local checks passed.

## 8. Exact next step: prepare S7

1. Replace the repository's `PROJECT_STATE.md` with this version and review the diff. Run `git diff --check` after copying it into the working tree.
2. Commit and push this documentation update (for example, commit message `docs: reconcile project state before S7`). This documentation commit will naturally become the latest `master` commit; do not add another commit solely to place that documentation commit's own hash inside itself.
3. Verify that the documentation push succeeded and that local `master` matches `origin/master`.
4. Build the S7 handoff from the latest pushed tree, including `MASTER_PROJECT_BUILD_GUIDE.md` and this `PROJECT_STATE.md`, while excluding `.git`, `.venv`, and generated outputs not needed for implementation. Follow the project's established handoff convention for the local raw archive.
5. Begin **S7: Predictive evaluation library and baseline models** only. Read the guide's S7 section in full. Preserve S0â€“S6, use S6 folds and `load_panel`, do not open locked-test data, and do not implement S8+ work.
6. After S7 implementation, run its local checks against the real environment/data, commit and push the implementation, then update and push this file with the actual S7 result before moving to S8.

