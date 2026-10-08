"""Unit tests for per-date winsorisation and rank-gauss (``features/normalize.py``)."""

from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from nasdaq100.features.normalize import check_winsor, rank_gauss_per_date
from nasdaq100.features.registry import FeatureError

D1, D2 = pd.Timestamp("2020-01-06"), pd.Timestamp("2020-01-07")


def _ppf(p: float) -> float:
    return NormalDist().inv_cdf(p)


@pytest.mark.unit
def test_hand_computed_rank_gauss_with_ties_and_clipping_off() -> None:
    raw = pd.DataFrame({"f": [3.0, 1.0, 2.0, 2.0, 10.0]})  # one tie (the two 2.0)
    dates = np.array([D1] * 5)
    z = rank_gauss_per_date(raw, dates, np.ones(5, dtype=bool), [0.0, 1.0])["f"]
    # ranks: 1.0 -> 1, 2.0 -> 2.5 (tie), 3.0 -> 4, 10.0 -> 5; n = 5
    expect = [_ppf((r - 0.5) / 5) for r in (4.0, 1.0, 2.5, 2.5, 5.0)]
    np.testing.assert_allclose(z.to_numpy(), expect, rtol=0, atol=1e-12)
    assert z.iloc[2] == z.iloc[3]  # tied values share one score


@pytest.mark.unit
def test_winsorisation_happens_before_ranking() -> None:
    n = 300
    values = np.arange(1.0, n + 1)
    values[-1] = 1e9  # an extreme outlier
    raw = pd.DataFrame({"f": values})
    dates = np.array([D1] * n)
    elig = np.ones(n, dtype=bool)
    z = rank_gauss_per_date(raw, dates, elig, [0.01, 0.99])["f"].to_numpy()
    # linear-interpolation quantiles: lo = 3.99 and hi = 297.01 (positions 2.99 and 296.01).
    # The three smallest values collapse onto lo and the three largest onto hi: two tie groups
    # with average ranks 2 and 299 (value 4 keeps rank 4, value 297 keeps rank 297).
    assert z[0] == z[1] == z[2] and z[297] == z[298] == z[299]
    assert z[0] == pytest.approx(_ppf((2.0 - 0.5) / n))
    assert z[299] == pytest.approx(_ppf((299.0 - 0.5) / n))
    assert z[3] == pytest.approx(_ppf((4.0 - 0.5) / n))
    assert z[296] == pytest.approx(_ppf((297.0 - 0.5) / n))
    plain = rank_gauss_per_date(raw, dates, elig, [0.0, 1.0])["f"].to_numpy()
    assert plain[0] != plain[1] and plain[298] != plain[299]  # without clipping: no ties


@pytest.mark.unit
def test_ineligible_and_nan_rows_are_nan_and_excluded_from_the_ranking() -> None:
    raw = pd.DataFrame({"f": [5.0, 1.0, 3.0, np.nan, 100.0, -50.0]})
    elig = np.array([True, True, True, True, False, False])
    dates = np.array([D1] * 6)
    z = rank_gauss_per_date(raw, dates, elig, [0.0, 1.0])["f"]
    assert z.iloc[3:].isna().all()  # NaN raw and ineligible rows -> NaN
    # n = 3 (NaN and ineligible excluded): ranks 3, 1, 2
    np.testing.assert_allclose(
        z.iloc[:3].to_numpy(), [_ppf(2.5 / 3), _ppf(0.5 / 3), _ppf(1.5 / 3)], atol=1e-12
    )
    none = rank_gauss_per_date(raw, dates, np.zeros(6, dtype=bool), [0.0, 1.0])
    assert none.isna().all().all()


@pytest.mark.unit
def test_each_date_and_each_feature_is_normalised_separately() -> None:
    rng = np.random.default_rng(2)
    n = 60
    raw = pd.DataFrame({"a": rng.normal(size=2 * n), "b": rng.uniform(100, 200, size=2 * n)})
    raw.loc[3, "b"] = np.nan
    dates = np.array([D1] * n + [D2] * n)
    elig = np.ones(2 * n, dtype=bool)
    z = rank_gauss_per_date(raw, dates, elig, [0.01, 0.99])
    first = rank_gauss_per_date(raw.iloc[:n], dates[:n], elig[:n], [0.01, 0.99])
    second = rank_gauss_per_date(raw.iloc[n:], dates[n:], elig[n:], [0.01, 0.99])
    pd.testing.assert_frame_equal(z.iloc[:n], first)
    pd.testing.assert_frame_equal(z.iloc[n:], second)
    # n counts the non-NaN values of the feature on that date (59 for b on date 1)
    assert z["b"].iloc[:n].notna().sum() == n - 1
    for d in (slice(0, n), slice(n, 2 * n)):
        a = z["a"].iloc[d]
        assert abs(a.mean()) < 0.1 and abs(a.std() - 1.0) < 0.1


@pytest.mark.unit
def test_monotone_in_raw_values_within_a_date() -> None:
    rng = np.random.default_rng(9)
    raw = pd.DataFrame({"f": rng.standard_t(3, size=200)})
    z = rank_gauss_per_date(raw, np.array([D1] * 200), np.ones(200, dtype=bool), [0.01, 0.99])["f"]
    order = np.argsort(raw["f"].to_numpy())
    assert (np.diff(z.to_numpy()[order]) >= 0).all()  # weakly monotone (clipped values tie)
    assert z.nunique() < 200  # the clipped tails tie, the middle is strictly increasing
    mid = order[5:-5]
    assert (np.diff(z.to_numpy()[mid]) > 0).all()


@pytest.mark.unit
def test_input_validation_and_empty_inputs() -> None:
    assert check_winsor([0.01, 0.99]) == (0.01, 0.99)
    for bad in ([0.99, 0.01], [-0.1, 0.9], [0.1, 1.1], [0.5], [0.5, 0.5], [0.1, 0.5, 0.9]):
        with pytest.raises(FeatureError, match="winsor_pct"):
            check_winsor(bad)
    raw = pd.DataFrame({"f": [1.0, 2.0]})
    out = rank_gauss_per_date(raw, np.array([D1, D1]), np.array([False, False]), [0.01, 0.99])
    assert out.shape == (2, 1) and out["f"].isna().all() and out["f"].dtype == "float64"
    empty = rank_gauss_per_date(raw[[]], np.array([D1, D1]), np.array([True, True]), [0.0, 1.0])
    assert empty.shape == (2, 0)
