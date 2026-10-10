# Project State: AI-Driven Equity Research & Portfolio Decision Support System

Living progress log (Master Project Build Guide §II.6). Updated at the end of every stage.

*Last updated:* 2026-10-11 (S6 locally verified; ready for commit review)
*Git baseline:* 7e0d5ab "S5: feature engineering" (tag M1, branch master, remote origin)
*Active environment:* Windows, Python 3.14 virtual environment (.venv), project folder under OneDrive

---

## Stage Checklist

| Stage | Name | Status | Completed | Commit | Notes |
|:---|:---|:---:|:---:|:---:|:---|
| **S0** | Foundations (repository, configuration, tooling) | ? Done (local) | 2026-10-03 | `86767bb` | Initial foundations in `93f1abb`; close-out in `86767bb`. CI not run (no remote). See S0 log. |
| **S1** | Data ingestion, validation and quality flags | ? Done (local) | 2026-10-04 | `c251ae3` | Locally verified with the real archive and dependencies. See S1 log. |
| **S2** | Security master and universe (eligibility) layer | ? Done (local) | 2026-10-04 | `102b7c8` | Locally verified with the real archive and dependencies. See S2 log. |
| **S3** | Adjusted price series and returns | ? Done (local) | 2026-10-04 | `bbde223` | Locally verified with the real archive and dependencies. See S3 log. |
| *S4* | Label generation | 🟢 Done (local) | 2026-10-06 | 9dbc5ec | Locally verified with the real archive and dependencies. |
| *S5* | Feature engineering (stock-level, market-level, normalisation) | 🟢 Implemented and locally verified | 2026-10-08 | 7e0d5ab | Feature registry, stock/market features, per-date normalisation, CLI, docs and leakage/integration tests. Milestone M1 (clean labelled panel). |
| **S6** | Validation framework (splits, locked-test guard, leakage tooling) | 🟢 Implemented and locally verified | 2026-10-10 | - | Baseline M1 (`7e0d5ab615ca9cb65b6f3ef494ceedac2ca750c0`). Locally verified on Windows .venv: 411 regular tests, 169 leakage tests and 62 real-data tests passed. The check-leakage CLI generated the fold plan; Ruff and git diff --check passed. Ready for commit review.|
| **S7** | Predictive evaluation library and baseline models | Not started | - | - | - |
| **S8** | Models, tuning, calibration and walk-forward training | Not started | - | - | Milestone M2 |
| **S9** | Signal engine | Not started | - | - | - |
| **S10** | Risk layer and portfolio construction | Not started | - | - | - |
| **S11** | Backtest engine (execution simulation, costs, benchmarks) | Not started | - | - | - |
| **S12** | Rule-based market regimes (reporting lens) | Not started | - | - | - |
| **S13** | Strategy evaluation, ablations, robustness and dev evidence package | Not started | - | - | Milestone M3 |
| **S14** | Explainability | Not started | - | - | - |
| **S15** | Streamlit dashboard | Not started | - | - | - |
| **S16** | Locked test and final report | Not started | - | - | Milestone M4 (single run) |
| **S17** | Packaging, documentation and reproducibility check | Not started | - | - | - |

---

## Stage Log

### S0: Foundations: done (local)

**Delivered (all present in the repository):**
- Package skeleton `src/nasdaq100/` with all sub-packages as empty stubs; working modules: `config.py`, `paths.py`, `cli.py`, `utils/{hashing,io,logging,seeds}.py`.
- `configs/base.yaml` (matches guide §II.4 key-for-key) and `configs/data_expectations.yaml` (verified dataset facts, §I.3).
- `pyproject.toml` (runtime deps, `dev` and `notebooks` extras, pytest markers, ruff config), `Makefile`, `.gitignore`, `.github/workflows/ci.yml`, `README.md` (survivorship notice), `docs/decisions/0000-template.md`, header-only `experiments/registry.csv`.
- Tests: `tests/conftest.py` (fixtures and the `needs_data` auto-skip hook), `tests/fixtures/toy_data.py` (`make_toy_prices`, `make_planted_signal_panel`, `make_null_panel`), unit tests for config, paths, utils, toy data, CLI and the conftest hook.

**Verification record:**

| Check | Result | Note |
|---|---|---|
| `pip install -e ".[dev]"` | ✅ Passed | Run locally by the project owner |
| `pytest -m "not needs_data and not slow"` | ✅ 19 passed (baseline commit `93f1abb`) | Close-out patch adds new tests; see below |
| `python -m nasdaq100.cli status` | ✅ Works | Prints this file |
| Ruff | 🟡 4 auto-fixable findings were fixed | A clean final run was not captured |
| `make test` | ⏳ Not run | GNU `make` may be unavailable on Windows. Guide §0.4.2 makes `make` optional; the direct pytest command is the accepted equivalent. |
| CI (GitHub Actions) | ⏳ Not run | No GitHub remote yet. CI matrix is Python 3.11 and 3.12. |
| Close-out patch: pytest | 🟡 24 passed (19 baseline + 5 new) in the assistant's sandbox | Run with the real pytest 9.1.1 but with **stand-ins** for pydantic and the parquet engine (their native wheels were unavailable offline). The stand-ins were calibrated: the pristine baseline `93f1abb` also gives 19/19 there. **Must be re-run locally with the real dependencies**: `pytest -m "not needs_data and not slow"`; record the result here. |
| Close-out patch: Ruff | ⏳ Not run | Ruff was unavailable in the sandbox. A best-effort static check of the E/W/F/I/B/UP families found and fixed one issue (W391 in `test_cli.py`). **Run `ruff check .` locally and record the result.** |

**S0 close-out patch (2026-10-03). Four narrowly scoped fixes:**
1. **`--config` layering.** `--config` is now an *override* file layered over `configs/base.yaml` (precedence: base < `--config` < `--override`), as the guide specifies. Previously the CLI passed it as the base config, so `base.yaml` was ignored. New helper `build_config_from_args` in `cli.py`; regression tests in `tests/unit/test_cli.py`.
2. **Tracked `egg-info`.** `*.egg-info/`, `build/`, `dist/` added to `.gitignore`; `src/nasdaq100.egg-info/` removed from the Git index (files remain on disk).
3. **`needs_data` auto-skip hook** (guide §II.7). `tests/conftest.py` skips `needs_data` tests when neither `data/raw/archive.zip` nor `data/raw/NASDAQ100_Historical_Data.csv` exists. Tests: `tests/unit/test_conftest_hooks.py`.
4. **This file** rewritten to match the repository (the previous version was written before the baseline commit and still said "no commit"; it also used wrong milestone labels).

