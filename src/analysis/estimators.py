"""The four treatment-effect estimators used in notebook 02, as importable functions.

Each `fit_*` function takes a DataFrame, an outcome column, a binary treatment column
and a covariate formula fragment, and returns one row of the treatment-effects table:

    {"method", "estimate_pp", "se_pp", "ci_low_pp", "ci_high_pp", "n", ...}

Estimates are in percentage points. The notebooks call these on the 1.77M-row master
table; `tests/test_estimators.py` calls them on synthetic data with a known effect.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from linearmodels.iv import IV2SLS

TREATMENT = "got_answer_within_24h"
INSTRUMENT = "hour_instrument_rate"

COVARIATES_FULL = (
    "log_body_length + title_length + has_code_block + has_link + has_image "
    "+ num_tags + C(day_of_week) + C(hour_of_day_utc) + C(cohort_year)"
)
# The instrument is a function of posting hour, so hour cannot also be a control.
COVARIATES_IV = (
    "log_body_length + title_length + has_code_block + has_link + has_image "
    "+ num_tags + C(day_of_week) + C(cohort_year)"
)

_FLOAT_COLS = [
    "active_d30", "active_d180", "got_answer_within_24h", "got_answer_within_1h",
    "got_any_answer", "has_code_block", "has_link", "has_image", "is_weekend",
    "title_length", "num_tags", "hour_of_day_utc", "day_of_week", "d180_observable",
]


def prepare_master(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns the formulas need and cast nullable ints to float.

    statsmodels and linearmodels both choke on pandas' nullable Int64 dtype, which is
    what the BigQuery client hands back, so everything numeric becomes float64.
    """
    out = df.copy()
    out["log_body_length"] = np.log(out["body_length"].clip(lower=1)).astype(float)
    out["cohort_year"] = pd.to_datetime(out["cohort_month"]).dt.year.astype(int)
    for col in _FLOAT_COLS:
        if col in out.columns:
            out[col] = out[col].astype(float)
    if INSTRUMENT in out.columns:
        out[INSTRUMENT] = out[INSTRUMENT].astype(float)
    return out


def fit_naive(df: pd.DataFrame, outcome: str, treatment: str = TREATMENT) -> dict[str, Any]:
    """Raw difference in outcome means, treated minus control. No controls, no CI."""
    treated = df.loc[df[treatment] == 1, outcome].mean()
    control = df.loc[df[treatment] == 0, outcome].mean()
    return {
        "method": "Naive (uncontrolled)",
        "estimate_pp": (treated - control) * 100,
        "se_pp": np.nan, "ci_low_pp": np.nan, "ci_high_pp": np.nan,
        "n": int(len(df)),
    }


def fit_ols(df: pd.DataFrame, outcome: str, treatment: str = TREATMENT,
            covariates: str = COVARIATES_FULL) -> dict[str, Any]:
    """Linear probability model with HC3 robust errors. The coefficient is the pp lift."""
    model = smf.ols(f"{outcome} ~ {treatment} + {covariates}", data=df).fit(cov_type="HC3")
    ci_low, ci_high = model.conf_int().loc[treatment]
    return {
        "method": "Controlled OLS",
        "estimate_pp": model.params[treatment] * 100,
        "se_pp": model.bse[treatment] * 100,
        "ci_low_pp": ci_low * 100, "ci_high_pp": ci_high * 100,
        "n": int(model.nobs),
    }


def fit_ipw(df: pd.DataFrame, outcome: str, treatment: str = TREATMENT,
            covariates: str = COVARIATES_FULL, weight_quantile: float = 0.99) -> dict[str, Any]:
    """Inverse-propensity weighting: logit propensity, weights capped at the 99th pct,
    then a weighted LPM. Returns the propensity scores too, so PSM can reuse them."""
    ps_model = smf.logit(f"{treatment} ~ {covariates}", data=df).fit(disp=0, maxiter=50)
    ps = ps_model.predict(df)
    raw_weight = np.where(df[treatment] == 1, 1 / ps, 1 / (1 - ps))
    cap = float(np.quantile(raw_weight, weight_quantile))
    weight = np.clip(raw_weight, a_min=None, a_max=cap)

    model = smf.wls(f"{outcome} ~ {treatment} + {covariates}", data=df, weights=weight).fit(cov_type="HC3")
    ci_low, ci_high = model.conf_int().loc[treatment]
    return {
        "method": "IPW",
        "estimate_pp": model.params[treatment] * 100,
        "se_pp": model.bse[treatment] * 100,
        "ci_low_pp": ci_low * 100, "ci_high_pp": ci_high * 100,
        "n": int(model.nobs),
        "ps_range": (float(ps.min()), float(ps.max())),
        "weight_cap": cap,
        "ps": ps,
    }


