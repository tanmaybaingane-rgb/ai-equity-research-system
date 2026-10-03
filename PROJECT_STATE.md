# Project State: AI-Driven Equity Research & Portfolio Decision Support System

Living progress log and stage tracking.
**Last updated:** 2026-10-03 by repository audit (based on the uploaded project folder and verified session results).

---

## Stage Checklist

| Stage | Name | Status | Completed Date | Commit | Deviations / Notes |
|:---|:---|:---:|:---:|:---:|:---|
| **S0** | Foundations (repository, configuration, tooling) | ⚠️ Nearly Done | - | - | Local implementation and verification complete; Git baseline commit and CI verification remain. |
| **S1** | Data ingestion, validation and quality flags | Not Started | - | - | - |
| **S2** | Security master and universe (eligibility) layer | Not Started | - | - | - |
| **S3** | Adjusted price series and returns | Not Started | - | - | - |
| **S4** | Label generation | Not Started | - | - | - |
| **S5** | Feature engineering (stock-level, market-level, normalisation) | Not Started | - | - | - |
| **S6** | Validation framework (splits, locked-test guard, leakage tooling) | Not Started | - | - | Milestone M1 pre-flight |
| **S7** | Predictive evaluation library and baseline models | Not Started | - | - | Milestone M1 |
| **S8** | Models, tuning, calibration and walk-forward training | Not Started | - | - | Milestone M2 |
| **S9** | Signal engine | Not Started | - | - | - |
| **S10** | Risk layer and portfolio construction | Not Started | - | - | - |
| **S11** | Backtest engine (execution simulation, costs, benchmarks) | Not Started | - | - | - |
| **S12** | Rule-based market regimes (reporting lens) | Not Started | - | - | - |
| **S13** | Strategy evaluation, ablations, robustness & dev evidence package | Not Started | - | - | Milestone M3 |
| **S14** | Explainability | Not Started | - | - | - |
| **S15** | Streamlit dashboard | Not Started | - | - | - |
| **S16** | Locked test and final report | Not Started | - | - | Milestone M4 (Single run) |
| **S17** | Packaging, documentation and reproducibility check | Not Started | - | - | - |

---

## Stage Progress Log

### S0: Foundations (repository, configuration, tooling)

- **Status:** ⚠️ Nearly Done — S0 implementation is complete and local verification is substantially complete. Dev dependencies are installed, the CLI runs, 19/19 non-data/non-slow tests pass, and the four Ruff findings were fixed. The remaining formal DoD items are the S0 Git commit, `make test` verification, and CI-green confirmation.
- **Artifacts created (verified by file inspection):**

#### Source files (`src/nasdaq100/`)
| File | Status | Notes |
|---|---|---|
| `__init__.py` | ✅ Present | Stub |
| `config.py` | ✅ Implemented | Full pydantic v1/v2 compatible Config; all II.4 sections; `load_config`, `config_hash` |
| `paths.py` | ✅ Implemented | All artifact paths per II.5; variant-namespaced processed/artifacts dirs |
| `cli.py` | ✅ Implemented | `status` command functional; all future commands registered as stubs returning exit 1 |
| `utils/seeds.py` | ✅ Implemented | `set_global_seed(seed)` for Python random, NumPy, PYTHONHASHSEED |
| `utils/hashing.py` | ✅ Implemented | `sha256_file`, `sha256_json`, `get_git_commit` |
| `utils/logging.py` | ✅ Present | Project logger |
| `utils/io.py` | ✅ Implemented | `read_parquet`, `write_parquet` (enforces ticker/date sort); `append_registry` (schema-validated, append-only); `new_run_id` |
| `utils/__init__.py` | ✅ Present | Stub |
| All sub-package `__init__.py` files | ✅ Present | Stubs for: `data/`, `labels/`, `features/`, `validation/`, `models/`, `evaluation/`, `signals/`, `risk/`, `portfolio/`, `backtest/`, `regimes/`, `explain/` |

#### Test files (`tests/`)
| File | Status | Notes |
|---|---|---|
| `conftest.py` | ✅ Implemented | `base_config`, `toy_prices`, `planted_panel`, `null_panel` fixtures |
| `fixtures/toy_data.py` | ✅ Implemented | `make_toy_prices` (tick noise, special dividend, staggered listing, illiquid AZN ticker); `make_planted_signal_panel`; `make_null_panel` |
| `fixtures/__init__.py` | ✅ Present | |
| `unit/test_config.py` | ✅ Written | Covers: defaults, immutability, unknown key raises, override precedence, hash stability |
| `unit/test_paths.py` | ✅ Written | Covers: repo root, variant namespacing, ensure_parent_dir |
| `unit/test_utils.py` | ✅ Written | Covers: seeds, sha256, parquet roundtrip, registry append/schema |
| `unit/test_toy_data.py` | ✅ Written | Covers: toy data generators |
| `unit/test_cli.py` | ✅ Written | Covers: status command, unimplemented command, invalid override |
| `unit/__init__.py`, `leakage/__init__.py`, `integration/__init__.py`, `dashboard/__init__.py` | ✅ Present | |