**Deviations from the guide and open items (none block S1):**
1. `config.py` repeats every `base.yaml` default inside the pydantic classes (two sources of truth). They match today; a drift-guard test comparing `Config()` defaults to `base.yaml` would be a cheap safeguard.
2. `new_run_id(stage, name, config_hash)` takes the hash string rather than `cfg` (avoids a circular import; acceptable).
3. `append_registry` validates columns only (no duplicate `run_id`, `split` or type checks), as the guide specifies.
4. `paths.py` hard-codes `archive.zip` and the CSV name, so the config keys `data.raw_zip` and `data.raw_csv_name` are currently unused; path helpers take `variant` as an explicit argument (default `"base"`), so callers must pass `cfg.project.variant`.
5. `write_parquet` sort is not stable (matters only for ties); config does not validate enum-like strings (`fill`, `weighting`, `calibration.method`, `cohort_filter`).
6. `cli status` prints the whole file; unimplemented commands exit with code 1.
7. Fixtures are lighter than later stages need: the planted/null panels use `feature_1`/`feature_2` and lack `rank_pct_h20`, `label_exit_idx_h20`, the 24 MVP feature names and market-level features; the toy `AZN` series has `adj_close/close ≠ 1` on its last date. Extend before S6/S8 (not S1).
8. Environment: Python 3.14 (CI covers 3.11/3.12 only); the venv was created with `--system-site-packages` (global packages can leak in); the project lives under OneDrive. LightGBM/SHAP wheel availability on 3.14 is unverified (matters in S8/S14).
9. Not present (not required by the S0 spec): `requirements-lock.txt`, `.pre-commit-config.yaml`, `Dockerfile` (S17).

### S1: Data ingestion, validation and quality flags: implemented (awaiting local verification)

**Delivered:**
- `src/nasdaq100/data/ingest.py`: extract CSV from `data/raw/archive.zip` (CSV bytes only, no `extractall`), SHA-256 of zip and CSV, `MANIFEST.json`, frozen-dataset guard (`FrozenDatasetError`), exact-column check (`SchemaError`), explicit dtypes, rename per §II.1, sort by (`ticker`,`date`), bronze + calendar parquet. Helpers `read_manifest`, `data_hash`.
- `src/nasdaq100/data/flags.py`: `add_flags` (silver = bronze + `n_obs` + 5 `flag_*`), `corp_action_events`. Rows are never removed.
- `src/nasdaq100/data/validate.py`: 9 hard checks (schema/dtypes, NaN, duplicates, sort order, prices > 0, 3 OHLC checks, internal calendar gaps), soft checks (dimensions vs `data_expectations.yaml`, survivorship indicator, zero-volume, tick noise by year, largest returns, GOOG/GOOGL correlation), `validation_report.json`, `docs/data_quality_report.md` (`SURVIVOR-BIASED` statement), `run_validate`.
- `src/nasdaq100/utils/calendar.py`: `build_calendar`, `TradingCalendar` (`idx_of`, `date_at`, `offset`, `rebalance_dates`), module-level `rebalance_dates(cfg, calendar)`.
- CLI: `ingest` and `validate` commands (config is still validated first; errors exit 1).
- Tests: `tests/unit/test_{calendar,flags,ingest,validate,cli_s1}.py`, `tests/fixtures/s1_prices.py` (clean generator that triggers no flag), `tests/integration/test_s1_real_data.py` (`needs_data`). Three existing tests in `tests/unit/test_cli.py` used `ingest` as the "unimplemented command" example; they now use `build-master`.

**Measured on the real archive (all match guide section I.3 / `data_expectations.yaml`):** 514,075 rows; 100 tickers; 6,571 calendar dates; 2000-01-03 to 2026-02-18; zip SHA-256 `e70ce876...e8d2`; 0 hard-check failures; 0 tickers end early (survivorship); `close < 5` rows 48,646; zero-volume rows 1,594 (AZN 1,459); 27 rows with |close return| > 40%; GOOG/GOOGL correlation 0.9971; `flag_corp_action_suspect` fires on KDP 2018-07-10, BKR 2017-07-05, MDLZ 2012-10-02, TMUS 2013-05-01. Flag totals: tick_noise 48,646; zero_volume 1,594; flat_bar 4,546; corp_action_suspect 19; extreme_move 30. Only soft warning: `zero_volume_share_by_ticker` (AZN), as expected.

**Verification record:**

| Check | Result | Note |
|---|---|---|
| Baseline (S0 close-out tree) in the assistant's sandbox | 24/24 passed | Calibration of the stand-ins below |
| `pytest -m "not needs_data and not slow"` (sandbox) | 77 passed | 24 baseline + 53 new |
| `pytest -m needs_data` (sandbox, real archive) | 13 passed | Full tree: 90 passed, 0 failed |
| `python -m nasdaq100.cli ingest` / `validate` (sandbox, real archive) | Works; re-ingest is idempotent | Isolated copy of the repo layout |
| Mutation checks | 5/5 caught | Corp-action guard, strict `<` tick threshold, frozen guard, gap check, rebalance anchor |
| Ruff | Not run | Unavailable offline. AST check for unused imports/variables found nothing. **Run `ruff check .` locally.** |
| **Local run with real dependencies** | Pending | Sandbox used **stand-ins** for pydantic, the parquet engine (pickle) and pytest (mini runner) because wheels were unavailable offline; pandas 3.0.2, Python 3.12. **Re-run locally and record here.** |

**Interpretations of the guide (none change a schema):**
1. `MANIFEST.json` top-level keys are exactly the section II.5 columns and describe the **zip** (`file_name`, `sha256`, `size_bytes`); an extra `csv` block holds the CSV's name, hash and size. `data_hash()` returns the zip hash. If only the CSV exists (no zip), the top-level entry describes the CSV.
2. Frozen guard compares the CSV hash always and the zip hash when the manifest was written from a zip. Re-ingesting identical data leaves the manifest (and `created_at`) untouched.
3. `rebalance_dates(cfg, calendar=None)` returns a DataFrame (`date`, `t_idx`) and takes the anchor/stride from `cfg.backtest`; the calendar defaults to `calendar.parquet`.
4. On a hard-check failure `validate` still writes the (failed) JSON and markdown reports for diagnosis, does **not** write silver, and exits 1.
5. `run_ingest` / `run_validate` accept optional explicit paths (default: `nasdaq100.paths` helpers) so tests run in temp directories. S0 deviation 4 (config keys `data.raw_zip`, `data.raw_csv_name` unused) is unchanged.
6. S1 appends **no** `experiments/registry.csv` row (it produces no experiment results). Revisit if a run record for data builds is wanted.
7. `make data` still lists the S2/S3 commands, which are stubs that exit 1: it runs `ingest` and `validate` correctly and then stops at `build-master`. Run the two S1 commands directly until S2/S3 exist.