def fit_psm_stratified(df: pd.DataFrame, outcome: str, ps: pd.Series | np.ndarray,
                       treatment: str = TREATMENT, n_strata: int = 10,
                       min_cell: int = 30) -> dict[str, Any]:
    """Propensity-score stratification: split on propensity deciles, take the treated
    minus control difference inside each, average the differences weighted by stratum
    size. Strata with fewer than `min_cell` treated or control users are skipped."""
    work = df[[outcome, treatment]].copy()
    work["ps_decile"] = pd.qcut(np.asarray(ps), n_strata, labels=False, duplicates="drop")

    rows = []
    for decile, g in work.groupby("ps_decile"):
        treated = g[g[treatment] == 1]
        control = g[g[treatment] == 0]
        if len(treated) < min_cell or len(control) < min_cell:
            continue
        rows.append({
            "decile": int(decile),
            "n": int(len(g)), "n_treated": int(len(treated)), "n_control": int(len(control)),
            "diff_pp": (treated[outcome].mean() - control[outcome].mean()) * 100,
            "var": treated[outcome].var(ddof=1) / len(treated) + control[outcome].var(ddof=1) / len(control),
        })
    table = pd.DataFrame(rows)
    if table.empty:
        raise ValueError("no propensity stratum had enough treated and control users")

    ate = float(np.average(table["diff_pp"], weights=table["n"]))
    w = table["n"] / table["n"].sum()
    se = float(np.sqrt(np.sum((w ** 2) * table["var"])) * 100)
    return {
        "method": "PSM stratified",
        "estimate_pp": ate, "se_pp": se,
        "ci_low_pp": ate - 1.96 * se, "ci_high_pp": ate + 1.96 * se,
        "n": int(table["n"].sum()),
        "strata_table": table,
    }


def fit_iv2sls(df: pd.DataFrame, outcome: str, treatment: str = TREATMENT,
               instrument: str = INSTRUMENT, covariates: str = COVARIATES_IV) -> dict[str, Any]:
    """Two-stage least squares with robust errors, plus the first-stage F statistic."""
    formula = f"{outcome} ~ 1 + {covariates} + [{treatment} ~ {instrument}]"
    model = IV2SLS.from_formula(formula, data=df).fit(cov_type="robust")
    ci = model.conf_int().loc[treatment]
    diag = model.first_stage.diagnostics.loc[treatment]
    return {
        "method": "2SLS (hour IV)",
        "estimate_pp": model.params[treatment] * 100,
        "se_pp": model.std_errors[treatment] * 100,
        "ci_low_pp": ci.iloc[0] * 100, "ci_high_pp": ci.iloc[1] * 100,
        "n": int(model.nobs),
        "first_stage_f": float(diag["f.stat"]),
        "first_stage_p": float(diag["f.pval"]),
    }


ROW_COLS = ["outcome", "method", "estimate_pp", "se_pp", "ci_low_pp", "ci_high_pp", "n"]


def estimate_all(df: pd.DataFrame, outcome: str, label: str, treatment: str = TREATMENT,
                 instrument: str = INSTRUMENT, covariates: str = COVARIATES_FULL,
                 covariates_iv: str = COVARIATES_IV) -> pd.DataFrame:
    """Run all five rows (naive + four estimators) for one outcome. Same table as
    notebook 02 writes to treatment_effects.parquet."""
    naive = fit_naive(df, outcome, treatment)
    ols = fit_ols(df, outcome, treatment, covariates)
    ipw = fit_ipw(df, outcome, treatment, covariates)
    psm = fit_psm_stratified(df, outcome, ipw["ps"], treatment)
    iv = fit_iv2sls(df, outcome, treatment, instrument, covariates_iv)
    rows = pd.DataFrame([naive, ols, ipw, psm, iv])
    rows["outcome"] = label
    return rows[ROW_COLS]
