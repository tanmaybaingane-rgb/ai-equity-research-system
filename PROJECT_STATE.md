# Project State: AI-Driven Equity Research & Portfolio Decision Support System

Living progress log (Master Project Build Guide §II.6). Updated at the end of every stage.

**Last updated:** 2026-10-03 (S0 close-out patch)
**Git baseline:** `93f1abb` "S0: foundations" (branch `master`, no remote configured)
**Active environment:** Windows, Python 3.14 virtual environment (`.venv`), project folder under OneDrive

---

## Stage Checklist

| Stage | Name | Status | Completed | Commit | Notes |
|:---|:---|:---:|:---:|:---:|:---|
| **S0** | Foundations (repository, configuration, tooling) | ✅ Done (local) | 2026-10-03 | `93f1abb` + close-out | CI not yet run (no remote). `make test` not run (direct pytest equivalent used). See S0 log. |
| **S1** | Data ingestion, validation and quality flags | Not started | - | - | Needs `data/raw/archive.zip` (see "Exact next step") |
| **S2** | Security master and universe (eligibility) layer | Not started | - | - | - |
| **S3** | Adjusted price series and returns | Not started | - | - | - |
| **S4** | Label generation | Not started | - | - | - |
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

---

## Exact next step

1. Review the close-out patch, run `pytest -m "not needs_data and not slow"` and `ruff check .` locally with the real dependencies (record results above), then commit as `S0: close-out (config layering, egg-info, needs_data hook, state file)`.
2. S1 input: copy the frozen dataset archive to `data/raw/archive.zip` (never commit it). Expected file: 8,405,356 bytes, SHA-256 `e70ce876b218b8af9d891a3c47c471f2a039698614697c60b6be5ad32537e8d2`. On Windows PowerShell: `Get-FileHash data\raw\archive.zip -Algorithm SHA256`.
3. Start **S1: Data ingestion, validation and quality flags** in a new Claude chat (attach the guide, this file, the repo tree, `configs/base.yaml`, the S0 modules, and the first ~20 lines of the CSV).

---

## File Quick Reference

| File | Purpose |
|---|---|
| `MASTER_PROJECT_BUILD_GUIDE.md` | Single source of truth for all stages |
| `configs/base.yaml` | All default parameters; `--config` override files layer on top |
| `src/nasdaq100/config.py` | Config loader and `config_hash` |
| `src/nasdaq100/paths.py` | All artifact path helpers (variant-namespaced) |
| `src/nasdaq100/cli.py` | CLI entry point (`status` works; other commands are stubs until their stage) |
| `src/nasdaq100/utils/io.py` | Parquet I/O, registry append, run IDs |
| `tests/fixtures/toy_data.py` | Synthetic price and panel generators |
| `experiments/registry.csv` | Append-only experiment log (header only so far) |
