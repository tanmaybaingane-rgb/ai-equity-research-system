"""Unit tests for the needs_data auto-skip hook defined in tests/conftest.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import NEEDS_DATA_SKIP_REASON, apply_needs_data_skip, raw_data_available


class FakeItem:
    """Minimal stand-in for a pytest Item (marker lookup and add_marker only)."""

    def __init__(self, name: str, markers: tuple[str, ...] = ()) -> None:
        self.name = name
        self._markers = set(markers)
        self.added: list[Any] = []

    def get_closest_marker(self, name: str) -> object | None:
        return object() if name in self._markers else None

    def add_marker(self, marker: Any) -> None:
        self.added.append(marker)


@pytest.mark.unit
def test_raw_data_available_detects_zip_or_csv(tmp_path: Path) -> None:
    """The dataset counts as available if either the archive or the extracted CSV exists."""
    zip_p = tmp_path / "archive.zip"
    csv_p = tmp_path / "data.csv"
    assert raw_data_available(zip_p, csv_p) is False

    zip_p.write_bytes(b"x")
    assert raw_data_available(zip_p, csv_p) is True

    zip_p.unlink()
    csv_p.write_text("x")
    assert raw_data_available(zip_p, csv_p) is True


@pytest.mark.unit
def test_needs_data_tests_are_skipped_when_dataset_missing() -> None:
    """Only needs_data tests get a skip marker, with an actionable reason."""
    data_test = FakeItem("test_real_data", ("needs_data",))
    data_and_slow = FakeItem("test_real_data_slow", ("needs_data", "slow"))
    plain_unit = FakeItem("test_unit", ("unit",))
    leakage = FakeItem("test_leakage", ("leakage",))

    n = apply_needs_data_skip([data_test, data_and_slow, plain_unit, leakage], data_available=False)

    assert n == 2
    for item in (data_test, data_and_slow):
        assert len(item.added) == 1
        mark = item.added[0].mark
        assert mark.name == "skip"
        assert mark.kwargs["reason"] == NEEDS_DATA_SKIP_REASON
        assert "data/raw" in mark.kwargs["reason"]
    assert plain_unit.added == []
    assert leakage.added == []


@pytest.mark.unit
def test_needs_data_tests_run_when_dataset_present() -> None:
    """No test is modified when the dataset is available."""
    data_test = FakeItem("test_real_data", ("needs_data",))
    assert apply_needs_data_skip([data_test], data_available=True) == 0
    assert data_test.added == []