**Observations for later stages (informational):**
- Besides the four reference events, `flag_corp_action_suspect` also fires on MSFT 2004-11-15 (special dividend), CCEP 2010-10-04 and 2016-05-31, ASML, KLAC and others, and on ~10 marginal events with a return gap of 0.03-0.04 (AZN x5, COST x3, PCAR x2) that look like large ordinary dividends. They are flags only; S2/S3 decide what to do with them.
- `Close` and `Adj Close` are both 2-decimal rounded, so `adj_close / close` ratios are noisy at low prices (the reason for the `corp_action_min_prev_close` guard).

### S2: Security master and universe: implemented (awaiting local verification)

**Delivered:**
- `src/nasdaq100/data/security_master.py`: curated-exceptions loader/validator, `build_security_master` (curated defaults + `first_date, last_date, n_obs, cohort, zero_volume_share, median_dollar_volume_last_year, include_in_universe, status_reason`), deterministic CSV writer/loader, `read_silver`, `run_build_master`.
- `src/nasdaq100/data/universe.py`: `build_universe` (the single place eligibility is decided), `run_build_universe`, `load_universe(cfg)` (honours `project.variant`, applies no filter of its own), `master_fail_by_ticker`.
- `data/reference/security_master_curated.csv` (tracked; exceptions only): AZN and GOOG excluded; GOOG `issuer_id=GOOGL`; GOOGL `share_class=A`; `stitching_suspect=true` for CCEP, KDP, WBD, LIN, BKR, MDLZ.
- `docs/survivorship.md` (hand-written, tracked): evidence, what the universe does and does not do, claims policy (section IV.4), `in_index_pit` plug-in point.
- CLI: `build-master` and `build-universe` (config is validated first; failures exit 1).
- Tests: `tests/unit/test_{security_master,universe,cli_s2,survivorship_doc}.py`, `tests/leakage/test_universe_time_safety.py` (L2), `tests/integration/test_s2_real_data.py` (`needs_data`), `tests/integration/conftest.py` (session fixture `real_s1`: runs S1 into a temp dir), `tests/fixtures/s2_silver.py`. Five `test_cli.py` references used `build-master` as the "unimplemented command" example; they now use `explain`.

**Measured on the real archive (assistant's sandbox; all within the guide's tolerances):** security master 100 tickers (55 `orig2000`, 45 `later`), 98 included, excluded AZN (curated + quality rule: 34.1% zero-volume days) and GOOG (curated); empty curated file still excludes exactly AZN. Universe 514,075 rows, 436,753 eligible (85.0%); `fail_*` rows: master 9,688, seasoning 25,200, min_close 48,646, zero_volume 1,594, liquidity 14,715. Median eligible names per date by year: 2001 = 42, 2005 = 48, 2008 = 53, 2010 = 59, 2015 = 75, 2019 = 83, 2022 = 94, 2025 = 98. GOOG never eligible; GOOGL first eligible 2005-08-18 (its 253rd observation). Variant `orig55` (`cohort_filter=original55`): 317,109 eligible rows, base untouched.

**Verification record:**

| Check | Result | Note |
|---|---|---|
| `pytest -m "not needs_data and not slow"` (sandbox) | 119 passed | 77 (S0+S1) + 42 new |
| `pytest -m needs_data` (sandbox, real archive) | 30 passed | 13 (S1) + 17 new; full tree 149 passed |
| `pytest -m leakage` (sandbox) | 4 passed | L2 universe time-safety |
| CLI `ingest`, `validate`, `build-master`, `build-universe` (sandbox, real archive) | Work; master and universe rebuilds are deterministic | Isolated copy of the repo layout; variant run does not overwrite base |
| Mutation checks (sandbox) | 9/9 caught | Seasoning off-by-one, `min_periods`, NaN-liquidity handling, strict `<` min close, stitched drop, `eligible` formula, quality rule (two ways), look-ahead via whole-history `n_obs` |
| Ruff | Not run | Unavailable offline; AST check for unused imports/variables found nothing. **Run `ruff check .` locally.** |
| **Local run with real dependencies** | Pending | Sandbox used **stand-ins** for pydantic, the parquet engine (pickle) and pytest (mini runner); pandas 3.0.2, Python 3.12. **Re-run locally and record here.** |

