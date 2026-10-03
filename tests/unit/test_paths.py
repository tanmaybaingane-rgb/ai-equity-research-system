"""Unit tests for path helpers and variant namespacing."""

from pathlib import Path

import pytest

from nasdaq100.paths import (
    adjusted_prices_path,
    artifacts_dir,
    ensure_parent_dir,
    features_model_path,
    processed_dir,
    repo_root,
    run_dir,
    universe_path,
)


@pytest.mark.unit
def test_repo_root_exists() -> None:
    """Verify repo_root points to existing directory containing pyproject.toml."""
    root = repo_root()
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()


@pytest.mark.unit
def test_variant_namespacing_changes_paths() -> None:
    """Verify that different project variants produce distinct paths."""
    base_proc = processed_dir("base")
    alt_proc = processed_dir("cohort_orig55")
    assert base_proc != alt_proc
    assert str(base_proc).endswith("base")
    assert str(alt_proc).endswith("cohort_orig55")

    base_adj = adjusted_prices_path("base")
    alt_adj = adjusted_prices_path("cohort_orig55")
    assert base_adj != alt_adj
    assert "cohort_orig55" in str(alt_adj)

    base_univ = universe_path("base")
    alt_univ = universe_path("variant_x")
    assert base_univ != alt_univ

    base_feat = features_model_path("base")
    alt_feat = features_model_path("variant_x")
    assert base_feat != alt_feat

    base_art = artifacts_dir("base")
    alt_art = artifacts_dir("variant_x")
    assert base_art != alt_art

    base_run = run_dir("run_123", variant="base")
    alt_run = run_dir("run_123", variant="variant_x")
    assert base_run != alt_run


@pytest.mark.unit
def test_ensure_parent_dir(tmp_path: Path) -> None:
    """Verify ensure_parent_dir creates parent directories."""
    nested_file = tmp_path / "level1" / "level2" / "test.parquet"
    assert not nested_file.parent.exists()

    result = ensure_parent_dir(nested_file)
    assert result == nested_file
    assert nested_file.parent.is_dir()