#### Config and project files
| File | Status | Notes |
|---|---|---|
| `configs/base.yaml` | ✅ Implemented | All II.4 parameters present; matches guide exactly |
| `configs/data_expectations.yaml` | ✅ Present | |
| `configs/candidates/` | ✅ Directory + `.gitkeep` | Empty (S13 deliverable) |
| `configs/experiments/` | ✅ Directory + `.gitkeep` | Empty (experiment overrides) |
| `pyproject.toml` | ✅ Implemented | All runtime deps + dev extra; pytest markers; ruff config |
| `Makefile` | ✅ Present | |
| `.gitignore` | ✅ Present | |
| `.github/` | ✅ Present | CI workflow directory |
| `experiments/registry.csv` | ✅ Present | Header-only (145 bytes) |
| `docs/decisions/0000-template.md` | ✅ Present | Decision record template |
| `README.md` | ✅ Present | |
| `data/raw/`, `data/interim/`, `data/processed/`, `data/reference/`, `data/reports/` | ✅ Present | All empty (`.gitkeep` only); no actual data |
| `artifacts/logs/`, `artifacts/runs/` | ✅ Present | Empty |
| `reports/dev/`, `reports/locked/` | ✅ Present | Empty |
| `dashboard/pages/` | ✅ Present | Empty |

#### Missing from S0 DoD
| Missing item | Impact |
|---|---|
| `utils/calendar.py` | Not created in S0 — spec says it belongs to S1. No blocking issue for S0. |
| `data/reference/security_master_curated.csv` | S2 deliverable — not yet needed. |
| `docs/data_quality_report.md`, `docs/survivorship.md`, `docs/architecture.md`, etc. | S1/S2 deliverables. |
| `requirements-lock.txt` | Not present — the guide lists it in the layout but S0 spec doesn't mandate it. |
| `.pre-commit-config.yaml` | Listed as optional in the guide; not present. |
| `dashboard/app.py`, `dashboard/data_access.py`, `dashboard/components.py` | S15 deliverables. |

---

### S0 Verification — Current State

The S0 environment and local checks have now been completed to the extent verified in the working session.

| Check | Result | Evidence / note |
|---|---|---|
| `pip install -e ".[dev]"` | ✅ Successful | Project editable install and development dependencies installed successfully. |
| `python -m nasdaq100.cli status` | ✅ Successful | CLI runs and prints the project-state checklist. |
| `python -m pytest -m "not needs_data and not slow" -v` | ✅ 19 passed, 0 failed | Full S0 non-data/non-slow test set passed. |
| Ruff lint | 🟡 Fixed; final clean run not separately recorded | Initial run found 4 auto-fixable issues; `ruff --fix` was run and the reported issues were fixed. |
| Git repository | ✅ Initialized | `.git/` is present in the uploaded project folder, but no baseline commit exists yet. |
| `make test` | ⏳ Not separately verified | The direct pytest command above passed; the guide's formal DoD specifically names `make test`. |
| CI | ⏳ Not verified | GitHub Actions workflow exists, but no green CI run was verified from the uploaded folder. |

#### Toy-data test correction

The only failing S0 test was `test_toy_prices_schema_and_quirks`. The fixture uses staggered listing, so TK02 starts at original `d_idx=15`. The special-dividend event at original `d_idx=40` therefore appears at row 25 after filtering TK02 and resetting its index. The test was corrected to inspect rows 24 → 25. The fixture `tests/fixtures/toy_data.py` was not changed.

This resolved the failure and the full S0 test command subsequently passed 19/19 tests.


---

## What Antigravity/Gemini Created or Changed

All files dated **2026-10-02 ~22:00–22:36** were created by Antigravity in the previous session:

- `src/nasdaq100/config.py` (22:35)
- `src/nasdaq100/paths.py` (22:13)
- `src/nasdaq100/cli.py` (22:16)
- `src/nasdaq100/utils/{seeds,hashing,logging,io}.py` (22:13–22:15)
- `src/nasdaq100/__init__.py` and all sub-package `__init__.py` stubs (22:08–22:16)
- `tests/conftest.py` (22:17)
- `tests/fixtures/toy_data.py` (22:17)
- `tests/unit/test_config.py` (22:18), `test_paths.py` (22:18), `test_utils.py` (22:19), `test_toy_data.py` (22:20), `test_cli.py` (22:20)
- `configs/base.yaml` (22:07), `configs/data_expectations.yaml` (22:06)
- `experiments/registry.csv` (22:07)
- `pyproject.toml` (22:08), `Makefile` (22:08)
- All directory scaffolding (22:12)
- `PROJECT_STATE.md` (22:04) — initial version (stub)
- `README.md` (22:03), `docs/decisions/0000-template.md` (22:05)