**Interpretations of the guide (none change a schema):**
1. `universe.cohort_filter` accepts `original55` / `later` (section II.4) and maps them to the security-master cohorts `orig2000` / `later` (section II.5): the same 55 tickers (first date 2000-01-03). Any other value raises `UniverseError` (config still does not validate enum strings; S0 deviation 5 unchanged).
2. `median_dollar_volume_last_year` is the median of `close * volume` over each ticker's last 252 observations (not calendar 2025). Measured: AZN about $0.20M; next-lowest GFS about $84M (the guide quotes about $0.19M and about $75M for 2025).
3. **`include_in_universe` is static and whole-history by specification** (curated exclusions plus the zero-volume quality rule on full-history `zero_volume_share`). It is a curation decision, not a per-date rule; only AZN is affected by the quality rule today. The per-date rules (seasoning, min close, zero volume, liquidity) are time-safe (L2). The L2 test holds the master fixed. Disclosed in `docs/survivorship.md`.
4. `security_master.csv` does not depend on `project.variant`, but it embeds `flags.max_zero_volume_share_ticker`: re-run `build-master` after changing that key.
5. `universe.parquet` has exactly the section II.5 columns (no `t_idx` or `n_obs`); later stages join the calendar or silver. The builder takes `n_obs` from silver and raises if it is inconsistent with row order.
6. GOOG `share_class` is `C` in the curated file (the guide only specifies GOOGL = `A`; GOOG is Alphabet's class C).
7. `load_universe` has no locked-test guard: decision D19 belongs to S6/S16, which must wrap it. No `experiments/registry.csv` row is written (no experiment results), consistent with S1.
8. `data/reference/security_master.csv` is not git-ignored (the guide keeps `data/reference` tracked); it is small and byte-for-byte deterministic, so committing it is reasonable.
9. `make data` still lists `build-adjusted` (S3 stub, exits 1): it runs the four S1/S2 commands correctly and then stops. Run the S1/S2 commands directly until S3 exists.

**Observations for later stages (informational):**
- The first 252 trading dates have zero eligible names by construction (seasoning); the first eligible decision date is 2001-01-02 (`t_idx` 252), as in the guide.
- Ineligible rows are kept in `universe.parquet` with their `fail_*` reasons; S1 flags remain only in silver.

---

## Exact next step

1. Review the S6 changes and local verification results, then commit locally as `S6: validation framework and locked-test guard`. Do not push to GitHub until the changes have been reviewed.
2. Create the S7 handoff ZIP from the committed tree, excluding `.git` and `.venv`.
3. Start the **S7 Predictive evaluation library and baseline models** stage with the current `MASTER_PROJECT_BUILD_GUIDE.md`, `PROJECT_STATE.md` and the handoff ZIP. S7 and later must read features and labels only through `load_panel` and the S6 folds.
4. S7 must preserve S0-S6 and implement **S7 only**.

## File Quick Reference

| File | Purpose |
|---|---|
| `MASTER_PROJECT_BUILD_GUIDE.md` | Single source of truth for all stages |
| `configs/base.yaml` | All default parameters; `--config` override files layer on top |
| `src/nasdaq100/config.py` | Config loader and `config_hash` |
| `src/nasdaq100/paths.py` | All artifact path helpers (variant-namespaced) |
| `src/nasdaq100/cli.py` | CLI entry point (`status`, `ingest`, `validate`, `build-master`, `build-universe`, `build-adjusted`, `build-labels`, `build-features`, `check-leakage` work; other commands are stubs until their stage) |
| `src/nasdaq100/utils/io.py` | Parquet I/O, registry append, run IDs |
| `src/nasdaq100/utils/calendar.py` | Global trading calendar, `t_idx` arithmetic, rebalance dates |
| `src/nasdaq100/data/ingest.py` | Zip -> bronze, calendar, manifest, frozen-dataset guard |
| `src/nasdaq100/data/flags.py` | Silver flags (`n_obs`, `flag_*`) |
| `src/nasdaq100/data/validate.py` | Hard/soft checks, validation report, data-quality report |
| `src/nasdaq100/data/security_master.py` | Curated exceptions + derived security master (`data/reference/security_master.csv`) |
| `src/nasdaq100/data/universe.py` | Eligibility builder (single source of truth) and `load_universe(cfg)` |
| `src/nasdaq100/data/adjust.py` | Adjusted prices and `logret_cc` (S3) and `load_adjusted(cfg)` |
| `src/nasdaq100/validation/folds.py` | `Fold`, `make_fold`, `make_dev_folds`, `make_tuning_folds`, `make_locked_folds` (token), `build_fold_plan`, `write_fold_plan` (S6) |
| `src/nasdaq100/validation/guards.py` | `LockedTestError`, `assert_not_locked`, `open_locked_test` (S16 only), tokens, boundary indices (S6) |
| `src/nasdaq100/validation/leakage.py` | `assert_folds_valid`, `poison_future`, `null_panel_test` (skeleton), `SpyEstimator`, `run_leakage_suite` (S6) |
| `src/nasdaq100/data/loaders.py` | `load_panel(cfg, features, split, labels=True)`: the only supported way to read features and labels (S6) |
| `src/nasdaq100/labels/forward_returns.py` | Forward-return labels (S4), `build_labels`, `run_build_labels`, `load_labels(cfg)` |
| `data/reference/security_master_curated.csv` | Hand-curated exceptions (AZN, GOOG, stitching suspects); tracked |
| `docs/data_dictionary.md` | Column-level documentation of processed tables (labels, features, the `load_panel` panel, `fold_plan.json`) |
| `docs/survivorship.md` | Survivorship evidence, allowed claims, point-in-time plug-in point |
| `tests/fixtures/toy_data.py` | Synthetic price and panel generators |
| `tests/fixtures/s1_prices.py` | Clean synthetic raw prices for S1 tests (triggers no flag) |
| `tests/fixtures/s2_silver.py` | Liquid synthetic silver tables, curated frames and configs for S2 tests |
| `tests/fixtures/s6_validation.py` | Holiday-aware synthetic calendars, configs, protocol/token helpers and panel tables for S6 tests |
| `tests/fixtures/s4_labels.py` | Synthetic adjusted-price and universe tables (full S3 / S2 schemas) for S4 tests |
| `experiments/registry.csv` | Append-only experiment log (header only so far) |

### S3: Adjusted price series and returns: implemented (awaiting local verification)

**Delivered:**
- `src/nasdaq100/data/adjust.py`: `build_adjusted(silver, calendar)` (pure), `run_build_adjusted(cfg, ...)` (reads silver and `calendar.parquet`, writes `data/processed/{variant}/adjusted_prices.parquet`), `load_adjusted(cfg)` (the only supported reader for later stages), `AdjustError`, `ADJUSTED_COLUMNS`. Columns exactly as section II.5: `ticker, date, t_idx, adj_factor, adj_open, adj_high, adj_low, adj_close, volume, dollar_volume, logret_cc`; flags are not carried.
- Specification: `adj_factor = adj_close / close`; `adj_open/high/low = field * adj_factor`; `adj_close` carried unchanged; `dollar_volume = close * volume`; `logret_cc = ln(adj_close_t / adj_close_{t-1})` per ticker (NaN on each ticker's first row); `t_idx` from the calendar, asserted consecutive within each ticker. Rows are never dropped (row set == silver).
- CLI: `build-adjusted` (config is validated first; failures exit 1).
- Tests: `tests/unit/test_{adjust,cli_s3}.py`, `tests/leakage/test_adjusted_scale_invariance.py` (L3, S3 part: scale invariance plus causality of `logret_cc`), `tests/integration/test_s3_real_data.py` (`needs_data`).

**Measured on the real archive (assistant's sandbox):** 514,075 rows, 100 tickers, row keys identical to `universe.parquet`; 100 NaN `logret_cc` (one per ticker, first rows only), none elsewhere; `adj_factor` is exactly 1.0 on every ticker's last date (minimum factor 0.1063); `logret_cc` range -0.833 to +0.562. Known events: KDP 2018-07-10 +0.1088, AAPL 2000-09-29 -0.7185; special-dividend days are small in adjusted terms: BKR 2017-07-05 -0.0759, MDLZ 2012-10-02 -0.0123 (raw close returns are below -0.3), TMUS 2013-05-01 -0.1717.

**Verification record:**

| Check | Result | Note |
|---|---|---|
| Baseline (S2 tree) in the assistant's sandbox | 119/119 passed (not needs_data, not slow) | Calibration of the stand-ins below |
| `pytest -m "not needs_data and not slow"` (sandbox) | 141 passed | 119 (S0-S2) + 22 new |
| `pytest -m needs_data` (sandbox, real archive) | 38 passed | 30 (S1, S2) + 8 new; full tree 179 passed |
| `pytest -m leakage` (sandbox) | 8 passed | 4 (L2) + 4 new (L3, S3 part) |
| CLI `ingest`, `validate`, `build-master`, `build-adjusted`, `build-universe` (sandbox, real archive) | Work | Isolated copy of the repo layout |
| Mutation checks (sandbox) | 8/8 caught | Inverted factor, close-based returns, dollar volume on adjusted close, gap check, cross-ticker shift, recomputed `adj_close`, missing ordering widening, `t_idx` off by one |
| Ruff | Not run | Unavailable offline; AST check for unused imports and a line-length/whitespace check found nothing. **Run `ruff check .` locally.** |
| **Local run with real dependencies** | Pending | Sandbox used **stand-ins** for pydantic, the parquet engine (pickle) and pytest (mini runner); pandas 3.0.2, Python 3.12. **Re-run locally and record here.** |

**Interpretations of the guide (none change a schema):**
1. `adj_low <= adj_open, adj_close <= adj_high` is made exact. `adj_close` is the vendor value, which can differ from `close * adj_factor` by one ulp; where the bar's high (low) equals the close, the plain product broke the ordering at the 1e-16 level on 455 rows (227 + 228). `adj_high` is therefore the maximum and `adj_low` the minimum of the product and the adjusted open/close. Values still equal `field * adj_factor` to a relative 1e-12.
2. The table does not depend on any config key, but is written per variant (`adjusted_prices_path(cfg.project.variant)`) so variant pipelines (S2-S8-S11 min-close reruns) find all inputs in one directory; run `build-adjusted` with the same `--override project.variant=...`.
3. `build-adjusted` needs only silver and the calendar (S1). It does not read the universe or the security master, so it can run before or after `build-universe`.
4. Invalid input (missing columns, NaN, non-positive prices, duplicate keys, dates off the calendar, a non-consecutive `t_idx`) raises `AdjustError`; the CLI exits 1. S1 already guarantees these cannot happen on the frozen dataset.
5. A ticker whose `adj_factor` is not 1.0 on its last date is logged as a warning, not an error (none on the real data; the S0 toy fixture has one).
6. No `experiments/registry.csv` row is written (no experiment results), consistent with S1 and S2.
7. `make data` now runs every command it lists (`ingest`, `validate`, `build-master`, `build-adjusted`, `build-universe`); `build-labels` and later are still stubs.

**Observations for later stages (informational):**
- The adjusted *level* is meaningless; S4 labels use ratios of `adj_open`, and S5 features use ratios of `adj_close` and `logret_cc` only (guide pitfalls).
- Low-price rounding makes `logret_cc` noisy early in a ticker's history (AAPL 2000-09-29 is the extreme case); S2's `min_close` eligibility rule is what keeps such rows out of the modelling panel.

### S4: Label generation: implemented (awaiting local verification)

**Delivered:**
- `src/nasdaq100/labels/forward_returns.py`: `build_labels(adjusted, universe, cfg.labels, calendar, *, min_names=20)` (pure), `run_build_labels(cfg, ...)` (reads `adjusted_prices.parquet`, `universe.parquet`, `calendar.parquet`; writes `data/processed/{variant}/labels.parquet`), `load_labels(cfg)` (the only supported reader for later stages), `label_columns(horizons)`, `LabelError`.
- Per horizon `h` in `labels.horizons` (default `[20]`), columns exactly as section II.5, after `ticker, date`: `ret_fwd_h{h}, excess_h{h}, y_reg_h{h}, y_cls_h{h}, rank_pct_h{h}, label_exit_idx_h{h}, has_label_h{h}`. `ret_fwd = ln(adj_open[t+1+h]) - ln(adj_open[t+1])` (row shifts after asserting consecutive `t_idx`); `label_exit_idx = t_idx + 1 + h`; `has_label` = exit on the calendar and both prices exist. Cross-sectional columns only over `eligible & has_label` rows, per date: `excess = ret_fwd - mean`, `y_reg` = `excess` clipped at the per-date `labels.winsor_pct` quantiles (raw units, not standardised), `y_cls = 1[excess > 0]`, `rank_pct` = per-date average-rank percentile of `ret_fwd` (1.0 = best). Dates with fewer than 20 eligible labelled names get NaN cross-sectional labels. Rows are never dropped.
- CLI: `build-labels` (config is validated first; failures exit 1).
- Docs: `docs/data_dictionary.md` (new; labels documented, later stages append).
- Tests: `tests/unit/test_{forward_returns,cli_s4,data_dictionary_doc}.py`, `tests/leakage/test_label_poisoned_future.py` (L1), `tests/integration/test_s4_real_data.py` (`needs_data`), `tests/fixtures/s4_labels.py`.

**Measured on the real archive (assistant's sandbox; matches section III S4):** 514,075 rows (keys identical to `universe.parquet`); last decision date with a label (h=20) 2026-01-16 (`t_idx` 6549); 511,975 rows with `ret_fwd_h20` (exactly the last 21 rows of each of the 100 tickers lack one); 434,695 rows with cross-sectional labels (= eligible and labelled); first date with cross-sectional labels 2001-01-02; 40 to 98 eligible labelled names per date (median 67), so the 20-name minimum never triggers; `y_cls_h20` mean 0.5009; `excess_h20` std 0.0853, mean 0 per date (max |mean| 5e-17); 12,596 `y_reg_h20` values differ from `excess_h20` (clipped); KDP labels across the 2018-07-10 special dividend are smooth (raw open ratio < -1.0, label about +0.19 at `t` = ex-date minus 5).

**Verification record:**

| Check | Result | Note |
|---|---|---|
| Baseline (S3 tree) in the assistant's sandbox | 141/141 passed (not needs_data, not slow) | Calibration of the stand-ins below |
| `pytest -m "not needs_data and not slow"` (sandbox) | 178 passed | 141 (S0-S3) + 37 new |
| `pytest -m leakage` (sandbox) | 26 passed | 8 (L2, L3) + 18 new (L1 label poisoned-future, parametrised over h = 1, 5, 20) |
| `pytest -m needs_data` (sandbox, real archive) | 46 passed | 38 (S1-S3) + 8 new; full tree 224 passed |
| CLI `ingest`, `validate`, `build-master`, `build-universe`, `build-adjusted`, `build-labels` (sandbox, real archive) | Work | Isolated copy of the repo layout |
| Mutation checks (sandbox) | 18 of 20 caught; the other 2 are equivalent mutants | Entry at `t`, exit off by one (two ways), mean over all rows, eligibility dropped, no minimum-names rule (and off by one), `y_cls >= 0`, flipped rank, pooled cross-date mean, no clipping, clipped `excess`, standardised `y_reg`, `has_label` ignoring prices, no contiguity assertion, cross-ticker exit shift, close-to-close labels, swapped clip bounds. Equivalent: dropping the `exit_idx <= last_idx` clause (a missing price already implies it) and an ungrouped entry shift (the grouped exit is NaN on the same rows) |
| Ruff | Not run | Unavailable offline; AST check for unused imports and a line-length/whitespace check found nothing. **Run `ruff check .` locally.** |
| **Local run with real dependencies** | Pending | Sandbox used **stand-ins** for pydantic, the parquet engine (pickle) and pytest (mini runner); pandas 3.0.2, Python 3.12. **Re-run locally and record here.** |

**Interpretations of the guide (none change a schema):**
1. `labels.parquet` has exactly the section II.5 columns: no `t_idx`, `eligible` or flags (join the calendar, `universe.parquet` or silver when needed), as for `universe.parquet`.
2. `ret_fwd_h{h}` is kept for ineligible rows (the guide allows it, for diagnostics); it is NaN exactly where `has_label_h{h}` is False. `excess_h`, `y_reg_h`, `y_cls_h`, `rank_pct_h` are NaN on every ineligible, unlabelled or thin-date row; `y_cls_h` is float64 (0.0, 1.0, NaN). `label_exit_idx_h` (int32) and `has_label_h` (bool) are always populated.
3. Quantiles for the `y_reg_h` clip use pandas' default linear interpolation over the eligible labelled names of the date; `rank_pct_h` uses average ranks for ties (`rank(pct=True)`), so ranks lie in (0, 1].
4. The 20-name minimum is the module constant `MIN_CROSS_SECTION` (no config key; `config.py` is unchanged), overridable through the keyword `min_names` for tests. Dates with 1 to 19 eligible labelled names raise one warning per horizon; dates with none (the 252-date seasoning period and the trailing horizon) are logged at info level, because they occur on every run.
5. `adjusted_prices.parquet` and `universe.parquet` must have identical (ticker, date) keys, `t_idx` must agree with the calendar and be consecutive within each ticker; otherwise `LabelError` (exit 1 from the CLI). `labels.primary_horizon` must be in `labels.horizons`; `labels.winsor_pct` must be `[lo, hi]` with `0 <= lo < hi <= 1`.
6. `has_label_h` is computed from the calendar end and price existence only, independent of eligibility.
7. No locked-test guard (D19) and no dev label masking (L7): those belong to S6/S16, which must wrap `load_labels`. No `experiments/registry.csv` row is written (no experiment results), consistent with S1 to S3.
8. `make features` already lists `build-labels`; `make data` is unchanged and does not run it (the guide's `make all` order places `build-labels` after `build-universe`).

**Observations for later stages (informational):**
- A label at `t` depends on `adj_open` at `t+1` and `t+1+h` of the same ticker and on the same-date cross-section; changing one open moves labels only on dates `j-1` and `j-1-h` (tested exactly). S6 purge/embargo must use `label_exit_idx_h`.
- `excess_h20` has a standard deviation of about 0.085 over 20 trading days; `y_reg_h20` (clipped) is about 0.080.


### S5: Feature engineering: implemented and locally verified

**Delivered:**
- `src/nasdaq100/features/registry.py`: 24 registered MVP features with feature specs, families, required-feature checks and registry validation.
- `src/nasdaq100/features/stock_features.py`: 18 stock-level features with trailing-window calculations and causal two-pass beta.
- `src/nasdaq100/features/market_features.py`: six market-level features and point-in-time eligible-name market aggregation.
- `src/nasdaq100/features/normalize.py`: eligible-only, per-date winsorisation and rank-Gauss transformation with average ranks for ties.
- `src/nasdaq100/features/build.py`: feature-building orchestrator and loaders; writes raw/model feature panels and market series without dropping rows.
- `src/nasdaq100/cli.py`: `build-features` command with config validation and failure handling.
- `docs/data_dictionary.md`: S5 feature documentation.
- Tests covering registry, stock features, market features, normalisation, orchestration, CLI, documentation, real-data integration and leakage/poisoned-future cases.

**Verification record:**

| Check | Result | Note |
|---|---|---|
| `ruff check .` | ✅ Passed | Clean local run with Ruff. |
| `git diff --check` | ✅ Passed | No whitespace errors. |
| S5 test suite | ✅ Passed | All locally run S5 tests produced the expected results. |
| Real-data feature build | ✅ Passed | Built successfully against the real frozen archive. |
| Leakage tests | ✅ Passed | Future-poisoning and per-date rank-Gauss checks passed. |

**Real-data observations:**
- Feature construction preserves the full 514,075-row panel; rows are not dropped.
- Stock and market features use causal/trailing information only.
- Stock features have expected warm-up NaNs.
- Market features have expected seasoning/warm-up NaNs.
- Normalisation is performed per date over eligible names only.
- `beta_126` is undefined during its initial trailing window, as expected.
- Market aggregation uses names eligible at `t-1`, avoiding contemporaneous eligibility look-ahead.

**S5 caveats / boundaries:**
1. Market-series warm-up periods naturally contain NaNs.
2. `check-leakage` is not implemented in S5; the dedicated leakage pytest suite provides S5 leakage coverage. The broader validation framework belongs to S6.
3. Locked-test / D19 protection is not introduced in S5; it belongs to S6/S16.
4. The existing frozen dataset remains explicitly survivorship-biased; S5 does not change that data-quality limitation.
5. No experiment registry row is written because S5 produces features rather than experiment results.

**Interpretations of the guide (none changes a schema):**
1. The market series is NaN until the first name is eligible (no composition exists), so `mkt_logret` and `mkt_index` are NaN for the initial period. Consequently, `beta_126` and the windowed market features have their expected warm-up NaNs. The needs_data "first valid date 2001-01-02" is interpreted as the first eligible date with the other stock-level features defined.
2. `mkt_index` is `exp(cumsum(mkt_logret))`, with the market series remaining NaN while `mkt_logret` is NaN. The implemented column name is `n_eligible`; the guide text calls it `n_eligible_t`.
3. Standard deviations use sample (`ddof=1`) behavior. `beta_126` uses sample moments and is NaN when its required return window is incomplete or market variance is numerically zero. Log-based volume/liquidity features return NaN rather than infinity when their logarithm argument is invalid.
4. `mkt_breadth_50` divides by eligible names with a defined `px_sma_50`; `xs_disp_21` is the sample standard deviation of `ret_21` over eligible names and requires at least two observations.
5. Winsorisation is applied per date to eligible, non-NaN values before rank-Gauss transformation. With the current cross-section size, the specified 1%/99% clipping generally does not alter the rank ordering, but the implementation remains spec-faithful.
6. Market-level features are copied to every row for their date, including ineligible rows, because they are date-level features. Stock-level features for ineligible rows remain NaN.
7. The workflow mentions `check-leakage` for S5, but the CLI assignment places it in S6+. S5 therefore provides dedicated leakage tests rather than implementing the broader `check-leakage` command.
8. `features/build.py` is a thin orchestration addition beyond the guide's explicitly listed feature files. S5 does not write an `experiments/registry.csv` row or apply the D19 locked-test guard; those concerns belong to later stages.

**Observations for later stages (informational):**
- `beta_126` and market-window features naturally contain warm-up NaNs. S6/S8 should explicitly decide whether any minimum-feature rule is required.
- `features_model` contains per-date rank-Gauss-transformed stock-level features; `features_raw` and `features_model` should not be mixed casually in a model pipeline.
- The existing dataset remains explicitly survivorship-biased; S5 does not change that limitation.

**Milestone:** S5 establishes the clean labelled feature panel required for M1.

### S6: Validation framework (splits, locked-test guard, leakage tooling): implemented and locally verified

**Baseline:** M1, commit `7e0d5ab615ca9cb65b6f3ef494ceedac2ca750c0` (S0-S5 complete). No S6 commit hash yet; nothing has been committed or pushed.

**Scope and delivered components** (Master Guide Part III S6):
- `src/nasdaq100/validation/folds.py`: `Fold` (`fold_id, kind, test_year, test_start_idx, test_end_idx, train_core_idx, calib_idx, gap, train_end_idx, base_rate`), `make_fold` (the algorithm for one test period), `make_dev_folds(cfg)` (12 folds, test years 2008-2019), `make_tuning_folds(cfg)` (validation years 2005-2007, no calibration block, `t <= tuning_max_idx`), `make_locked_folds(cfg, token)` (2020-2026, needs the guard token), `build_fold_plan` / `write_fold_plan`, `purge_gap`, `year_bounds`.
- `src/nasdaq100/validation/guards.py`: `LockedTestError`, `assert_not_locked(dates_or_idx, cfg=None, *, calendar=None, token=None)`, `open_locked_test(cfg, protocol_file=None)` (checks `frozen == true`, records `test_opened` / `test_opened_at`, logs a warning, returns a `LockedAccessToken`), `require_token`, `is_valid_token`, and the boundary helpers `locked_start_idx`, `last_dev_label_idx` (5009), `tuning_max_idx` (1988).
- `src/nasdaq100/validation/leakage.py`: `assert_folds_valid`, `poison_future(panel, t_idx)`, `null_panel_test(pipeline_fn, seeds, panel_factory=None)` (skeleton for S8), `SpyEstimator` (max `t_idx` seen in `fit`, for S8), `run_leakage_suite`, `LeakageError`.
- `src/nasdaq100/data/loaders.py`: `load_panel(cfg, features, split, labels=True, *, token=None, ...)` and the pure `build_panel`.
- CLI `check-leakage` (config validated first): writes `artifacts/{variant}/fold_plan.json`, then runs `pytest -m leakage`; exit 0 only if the plan was written and every leakage test passed.
- Tests: `tests/unit/test_{folds,guards,loaders,leakage_tools,cli_s6}.py`, `tests/leakage/test_{fold_validity,dev_label_masking,locked_guard}.py` (L6, L7, L8), `tests/integration/test_s6_real_data.py` (`needs_data`), fixtures `tests/fixtures/s6_validation.py`. `docs/data_dictionary.md` documents the `load_panel` panel and `fold_plan.json`.

**Files modified (S0-S5 files):** `src/nasdaq100/cli.py` (three imports, `cmd_check_leakage`, one dispatch branch; the `check-leakage` parser entry already existed) and `docs/data_dictionary.md` (two sections appended). No S0-S5 behaviour changes: no config, path, test or data changes; `load_labels`, `load_features_model`, `load_features_raw`, `load_universe` are unchanged and remain unguarded building blocks (see interpretation 8).

**Real-calendar results (assistant's sandbox, real archive, stand-in parquet engine):** locked start `t_idx` 5031 (2020-01-02); last dev date 5030 (2019-12-31); `last_dev_label_idx` 5009 (2019-11-29); `tuning_max_idx` 1988 (2007-11-29); `first_train_idx` 252; gap 26. Dev fold 2008: `t0` 2010, `train_end` 1983 (2007-11-21), calibration `[1480, 1983]` and core `[252, 1453]` before stride (guide worked example; with `train_stride=5` the blocks are `[1482, 1982]` with 101 dates and `[252, 1452]` with 241 dates; core span 1,201-1,202 dates, about 4.8 years). 12 dev folds (test years 2008-2019, last test date 2019-12-31), 3 tuning folds (2005, 2006, 2007; the last ends at 1988), 7 locked folds (2020-2026, last test date 2026-02-18). Dev panel: last date 2019-12-31, labels NaN and `has_label_h20` False for `t_idx` 5010-5030, features kept; tuning panel ends at `t_idx` 1988; `load_panel("locked")` raises without a token and returns all 6,571 dates with 511,975 labelled rows with one.

**Acceptance criteria:**

| Criterion (guide) | Met | Evidence |
|---|---|---|
| Property tests pass (folds valid, exact gap, off-by-one, worked example, stride, rolling window) | Yes (sandbox) | `tests/leakage/test_fold_validity.py` (60 random draws of calendar, h in {5, 20, 60}, embargo, calibration, stride, window, checked against an independent re-derivation), `tests/unit/test_folds.py` |
| Gap formula exact; row at `t0 - gap - 1` allowed, `t0 - gap` not | Yes | `test_gap_off_by_one_for_every_horizon`, `test_off_by_one_row_at_t0_minus_gap_minus_1_allowed_t0_minus_gap_blocked` |
| Dev folds never include dates on or after 2020-01-02, also as training rows | Yes | L6 tests, `assert_folds_valid(..., locked_start_idx=5031)` on the real calendar |
| Loader NaN-masks dev labels beyond 5009; dev data contain no date >= 2020-01-02 (L7) | Yes | `tests/leakage/test_dev_label_masking.py`, real-data test |
| `load_panel("locked")` raises without protocol and with `frozen=false`; boundary 2019-12-31 allowed, 2020-01-02 blocked (L8) | Yes | `tests/leakage/test_locked_guard.py`, `tests/unit/test_guards.py` |
| Tuning split ends at 1988 | Yes | `tests/unit/test_loaders.py`, real-data test |
| `fold_plan.json` lists 12 dev folds with sensible sizes (fold 2008 core about 4.8 years, about 1,200 dates before stride) | Yes (sandbox) | `check-leakage` wrote the plan; `tests/integration/test_s6_real_data.py` |
| The guard cannot be bypassed via public loaders | Yes, by construction and by tests | Locked data need a token that only `open_locked_test` issues; structural tests: nothing in `src/` calls or imports `open_locked_test` except `guards.py`, and only `data/loaders.py` imports `load_labels` / `load_features_model` / `load_features_raw` |
| Committed as `S6: validation framework and locked-test guard` | Pending | Not committed (patch delivered for review) |

**Verification record:**

| Check | Result | Note |
|---|---|---|
| Baseline (M1 tree) in the assistant's sandbox | 337/337 passed | Calibration of the stand-ins below |
| `pytest -m "not needs_data and not slow"` (sandbox) | 411 passed | 282 (S0-S5) + 129 new |
| `pytest -m leakage` (sandbox) | 169 passed | 91 (L1-L5) + 78 new (L6, L7, L8) |
| `pytest -m needs_data` (sandbox, real archive) | 62 passed | 55 (S1-S5) + 7 new; full tree 473 passed |
| `python -m nasdaq100.cli check-leakage` (sandbox) | Fold plan written; the pytest step could not run | The sandbox `pytest` is a stand-in without `python -m pytest`; **run it locally** |
| Mutation checks (sandbox) | 30 of 30 caught | Off-by-one gap / train_end / calibration / core purge, stride anchor, window, tuning cap, locked start clamp, boundary comparisons, frozen check, token validity, mask cap and flags, split filters, guard removals, validity-check weakening. One genuine gap (locked start not clamped to the configured lock) found and closed with a test |
| Ruff | Not run | Unavailable offline; AST scans for unused imports, `zip(strict=)`, constant `getattr` and whitespace found nothing. **Run `ruff check .` locally** |
| **Local run with real dependencies (Windows .venv)** | Passed | 411 regular tests passed; 169 leakage tests passed; `check-leakage` generated the fold plan; 62 real-data tests passed; `ruff check .` and `git diff --check` passed. Fold example `dev_2008` matched the expected values. |

**Interpretations of the guide (none changes a schema or an earlier stage):**
1. `load_panel` adds a `t_idx` column (int32, from the calendar) to the join of `features_model`, `labels` and `eligible`: folds are defined on `t_idx`. It verifies that `labels`, `features_model` and `universe` have identical keys and identical `eligible` before joining. Column order: `ticker, date, t_idx, eligible`, features, the seven primary-horizon label columns.
2. `split="locked"` returns the complete panel (all dates, true labels) and only with a valid token: the S16 folds 2021-2026 train on earlier locked years (guide S16). `split="dev"` and `"tuning"` additionally run `assert_not_locked` on their output.
3. In dev mode `label_exit_idx_h20` is not masked (an integer calendar number, not price information); `ret_fwd`, `excess`, `y_reg`, `y_cls`, `rank_pct` are NaN and `has_label` False for `t_idx > 5009`.
4. `fold_plan.json` is written with the existing `paths.fold_plan_path(variant)`, i.e. `artifacts/{variant}/fold_plan.json` (`artifacts/base/fold_plan.json`), keeping S0's variant namespacing. The guide and `.gitignore` name `artifacts/fold_plan.json` (the only fold-plan path exempt from the artifacts ignore rule), so the file is git-ignored here; nothing changed in `paths.py` or `.gitignore`. It lists the dev and tuning folds and the boundary indices; locked folds are deliberately absent.
5. `assert_not_locked` accepts dates or integer `t_idx` (resolved with a calendar, default the stored one); the boundary is on the decision date (>= `validation.locked_test_start`). A valid token disables the check.
6. `open_locked_test(cfg, protocol_file=None)` writes `test_opened = true` and `test_opened_at` (UTC) into the protocol and never overwrites an earlier timestamp; tokens are valid only in the issuing process (`_ISSUED_NONCES`), which makes peeking a deliberate and logged act, not a cryptographic barrier. Rerun flagging (`rerun_count`, L18) belongs to S16.
7. `make_fold` thins both blocks by `(t_idx - first_train_idx) % train_stride == 0` (anchor `first_train_idx`, 252 by default); the test period is never thinned. Tuning folds restrict the validation dates to `t <= tuning_max_idx` (the 2007 fold ends at 1988) and have no calibration block. `first_train_idx` is the first trading date on or after `validation.first_train_decision_date`.
8. The S4/S5 table readers remain public and unguarded; a structural test restricts their importers to `data/loaders.py`. S7 and later must read features and labels through `load_panel`. The same kind of test allows only `validation/guards.py` to mention `open_locked_test`: **S16 must extend that allow-list** with its `locked-test` command.
9. `null_panel_test` is a skeleton: the pipeline returns `ic_by_date` (non-overlapping per-date ICs) and optionally `auc`; criteria from S8 (pooled mean IC within 2.5 SE, at most 20% of the runs with |t| > 2, mean AUC within 0.02 of 0.5, at least 10 seeds). Its default panel factory is the S0 `make_null_panel` (imported lazily from the test fixtures; pass `panel_factory` otherwise). `SpyEstimator.fit(X, y, t_idx=...)` takes the decision dates from the argument, a `t_idx` column or an index named `t_idx`.
10. `check-leakage` runs `python -m pytest -m leakage -q` in a subprocess from the repository root; the sandbox could only verify the plan-writing half.

**Observations for later stages (informational):**
- Dev *predictions* are made on all eligible rows of each test year (including December 2019 where labels are masked); *evaluation* must use only rows with `has_label` (S7). The rebalance schedule and the dev backtest (S11) must not use decision dates after 2019-11-29 for evaluated results.
- `beta_126` and market-window features have warm-up NaNs from 2001; with `first_train_decision_date` 2001-01-02 the first training rows have NaN market features. S8 must decide on a minimum-feature rule explicitly.
- Fold training blocks hold decision dates; the trainer selects `eligible & has_label` rows within them. `Fold.base_rate` is filled at fit time (S8).
- `tests/leakage` now holds L1-L8; `pytest -m leakage` is the gate for every later stage.
