"""Unit tests for S4: forward-return labels (``labels/forward_returns.py``)."""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
import pytest

from nasdaq100.config import load_config
from nasdaq100.data.adjust import build_adjusted
from nasdaq100.labels import forward_returns as fr
from nasdaq100.labels.forward_returns import (
    LabelError,
    build_labels,
    label_columns,
    load_labels,
    run_build_labels,
)
from nasdaq100.utils.calendar import TradingCalendar
from nasdaq100.utils.io import write_parquet
from tests.fixtures.s4_labels import eligible_where, make_adjusted, make_universe

DATES = pd.bdate_range("2020-01-06", periods=8)


def lcfg(horizons: list[int], primary: int | None = None, winsor: list[float] | None = None):
    """``cfg.labels`` for the given horizons (primary defaults to the first)."""
    ov = [f"labels.horizons={horizons}".replace(" ", ""),
          f"labels.primary_horizon={primary if primary is not None else horizons[0]}"]
    if winsor is not None:
        ov.append(f"labels.winsor_pct={winsor}".replace(" ", ""))
    return load_config(overrides=ov).labels


def _silver(ticker: str, open_: list[float], close: list[float], adj_close: list[float]):
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": DATES[: len(open_)],
            "open": open_,
            "high": [max(o, c) + 0.5 for o, c in zip(open_, close, strict=True)],
            "low": [min(o, c) - 0.5 for o, c in zip(open_, close, strict=True)],
            "close": close,
            "adj_close": adj_close,
            "volume": np.full(len(open_), 1_000, dtype="int64"),
        }
    )


def _row(df: pd.DataFrame, ticker: str, t: int) -> pd.Series:
    sel = df[(df["ticker"] == ticker) & (df["date"] == DATES[t])]
    assert len(sel) == 1
    return sel.iloc[0]


