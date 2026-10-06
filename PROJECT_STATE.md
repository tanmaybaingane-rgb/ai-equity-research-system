# Project State: AI-Driven Equity Research & Portfolio Decision Support System

Living progress log (Master Project Build Guide §II.6). Updated at the end of every stage.

**Last updated:** 2026-10-06 (S4 implemented; awaiting local verification)
**Git baseline:** `bbde223` "S3: adjusted series" (branch `master`, no remote configured)
**Active environment:** Windows, Python 3.14 virtual environment (`.venv`), project folder under OneDrive

---

## Stage Checklist

| Stage | Name | Status | Completed | Commit | Notes |
|:---|:---|:---:|:---:|:---:|:---|
| **S0** | Foundations (repository, configuration, tooling) | ? Done (local) | 2026-10-03 | `86767bb` | Initial foundations in `93f1abb`; close-out in `86767bb`. CI not run (no remote). See S0 log. |
| **S1** | Data ingestion, validation and quality flags | ? Done (local) | 2026-10-04 | `c251ae3` | Locally verified with the real archive and dependencies. See S1 log. |
| **S2** | Security master and universe (eligibility) layer | ? Done (local) | 2026-10-04 | `102b7c8` | Locally verified with the real archive and dependencies. See S2 log. |
| **S3** | Adjusted price series and returns | ? Done (local) | 2026-10-04 | `bbde223` | Locally verified with the real archive and dependencies. See S3 log. |
| **S4** | Label generation | 🟡 Implemented (not yet verified locally) | 2026-10-06 | - | Sandbox-verified with stand-ins (see S4 log). Run the local verification commands, then commit as `S4: labels`. |
| **S5** | Feature engineering (stock-level, market-level, normalisation) | Not started | - | - | Milestone M1 (clean labelled panel) |
| **S6** | Validation framework (splits, locked-test guard, leakage tooling) | Not started | - | - | - |
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

1. Verify S4 locally (see the S4 log: `pytest -m "not needs_data"`, `pytest -m leakage`, `python -m nasdaq100.cli build-labels`, `pytest -m needs_data`, `ruff check .`), record the results, then commit as `S4: labels`.
2. Create the S5 handoff ZIP from the committed tree, excluding `.git` and `.venv`.
3. Start a new Claude chat for **S5 Feature engineering**. Include the current `MASTER_PROJECT_BUILD_GUIDE.md`, `PROJECT_STATE.md`, and the S5 handoff ZIP.
4. S5 must preserve S0-S4 and implement **S5 only**.

## File Quick Reference

| File | Purpose |
|---|---|
| `MASTER_PROJECT_BUILD_GUIDE.md` | Single source of truth for all stages |
| `configs/base.yaml` | All default parameters; `--config` override files layer on top |
| `src/nasdaq100/config.py` | Config loader and `config_hash` |
| `src/nasdaq100/paths.py` | All artifact path helpers (variant-namespaced) |
| `src/nasdaq100/cli.py` | CLI entry point (`status`, `ingest`, `validate`, `build-master`, `build-universe`, `build-adjusted`, `build-labels` work; other commands are stubs until their stage) |
| `src/nasdaq100/utils/io.py` | Parquet I/O, registry append, run IDs |
| `src/nasdaq100/utils/calendar.py` | Global trading calendar, `t_idx` arithmetic, rebalance dates |
| `src/nasdaq100/data/ingest.py` | Zip -> bronze, calendar, manifest, frozen-dataset guard |
| `src/nasdaq100/data/flags.py` | Silver flags (`n_obs`, `flag_*`) |
| `src/nasdaq100/data/validate.py` | Hard/soft checks, validation report, data-quality report |
| `src/nasdaq100/data/security_master.py` | Curated exceptions + derived security master (`data/reference/security_master.csv`) |
| `src/nasdaq100/data/universe.py` | Eligibility builder (single source of truth) and `load_universe(cfg)` |
| `src/nasdaq100/data/adjust.py` | Adjusted prices and `logret_cc` (S3) and `load_adjusted(cfg)` |
| `src/nasdaq100/labels/forward_returns.py` | Forward-return labels (S4), `build_labels`, `run_build_labels`, `load_labels(cfg)` |
| `data/reference/security_master_curated.csv` | Hand-curated exceptions (AZN, GOOG, stitching suspects); tracked |
| `docs/data_dictionary.md` | Column-level documentation of processed tables (labels so far) |
| `docs/survivorship.md` | Survivorship evidence, allowed claims, point-in-time plug-in point |
| `tests/fixtures/toy_data.py` | Synthetic price and panel generators |
| `tests/fixtures/s1_prices.py` | Clean synthetic raw prices for S1 tests (triggers no flag) |
| `tests/fixtures/s2_silver.py` | Liquid synthetic silver tables, curated frames and configs for S2 tests |
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