**No project code was modified by the current (2026-10-03) Antigravity session.** This session is inspection-only.

### Manual changes and verification on 2026-10-03

- Re-ran the project installation with `pip install -e ".[dev]"`; installation completed successfully.
- Ran the S0 pytest command; result: **19 passed, 0 failed**.
- Diagnosed and corrected the TK02 staggered-listing index assumption in `tests/unit/test_toy_data.py`.
- Ran Ruff; four issues were reported (two unused `Path` imports and two unnecessary `"r"` mode arguments). Applied Ruff's automatic fixes.
- Ran `python -m nasdaq100.cli status` successfully after installation.
- Initialized Git; no S0 baseline commit has been recorded yet.

---

## Tests / Checks Actually Run and Their Results

| Test / Check | Run? | Result |
|---|---|---|
| `pip install -e ".[dev]"` | ✅ Yes | Successful editable install with dev dependencies. |
| `python -m nasdaq100.cli status` | ✅ Yes | Successful; checklist printed. |
| `python -m pytest -m "not needs_data and not slow" -v` | ✅ Yes | **19 passed, 0 failed**. |
| `python -m ruff check src/ tests/` | ✅ Initial run | 4 fixable issues found; all were fixed with Ruff's `--fix`. A subsequent clean Ruff output was not captured in the project state. |
| Git initialization | ✅ Yes | `.git/` exists; no commit recorded yet. |
| CI (GitHub Actions) | ⏳ Not verified | Workflow file exists; green run not confirmed. |
| `make test` | ⏳ Not separately run | Direct pytest equivalent passed. Formal DoD still calls for `make test`. |

---

## Known Errors / Incomplete Parts

1. **S0 formal closure pending:** Git baseline commit, `make test` verification, and CI-green confirmation have not yet been verified.
2. **`utils/calendar.py` not present** — expected in S1, not an S0 blocker.
3. **`data/raw/archive.zip`** not present — expected input for S1; data ingestion has not started.
4. **`configs/tuned_params.yaml`** not present — S8 deliverable, not yet needed.
5. **`Dockerfile`** not present — S17 deliverable, not yet needed.
6. **`requirements-lock.txt`** not present — listed in the guide layout but not required by the S0 specification.
7. **`.pre-commit-config.yaml`** not present — optional according to the guide.
8. **CI green status** is unknown because it was not verified from the uploaded repository.

---

## Important Decisions Already in Implementation

- **Pydantic v1/v2 compatibility layer** in `config.py` (lines 21–43): uses `ConfigDict` for v2, falls back to `class Config` for v1. Since `pyproject.toml` requires `pydantic>=2.0.0`, v1 branch is dead code but safe.
- **Variant namespacing** fully implemented in `paths.py`: `processed_dir(variant)` and `artifacts_dir(variant)` use `data/processed/{variant}/` and `artifacts/{variant}/` paths.
- **`config.py` `immutability test`**: the test checks mutation raises `ValidationError`; in pydantic v2 frozen models raise `ValidationError` on mutation — this is correct behaviour.
- **Toy data `AZN` illiquid ticker**: injected as the last ticker when `add_illiquid=True`, with 80% zero-volume days — mirrors the real AZN problem.
- **Registry schema**: `append_registry` enforces exactly 14 columns per II.5; rejects extra or missing columns.

---

## Exact Next Step

Close S0 formally before starting S1:

1. Run a final clean Ruff check:
   `python -m ruff check src/ tests/`
2. Run the guide's formal S0 test target:
   `make test`
3. Check Git status and create the S0 baseline commit:
   `git status`
   `git add .`
   `git commit -m "S0: foundations"`
4. If a GitHub remote has been configured, push and confirm the CI workflow is green.

Only after these checks should S0 be marked **Complete**. Then proceed to **S1 — Data ingestion, validation and quality flags** by placing the frozen `archive.zip` in `data/raw/` and following the S1 specification.

---

## File Quick Reference

| Key File | Purpose |
|---|---|
| `MASTER_PROJECT_BUILD_GUIDE.md` | Single source of truth for all stages |
| `configs/base.yaml` | All runtime parameters (seed, thresholds, universe rules, model grids) |
| `src/nasdaq100/config.py` | Pydantic config loader + `config_hash` |
| `src/nasdaq100/paths.py` | All artifact path helpers |
| `src/nasdaq100/cli.py` | CLI entrypoint (`status` works; all other commands are stubs) |
| `src/nasdaq100/utils/io.py` | Parquet I/O + registry append + run ID generation |
| `tests/fixtures/toy_data.py` | `make_toy_prices`, `make_planted_signal_panel`, `make_null_panel` |
| `tests/conftest.py` | pytest fixtures: `base_config`, `toy_prices`, `planted_panel`, `null_panel` |
| `experiments/registry.csv` | Append-only experiment log (header only currently) |
| `data/raw/` | **Empty** — place `archive.zip` here for S1 |