def _three_stock_case():
    """A, B plain; C pays a special dividend (raw open 100 -> 60 on day 3, adjusted smooth)."""
    a = [10.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    b = [20.0, 20.0, 20.0, 22.0, 22.0, 22.0, 22.0, 22.0]
    c_raw = [100.0, 100.0, 100.0, 60.0, 60.0, 60.0, 60.0, 60.0]
    c_adj = [61.0, 61.0, 61.0, 60.0, 60.0, 60.0, 60.0, 60.0]
    silver = pd.concat(
        [_silver("A", a, a, a), _silver("B", b, b, b), _silver("C", c_raw, c_raw, c_adj)],
        ignore_index=True,
    )
    cal = TradingCalendar.from_dates(DATES)
    return build_adjusted(silver, cal), cal


@pytest.mark.unit
def test_hand_computed_three_stock_example_with_dividend_adjustment() -> None:
    adjusted, cal = _three_stock_case()
    # C is ineligible at t=1; everything else eligible.
    elig = eligible_where(adjusted, lambda tk, i: not (tk == "C" and i == 1))
    out = build_labels(adjusted, make_universe(adjusted, elig), lcfg([2]), cal, min_names=2)

    # --- t = 0: entry = open[1], exit = open[3] (h = 2), all three eligible
    ra, rb = math.log(12.0 / 10.0), math.log(22.0 / 20.0)
    rc = math.log(60.0 / 61.0)  # adjusted: tiny. The raw open ratio would be ln(60/100) = -0.51
    assert rc == pytest.approx(-0.0165, abs=1e-4)
    mean0 = (ra + rb + rc) / 3
    for tk, r in (("A", ra), ("B", rb), ("C", rc)):
        row = _row(out, tk, 0)
        assert row["ret_fwd_h2"] == pytest.approx(r, abs=1e-12)
        assert row["excess_h2"] == pytest.approx(r - mean0, abs=1e-12)
        assert row["label_exit_idx_h2"] == 3 and bool(row["has_label_h2"])
        assert row["y_cls_h2"] == (1.0 if r - mean0 > 0 else 0.0)
    assert _row(out, "A", 0)["rank_pct_h2"] == pytest.approx(1.0)  # A is best (ln 1.2)
    assert _row(out, "B", 0)["rank_pct_h2"] == pytest.approx(2 / 3)
    assert _row(out, "C", 0)["rank_pct_h2"] == pytest.approx(1 / 3)
    # y_reg: excess clipped at the per-date 1% / 99% quantiles (linear interpolation, n = 3)
    ex = sorted([ra - mean0, rb - mean0, rc - mean0])
    lo, hi = ex[0] + 0.02 * (ex[1] - ex[0]), ex[2] - 0.02 * (ex[2] - ex[1])
    assert _row(out, "A", 0)["y_reg_h2"] == pytest.approx(hi, abs=1e-12)  # clipped from above
    assert _row(out, "C", 0)["y_reg_h2"] == pytest.approx(lo, abs=1e-12)  # clipped from below
    assert _row(out, "B", 0)["y_reg_h2"] == pytest.approx(rb - mean0, abs=1e-12)  # inside
    assert _row(out, "A", 0)["excess_h2"] > hi  # excess itself is NOT clipped

    # --- t = 1: entry = open[2], exit = open[4]; C ineligible -> kept out of mean / rank
    ra, rb, rc = math.log(13.0 / 11.0), math.log(22.0 / 20.0), math.log(60.0 / 61.0)
    mean1 = (ra + rb) / 2
    assert _row(out, "A", 1)["excess_h2"] == pytest.approx(ra - mean1, abs=1e-12)
    assert _row(out, "B", 1)["excess_h2"] == pytest.approx(rb - mean1, abs=1e-12)
    c1 = _row(out, "C", 1)
    assert c1["ret_fwd_h2"] == pytest.approx(rc, abs=1e-12)  # kept for diagnostics ...
    for stem in ("excess_h2", "y_reg_h2", "y_cls_h2", "rank_pct_h2"):
        assert np.isnan(c1[stem])  # ... but no cross-sectional label
    assert c1["label_exit_idx_h2"] == 4 and bool(c1["has_label_h2"])  # always populated
    assert _row(out, "A", 1)["rank_pct_h2"] == pytest.approx(0.5 + 0.5 * (ra > rb))


@pytest.mark.unit
def test_last_h_plus_1_dates_have_no_label() -> None:
    adjusted, cal = _three_stock_case()
    for h in (1, 2, 3):
        out = build_labels(adjusted, make_universe(adjusted), lcfg([h]), cal, min_names=1)
        last = cal.last_idx
        n_unlabelled = out.loc[~out[f"has_label_h{h}"], "date"].nunique()
        assert n_unlabelled == h + 1
        cutoff = DATES[last - h]  # first date without label
        assert not out.loc[out["date"] >= cutoff, f"has_label_h{h}"].any()
        assert out.loc[out["date"] < cutoff, f"has_label_h{h}"].all()
        dead = out[~out[f"has_label_h{h}"]]
        for stem in ("ret_fwd_h", "excess_h", "y_reg_h", "y_cls_h", "rank_pct_h"):
            assert dead[f"{stem}{h}"].isna().all()
        # exit index is populated on every row, including unlabelled ones
        t_idx = adjusted.sort_values(["ticker", "date"])["t_idx"].to_numpy()
        assert (out[f"label_exit_idx_h{h}"].to_numpy() == t_idx + 1 + h).all()


def _random_case(h: int = 3, n_tickers: int = 12, n_days: int = 50, seed: int = 4):
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    adjusted, cal = make_adjusted(tickers, n_days, start_offsets={"T03": 8, "T04": 20}, seed=seed)
    universe = make_universe(adjusted, None, seed=seed + 1)
    return adjusted, universe, cal, lcfg([h])


@pytest.mark.unit
def test_cross_sectional_properties_on_random_panel() -> None:
    h = 3
    adjusted, universe, cal, cfg = _random_case(h)
    out = build_labels(adjusted, universe, cfg, cal, min_names=5)
    cs = out[out[f"excess_h{h}"].notna()].copy()
    assert len(cs) > 100
    g = cs.groupby("date")
    # excess has mean zero per date; y_cls matches its sign; ranks live in (0, 1], best = 1.0
    np.testing.assert_allclose(g[f"excess_h{h}"].mean().to_numpy(), 0.0, atol=1e-15)
    assert (cs[f"y_cls_h{h}"] == (cs[f"excess_h{h}"] > 0).astype(float)).all()
    assert set(cs[f"y_cls_h{h}"].unique()) <= {0.0, 1.0}
    assert (cs[f"rank_pct_h{h}"] > 0).all() and (cs[f"rank_pct_h{h}"] <= 1.0).all()
    assert (g[f"rank_pct_h{h}"].max() == 1.0).all()
    best = cs.loc[g[f"ret_fwd_h{h}"].idxmax()]
    assert (best[f"rank_pct_h{h}"] == 1.0).all()
    # y_reg is the per-date clip of excess: inside [lo, hi] and equal to excess in between
    lo = g[f"excess_h{h}"].transform(lambda s: s.quantile(0.01))
    hi = g[f"excess_h{h}"].transform(lambda s: s.quantile(0.99))
    assert (cs[f"y_reg_h{h}"] >= lo - 1e-15).all() and (cs[f"y_reg_h{h}"] <= hi + 1e-15).all()
    inside = (cs[f"excess_h{h}"] >= lo) & (cs[f"excess_h{h}"] <= hi)
    assert (cs.loc[inside, f"y_reg_h{h}"] == cs.loc[inside, f"excess_h{h}"]).all()
    assert (cs.loc[~inside, f"y_reg_h{h}"] != cs.loc[~inside, f"excess_h{h}"]).all()
    assert (~inside).any()  # the clip actually bites somewhere (excess is not clipped itself)
    # winsor_pct is honoured
    wide = build_labels(adjusted, universe, lcfg([h], winsor=[0.0, 1.0]), cal, min_names=5)
    np.testing.assert_array_equal(
        wide[f"y_reg_h{h}"].to_numpy(), wide[f"excess_h{h}"].to_numpy()
    )


@pytest.mark.unit
def test_matches_independent_pivot_reference() -> None:
    """Row-shift implementation == a pivot (dates x tickers) reference on a ragged panel."""
    h = 4
    adjusted, universe, cal, cfg = _random_case(h)
    out = build_labels(adjusted, universe, cfg, cal, min_names=1)
    px = adjusted.pivot(index="t_idx", columns="ticker", values="adj_open").reindex(
        range(cal.n_days)
    )
    ref = np.log(px.shift(-(1 + h))) - np.log(px.shift(-1))
    ref_long = ref.stack(future_stack=True).rename("ref").reset_index()
    got = out.merge(adjusted[["ticker", "date", "t_idx"]], on=["ticker", "date"]).merge(
        ref_long, on=["t_idx", "ticker"], how="left"
    )
    np.testing.assert_allclose(
        got[f"ret_fwd_h{h}"].to_numpy(), got["ref"].to_numpy(), rtol=0, atol=1e-13,
        equal_nan=True,
    )
    elig = universe.set_index(["ticker", "date"])["eligible"]
    got_elig = elig.reindex(pd.MultiIndex.from_frame(got[["ticker", "date"]])).to_numpy()
    both = got_elig & got["ref"].notna().to_numpy()
    assert (got[f"excess_h{h}"].notna().to_numpy() == both).all()
    mean_ref = got[both].groupby("date")["ref"].transform("mean")
    np.testing.assert_allclose(
        got.loc[both, f"excess_h{h}"].to_numpy(), (got.loc[both, "ref"] - mean_ref).to_numpy(),
        rtol=0, atol=1e-13,
    )


@pytest.mark.unit
def test_ineligible_rows_never_enter_cross_sectional_statistics() -> None:
    h = 3
    adjusted, universe, cal, cfg = _random_case(h)
    base = build_labels(adjusted, universe, cfg, cal, min_names=5)
    # wildly change the future price path of one ticker that is ineligible on every date
    universe2 = universe.copy()
    universe2.loc[universe2["ticker"] == "T07", "eligible"] = False
    ref = build_labels(adjusted, universe2, cfg, cal, min_names=5)
    adjusted2 = adjusted.copy()
    m = adjusted2["ticker"] == "T07"
    adjusted2.loc[m, "adj_open"] = adjusted2.loc[m, "adj_open"] * np.linspace(1.0, 40.0, m.sum())
    poisoned = build_labels(adjusted2, universe2, cfg, cal, min_names=5)
    others = ref["ticker"] != "T07"
    cols = [c for c in ref.columns if c.endswith(f"h{h}") and not c.startswith("ret_fwd")]
    pd.testing.assert_frame_equal(ref.loc[others, cols], poisoned.loc[others, cols])
    # ... and T07 itself has no cross-sectional labels, only the always-populated columns
    t07 = ref[~others]
    assert t07[f"excess_h{h}"].isna().all() and t07[f"rank_pct_h{h}"].isna().all()
    assert t07[f"has_label_h{h}"].any() and (t07[f"label_exit_idx_h{h}"] > 0).all()
    # sanity: the first (eligibility-random) universe does differ from the all-T07-out one
    assert not base.equals(ref)


@pytest.mark.unit
def test_minimum_cross_section_size_and_warning() -> None:
    h = 2
    tickers = [f"T{i:02d}" for i in range(25)]
    adjusted, cal = make_adjusted(tickers, 30, seed=8)
    # day t=5: exactly 20 eligible names; day t=6: only 19 eligible; other days: all 25
    def rule(tk, i):
        k = int(tk[1:])
        return not (i == 5 and k >= 20) and not (i == 6 and k >= 19)

    universe = make_universe(adjusted, eligible_where(adjusted, rule))
    cfg = lcfg([h])
    seen: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    handler = Grab(level=logging.WARNING)
    lg = logging.getLogger("nasdaq100.labels.forward_returns")
    lg.addHandler(handler)
    try:
        out = build_labels(adjusted, universe, cfg, cal)  # default min_names = 20
    finally:
        lg.removeHandler(handler)
    n_by_date = out.groupby("date")[f"excess_h{h}"].count()
    assert n_by_date[DATES_AT(5)] == 20  # exactly the minimum: labelled
    assert n_by_date[DATES_AT(6)] == 0  # one below: all NaN
    assert n_by_date[DATES_AT(7)] == 25
    thin = out[out["date"] == DATES_AT(6)]
    assert thin[f"has_label_h{h}"].all() and thin[f"ret_fwd_h{h}"].notna().all()
    assert any(r.levelno == logging.WARNING and "fewer than 20" in r.getMessage() for r in seen)
    # with a lower threshold the same date is labelled
    low = build_labels(adjusted, universe, cfg, cal, min_names=19)
    assert low[low["date"] == DATES_AT(6)][f"excess_h{h}"].count() == 19


def DATES_AT(i: int) -> pd.Timestamp:
    return pd.bdate_range("2020-01-06", periods=30)[i]


@pytest.mark.unit
def test_exact_ties_get_class_zero_and_average_rank() -> None:
    # two names with identical price paths: both excess == 0 exactly -> y_cls = 0 (strict >)
    a, cal = make_adjusted(["AAA"], 12, seed=1)
    b = a.copy()
    b["ticker"] = "BBB"
    adjusted = pd.concat([a, b], ignore_index=True)
    out = build_labels(adjusted, make_universe(adjusted), lcfg([2]), cal, min_names=2)
    cs = out[out["excess_h2"].notna()]
    assert len(cs) == 2 * (12 - 3)
    assert (cs["excess_h2"] == 0.0).all() and (cs["y_cls_h2"] == 0.0).all()
    assert (cs["y_reg_h2"] == 0.0).all()
    assert (cs["rank_pct_h2"] == 0.75).all()  # average rank of a two-way tie: (1 + 2) / 2 / 2


@pytest.mark.unit
def test_early_ending_ticker_gets_no_label_without_a_price() -> None:
    h = 3
    # BBB stops 6 days early; CCC follows it in the sorted table, so a shift that ignored the
    # ticker boundary would silently pick up CCC's first prices as BBB's exit prices.
    adjusted, cal = make_adjusted(["AAA", "BBB", "CCC"], 20, end_offsets={"BBB": 6}, seed=2)
    out = build_labels(adjusted, make_universe(adjusted), lcfg([h]), cal, min_names=1)
    bbb = out[out["ticker"] == "BBB"].reset_index(drop=True)  # rows t = 0..13, then data ends
    assert len(bbb) == 14
    # exit idx t+1+h is on the calendar for every row here, but BBB has no price after t=13
    assert (bbb["label_exit_idx_h3"] <= cal.last_idx).all()
    assert bbb["has_label_h3"].tolist() == [True] * 10 + [False] * 4  # t=10..13 lack t+4 data
    assert bbb.loc[10:, "ret_fwd_h3"].isna().all()
    for tk in ("AAA", "CCC"):
        assert out.loc[out["ticker"] == tk, "has_label_h3"].sum() == 20 - (h + 1)


@pytest.mark.unit
def test_only_adj_open_is_used() -> None:
    h = 5
    adjusted, universe, cal, cfg = _random_case(h)
    base = build_labels(adjusted, universe, cfg, cal, min_names=5)
    other = adjusted.copy()
    rng = np.random.default_rng(0)
    for col in ("adj_factor", "adj_high", "adj_low", "adj_close", "dollar_volume", "logret_cc"):
        other[col] = rng.uniform(0.5, 500.0, size=len(other))
    other["volume"] = 7
    pd.testing.assert_frame_equal(build_labels(other, universe, cfg, cal, min_names=5), base)


@pytest.mark.unit
def test_horizon_columns_are_independent_and_named_per_spec() -> None:
    adjusted, universe, cal, _ = _random_case(3)
    both = build_labels(adjusted, universe, lcfg([3, 7]), cal, min_names=5)
    only3 = build_labels(adjusted, universe, lcfg([3]), cal, min_names=5)
    only7 = build_labels(adjusted, universe, lcfg([7]), cal, min_names=5)
    assert list(both.columns) == label_columns([3, 7])
    assert list(both.columns)[:2] == ["ticker", "date"]
    stems = ["ret_fwd_h", "excess_h", "y_reg_h", "y_cls_h", "rank_pct_h", "label_exit_idx_h",
             "has_label_h"]
    assert list(both.columns)[2:9] == [f"{s}3" for s in stems]
    assert list(both.columns)[9:] == [f"{s}7" for s in stems]
    pd.testing.assert_frame_equal(both[only3.columns], only3)
    pd.testing.assert_frame_equal(both[only7.columns], only7)
    # the two horizons really are different quantities
    assert not both["ret_fwd_h3"].equals(both["ret_fwd_h7"])


@pytest.mark.unit
def test_output_schema_dtypes_order_and_input_not_modified() -> None:
    adjusted, universe, cal, cfg = _random_case(3)
    sa = adjusted.sample(frac=1.0, random_state=1).reset_index(drop=True)
    su = universe.sample(frac=1.0, random_state=2).reset_index(drop=True)
    before = (sa.copy(), su.copy())
    out = build_labels(sa, su, cfg, cal, min_names=5)
    pd.testing.assert_frame_equal(sa, before[0])
    pd.testing.assert_frame_equal(su, before[1])
    pd.testing.assert_frame_equal(out, build_labels(adjusted, universe, cfg, cal, min_names=5))
    assert len(out) == len(adjusted)  # rows never dropped
    assert out[["ticker", "date"]].equals(
        adjusted.sort_values(["ticker", "date"]).reset_index(drop=True)[["ticker", "date"]]
    )
    assert out["date"].dtype == "datetime64[ns]"
    for stem in ("ret_fwd_h3", "excess_h3", "y_reg_h3", "y_cls_h3", "rank_pct_h3"):
        assert out[stem].dtype == "float64"
    assert out["label_exit_idx_h3"].dtype == "int32" and out["has_label_h3"].dtype == "bool"
    assert out["label_exit_idx_h3"].notna().all()


@pytest.mark.unit
def test_contiguity_key_and_input_validation() -> None:
    adjusted, universe, cal, cfg = _random_case(3)
    # internal gap in one ticker: dropping a middle row from both tables keeps keys equal
    # but makes row shifts invalid -> must raise
    gap = adjusted[~((adjusted["ticker"] == "T01") & (adjusted["t_idx"] == 20))]
    gap_u = make_universe(gap, True)
    with pytest.raises(LabelError, match="consecutive"):
        build_labels(gap, gap_u, cfg, cal)
    # key mismatch between universe and adjusted
    with pytest.raises(LabelError, match="identical"):
        build_labels(adjusted, universe.iloc[:-1], cfg, cal)
    # t_idx inconsistent with the calendar
    shifted = adjusted.copy()
    shifted["t_idx"] = shifted["t_idx"] + 1
    with pytest.raises(LabelError, match="calendar"):
        build_labels(shifted, universe, cfg, cal)
    # date off the calendar
    short = TradingCalendar.from_dates(cal.dates[:30])
    with pytest.raises(LabelError, match="not on the calendar"):
        build_labels(adjusted, universe, cfg, short)
    # missing columns / empty / duplicates / NaN / non-positive
    with pytest.raises(LabelError, match="missing columns"):
        build_labels(adjusted.drop(columns=["adj_open"]), universe, cfg, cal)
    with pytest.raises(LabelError, match="missing columns"):
        build_labels(adjusted, universe.drop(columns=["eligible"]), cfg, cal)
    with pytest.raises(LabelError, match="empty"):
        build_labels(adjusted.iloc[0:0], universe, cfg, cal)
    dup = pd.concat([adjusted, adjusted.iloc[[0]]], ignore_index=True)
    with pytest.raises(LabelError, match="duplicate"):
        build_labels(dup, universe, cfg, cal)
    nan = adjusted.copy()
    nan.loc[5, "adj_open"] = np.nan
    with pytest.raises(LabelError, match="NaN adj_open"):
        build_labels(nan, universe, cfg, cal)
    neg = adjusted.copy()
    neg.loc[5, "adj_open"] = 0.0
    with pytest.raises(LabelError, match="non-positive"):
        build_labels(neg, universe, cfg, cal)
    nan_u = universe.copy().astype({"eligible": "object"})
    nan_u.loc[3, "eligible"] = None
    with pytest.raises(LabelError, match="eligible"):
        build_labels(adjusted, nan_u, cfg, cal)


@pytest.mark.unit
def test_config_validation() -> None:
    adjusted, universe, cal, _ = _random_case(3)
    for horizons, primary, winsor, match in (
        ([], 20, None, "empty"),
        ([0, 20], 20, None, "positive"),
        ([20, 20], 20, None, "duplicates"),
        ([5], 20, None, "primary_horizon"),
        ([5], 5, [0.99, 0.01], "winsor_pct"),
        ([5], 5, [-0.1, 0.9], "winsor_pct"),
        ([5], 5, [0.1], "winsor_pct"),
    ):
        cfg = lcfg(horizons, primary, winsor) if horizons else load_config(
            overrides=["labels.horizons=[]"]).labels
        with pytest.raises(LabelError, match=match):
            build_labels(adjusted, universe, cfg, cal)
    # the shipped defaults are valid and give h=20 columns
    default = load_config().labels
    big_adj, cal2 = make_adjusted(["A", "B"], 40)
    out = build_labels(big_adj, make_universe(big_adj), default, cal2, min_names=1)
    assert list(out.columns) == label_columns([20])


@pytest.mark.unit
def test_run_build_labels_roundtrip_variant_and_determinism(tmp_path, monkeypatch) -> None:
    tickers = [f"T{i:02d}" for i in range(22)]  # >= the default 20-name minimum
    adjusted, cal = make_adjusted(tickers, 30, seed=6)
    universe = make_universe(adjusted)
    cfg = load_config(overrides=["labels.horizons=[3]", "labels.primary_horizon=3"])
    a_file, u_file, c_file = (tmp_path / n for n in ("a.parquet", "u.parquet", "c.parquet"))
    write_parquet(adjusted, a_file)
    write_parquet(universe, u_file)
    write_parquet(cal.frame, c_file, sort_keys=("date",))
    out_file = tmp_path / "out" / "labels.parquet"
    kw = {"adjusted_file": a_file, "universe_file": u_file, "calendar_file": c_file,
          "labels_file": out_file}
    built = run_build_labels(cfg, **kw)
    assert out_file.is_file()
    assert built["excess_h3"].notna().sum() == 22 * (30 - 4)
    loaded = load_labels(cfg, out_file)
    pd.testing.assert_frame_equal(loaded, built)
    pd.testing.assert_frame_equal(run_build_labels(cfg, **kw), built)
    assert list(loaded.columns) == label_columns([3])

    # default output path follows the variant
    seen: list[str] = []

    def fake_path(variant: str = "base"):
        seen.append(variant)
        return tmp_path / variant / "labels.parquet"

    monkeypatch.setattr(fr, "labels_path", fake_path)
    cfg2 = load_config(
        overrides=["labels.horizons=[3]", "labels.primary_horizon=3", "project.variant=exp1"]
    )
    run_build_labels(cfg2, adjusted_file=a_file, universe_file=u_file, calendar_file=c_file)
    assert seen == ["exp1"] and (tmp_path / "exp1" / "labels.parquet").is_file()
    assert len(load_labels(cfg2)) == len(adjusted)


@pytest.mark.unit
def test_run_build_labels_missing_inputs_and_load_errors(tmp_path) -> None:
    cfg = load_config(overrides=["labels.horizons=[3]", "labels.primary_horizon=3"])
    adjusted, universe, cal, _ = _random_case(3)
    a_file, u_file = tmp_path / "a.parquet", tmp_path / "u.parquet"
    write_parquet(adjusted, a_file)
    write_parquet(universe, u_file)
    with pytest.raises(FileNotFoundError, match="build-adjusted"):
        run_build_labels(cfg, adjusted_file=tmp_path / "none.parquet", universe_file=u_file,
                         calendar_file=tmp_path / "c.parquet")
    with pytest.raises(FileNotFoundError, match="build-universe"):
        run_build_labels(cfg, adjusted_file=a_file, universe_file=tmp_path / "none.parquet",
                         calendar_file=tmp_path / "c.parquet")
    with pytest.raises(FileNotFoundError, match="Calendar"):
        run_build_labels(cfg, adjusted_file=a_file, universe_file=u_file,
                         calendar_file=tmp_path / "c.parquet")
    with pytest.raises(FileNotFoundError, match="build-labels"):
        load_labels(cfg, tmp_path / "missing.parquet")
    wrong = tmp_path / "wrong.parquet"
    write_parquet(pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp("2020-01-06")]}), wrong)
    with pytest.raises(LabelError, match="columns"):
        load_labels(cfg, wrong)
