"""Estimator tests on synthetic data with a known treatment effect.

The data-generating process mirrors the real problem: a confounder (question quality)
raises both the chance of getting an answer and the chance of coming back, so the naive
difference in means is biased upward. The controlled estimators see the confounder and
should recover the true effect; the IV estimator is handed a valid instrument and should
recover it too. Nothing here touches BigQuery or the real parquet files.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis import estimators as est

TRUE_EFFECT_PP = 8.0
N = 40_000


@pytest.fixture(scope="module")
def synthetic() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = N
    quality = rng.normal(size=n)                      # unobserved by the naive estimator only
    hour = rng.integers(0, 24, size=n)
    # Instrument: hour-level answer rate, exogenous to quality by construction and
    # strong enough that the first stage is not the thing being tested.
    instrument = 0.2 + 0.6 * (np.sin(hour / 24 * 2 * np.pi) + 1) / 2

    p_treat = 1 / (1 + np.exp(-(-0.4 + 1.2 * quality + 6.0 * (instrument - instrument.mean()))))
    treat = (rng.uniform(size=n) < p_treat).astype(float)

    base = 0.20 + 0.06 * quality
    p_out = np.clip(base + TRUE_EFFECT_PP / 100 * treat, 0.01, 0.99)
    outcome = (rng.uniform(size=n) < p_out).astype(float)

    return pd.DataFrame({
        "active_d30": outcome,
        "got_answer_within_24h": treat,
        "quality": quality,
        "hour_of_day_utc": hour.astype(float),
        "hour_instrument_rate": instrument,
        "cohort_year": rng.integers(2018, 2023, size=n),
        "day_of_week": rng.integers(1, 8, size=n).astype(float),
    })


COV = "quality + C(day_of_week) + C(cohort_year)"


def test_naive_is_biased_upward(synthetic):
    row = est.fit_naive(synthetic, "active_d30")
    assert row["method"] == "Naive (uncontrolled)"
    assert row["n"] == N
    assert np.isnan(row["se_pp"])
    # Quality pushes both treatment and outcome up, so the raw gap overstates the effect.
    assert row["estimate_pp"] > TRUE_EFFECT_PP + 1.5


def test_ols_recovers_effect_with_confounder_controlled(synthetic):
    row = est.fit_ols(synthetic, "active_d30", covariates=COV)
    assert row["method"] == "Controlled OLS"
    assert row["ci_low_pp"] < row["estimate_pp"] < row["ci_high_pp"]
    assert abs(row["estimate_pp"] - TRUE_EFFECT_PP) < 1.0
    assert row["ci_low_pp"] <= TRUE_EFFECT_PP <= row["ci_high_pp"]


def test_ipw_recovers_effect_and_returns_propensities(synthetic):
    row = est.fit_ipw(synthetic, "active_d30", covariates=COV)
    assert row["method"] == "IPW"
    assert abs(row["estimate_pp"] - TRUE_EFFECT_PP) < 1.0
    assert len(row["ps"]) == N
    assert 0.0 < row["ps_range"][0] < row["ps_range"][1] < 1.0
    assert row["weight_cap"] >= 1.0


def test_psm_stratified_recovers_effect(synthetic):
    ipw = est.fit_ipw(synthetic, "active_d30", covariates=COV)
    row = est.fit_psm_stratified(synthetic, "active_d30", ipw["ps"])
    assert row["method"] == "PSM stratified"
    assert abs(row["estimate_pp"] - TRUE_EFFECT_PP) < 1.5
    table = row["strata_table"]
    assert 5 <= len(table) <= 10
    assert (table["n_treated"] >= 30).all() and (table["n_control"] >= 30).all()
    assert row["n"] == table["n"].sum()


def test_psm_raises_when_no_stratum_is_usable(synthetic):
    tiny = synthetic.head(40)
    with pytest.raises(ValueError, match="stratum"):
        est.fit_psm_stratified(tiny, "active_d30", tiny["hour_instrument_rate"])


def test_iv_recovers_effect_with_valid_instrument(synthetic):
    # Hour is dropped from the controls because the instrument is a function of it.
    row = est.fit_iv2sls(synthetic, "active_d30", covariates="quality + C(day_of_week) + C(cohort_year)")
    assert row["method"] == "2SLS (hour IV)"
    assert row["first_stage_f"] > 10
    assert row["first_stage_p"] < 1e-6
    assert row["ci_low_pp"] <= TRUE_EFFECT_PP <= row["ci_high_pp"]
    assert abs(row["estimate_pp"] - TRUE_EFFECT_PP) < 3.0   # IV is noisier by nature


def test_iv_detects_exclusion_violation():
    """When the instrument also moves the outcome directly, 2SLS lands far from the
    truth while OLS (which keeps the instrument variable as a control, the way the real
    OLS keeps posting hour) stays close. This is the pattern the posting-hour IV showed."""
    rng = np.random.default_rng(11)
    n = 40_000
    quality = rng.normal(size=n)
    z = rng.uniform(0.3, 0.7, size=n)
    treat = (rng.uniform(size=n) < 1 / (1 + np.exp(-(-0.3 + quality + 4 * (z - 0.5))))).astype(float)
    # Direct path from the instrument into the outcome: the exclusion restriction fails.
    p_out = np.clip(0.2 + 0.05 * quality + 0.08 * treat - 0.6 * (z - 0.5), 0.01, 0.99)
    out = (rng.uniform(size=n) < p_out).astype(float)
    df = pd.DataFrame({
        "active_d30": out, "got_answer_within_24h": treat, "quality": quality,
        "hour_instrument_rate": z, "cohort_year": 2020, "day_of_week": 1.0,
    })
    ols = est.fit_ols(df, "active_d30", covariates="quality + hour_instrument_rate")
    iv = est.fit_iv2sls(df, "active_d30", covariates="quality")
    assert abs(ols["estimate_pp"] - 8.0) < 1.5
    assert iv["first_stage_f"] > 10               # not a weak-instrument problem
    assert iv["estimate_pp"] < 0                  # but the estimate is nonsense
    assert iv["ci_high_pp"] < ols["ci_low_pp"]    # and the two CIs do not overlap


def test_estimate_all_has_the_five_rows_in_order(synthetic):
    table = est.estimate_all(synthetic, "active_d30", "D30", covariates=COV,
                             covariates_iv="quality + C(day_of_week) + C(cohort_year)")
    assert list(table.columns) == est.ROW_COLS
    assert table["method"].tolist() == [
        "Naive (uncontrolled)", "Controlled OLS", "IPW", "PSM stratified", "2SLS (hour IV)",
    ]
    assert (table["outcome"] == "D30").all()
    controlled = table.set_index("method").loc[["Controlled OLS", "IPW", "PSM stratified"], "estimate_pp"]
    assert controlled.max() - controlled.min() < 1.0


def test_prepare_master_casts_and_derives():
    df = pd.DataFrame({
        "body_length": pd.array([0, 10, 1000], dtype="Int64"),
        "cohort_month": ["2018-01-01", "2020-06-01", "2022-09-01"],
        "active_d30": pd.array([1, 0, 1], dtype="Int64"),
        "hour_of_day_utc": pd.array([0, 12, 23], dtype="Int64"),
        "hour_instrument_rate": pd.array([0.5, 0.6, 0.7], dtype="Float64"),
    })
    out = est.prepare_master(df)
    assert out["log_body_length"].iloc[0] == 0.0          # clipped at 1 before the log
    assert out["cohort_year"].tolist() == [2018, 2020, 2022]
    assert out["active_d30"].dtype == float and out["hour_of_day_utc"].dtype == float
    assert out["hour_instrument_rate"].dtype == float
    assert "log_body_length" not in df.columns              # input untouched
