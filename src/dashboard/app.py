"""
Streamlit dashboard for the Stack Overflow new-contributor retention project.

Reads only the small committed summaries in data/summary/ (built by
`python -m src.analysis.summaries` from the notebook outputs), so it runs on a fresh
clone, in the Docker image and on the Hugging Face Space without BigQuery access:

    data/summary/headline.json               cohort-level counts and rates (notebook 01)
    data/summary/cohort_monthly.parquet      one row per cohort month   (notebook 01)
    data/summary/treatment_effects.parquet   four estimators x two outcomes (notebook 02)
    data/summary/robustness.parquet          treatment / spec / year swaps (notebook 03)
    data/summary/heterogeneity.parquet       body / code / tag / year cuts (notebook 04)
    data/summary/predictive_*.parquet        classifier ladder + SHAP (notebook 05)

Launch with `make dashboard` or `streamlit run src/dashboard/app.py`.
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

# ── Setup ─────────────────────────────────────────────────────────────────────
SUMMARY_DIR = Path(__file__).resolve().parents[2] / "data" / "summary"
REPO_URL = "https://github.com/bass990/stackoverflow-causal-retention"

st.set_page_config(
    page_title="SO new-contributor retention",
    page_icon=":bar_chart:",
    layout="wide",
)


# ── Cached loaders ────────────────────────────────────────────────────────────
@st.cache_data
def load_headline() -> dict:
    return json.loads((SUMMARY_DIR / "headline.json").read_text(encoding="utf-8"))


@st.cache_data
def load_artifact(name: str) -> pd.DataFrame:
    return pd.read_parquet(SUMMARY_DIR / name)


@st.cache_data
def load_monthly() -> pd.DataFrame:
    df = load_artifact("cohort_monthly.parquet")
    df["cohort_month_dt"] = pd.to_datetime(df["cohort_month"])
    return df.sort_values("cohort_month_dt")


def effect_bars(sub: pd.DataFrame, value: str, lo: str, hi: str, label: str,
                xlabel: str, colors=None, height: float | None = None):
    """Horizontal bars with 95% CI whiskers, one row per estimate."""
    fig, ax = plt.subplots(figsize=(10, height or max(3, len(sub) * 0.45)))
    y = np.arange(len(sub))
    ax.barh(y, sub[value], color=colors or "steelblue", alpha=0.85)
    for i, row in sub.reset_index(drop=True).iterrows():
        if pd.notna(row[lo]):
            ax.plot([row[lo], row[hi]], [i, i], "k-", lw=2)
        ax.text(row[value] + 0.1, i, f"{row[value]:+.2f}", va="center")
    ax.set_yticks(y); ax.set_yticklabels(sub[label])
    ax.axvline(0, color="black", lw=0.5)
    ax.set_xlabel(xlabel)
    ax.invert_yaxis()
    st.pyplot(fig)
    plt.close(fig)


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "View",
    [
        "Overview",
        "Funnel and retention",
        "Causal estimates",
        "Robustness",
        "Heterogeneity",
        "Predictive model",
        "About the project",
    ],
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "Mamadou Bassirou Diallo, MSBA+AI candidate, UT Dallas. "
    f"[Source on GitHub]({REPO_URL})."
)


# ── Pages ─────────────────────────────────────────────────────────────────────
def page_overview():
    h = load_headline()
    st.title("Stack Overflow new-contributor retention")
    st.markdown(
        f"Causal-inference project on {h['n_question_first']:,} new Stack Overflow contributors who "
        f"posted their first question between {h['first_cohort_month'][:7]} and "
        f"{h['last_cohort_month'][:7]}. The question: "
        "**does getting an answer to your first question keep you on the platform?**"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Question-first cohort", f"{h['n_question_first']:,}")
    c2.metric("Active at D30", f"{h['active_d30_rate']*100:.1f}%")
    c3.metric("Active at D180 (observable)", f"{h['active_d180_rate_observable']*100:.1f}%")
    c4.metric("Got answer within 24h", f"{h['got_answer_within_24h_rate']*100:.1f}%")

    st.subheader("Cohort size by month")
    monthly = load_monthly()
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(monthly["cohort_month_dt"], monthly["users"], marker="o", color="steelblue")
    ax.set_ylabel("users")
    ax.set_title(f"Monthly new-contributor count, {h['first_cohort_month'][:7]} to {h['last_cohort_month'][:7]}")
    ax.grid(alpha=0.3)
    st.pyplot(fig)
    plt.close(fig)

    st.subheader("Headline finding")
    te = load_artifact("treatment_effects.parquet").set_index(["outcome", "method"])
    ols30 = te.loc[("D30", "Controlled OLS")]
    ols180 = te.loc[("D180", "Controlled OLS")]
    st.info(
        "Getting an answer within 24 hours of your first question is associated with "
        f"**{ols30['estimate_pp']:+.1f} pp higher D30 retention** (controlled OLS, 95% CI "
        f"[{ols30['ci_low_pp']:+.2f}, {ols30['ci_high_pp']:+.2f}]). "
        f"The effect shrinks to {ols180['estimate_pp']:+.1f} pp at six months. The estimate is robust to "
        "swapping covariates, adding tighter time fixed effects, and stratifying "
        "by propensity score. An instrumental-variable analysis using posting hour "
        "as the instrument produced a large negative estimate, which points to a violated "
        "exclusion restriction; it is reported but not used as the headline."
    )


def page_funnel():
    h = load_headline()
    st.title("Funnel and retention")

    st.subheader("Engagement funnel, first question")
    funnel = pd.DataFrame({
        "stage": ["Posted first question", "Got any answer ever",
                  "Got answer within 24h", "Got answer within 1h"],
        "% of cohort": [100.0,
                        round(h["got_any_answer_rate"] * 100, 1),
                        round(h["got_answer_within_24h_rate"] * 100, 1),
                        round(h["got_answer_within_1h_rate"] * 100, 1)],
    })
    st.dataframe(funnel, width="stretch", hide_index=True)

    st.subheader("Retention outcomes")
    ret = pd.DataFrame({
        "outcome": ["Active at D30", "Active at D180 (observable)"],
        "pct": [h["active_d30_rate"] * 100, h["active_d180_rate_observable"] * 100],
    })
    st.dataframe(ret.style.format({"pct": "{:.1f}"}), width="stretch", hide_index=True)
    st.caption(
        f"{h['n_d180_observable']:,} users ({h['share_d180_observable']*100:.1f}% of the cohort) "
        f"are old enough at the {h['data_snapshot_date']} snapshot for the D180 outcome to be observed."
    )

    st.subheader("Cohort-month trend, retention and engagement rates")
    monthly = load_monthly()
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(monthly["cohort_month_dt"], monthly["d30_rate"] * 100, marker="o", label="D30 retention", color="steelblue")
    ax.plot(monthly["cohort_month_dt"], monthly["got_24h_rate"] * 100, marker="o", label="Got answer within 24h", color="orange")
    ax.plot(monthly["cohort_month_dt"], monthly["d180_rate"] * 100, marker="o", label="D180 retention (observable)", color="green")
    ax.set_ylabel("rate (%)"); ax.legend(); ax.grid(alpha=0.3)
    st.pyplot(fig)
    plt.close(fig)


def page_causal():
    st.title("Causal estimates")
    st.markdown(
        "Four estimators applied to the same treatment, got-answer-within-24h, "
        "for the D30 and D180 outcomes. The naive lift is shown for reference."
    )

    te = load_artifact("treatment_effects.parquet")
    for outcome in ["D30", "D180"]:
        st.subheader(f"{outcome} outcome")
        sub = te[te["outcome"] == outcome][["method", "estimate_pp", "se_pp", "ci_low_pp", "ci_high_pp", "n"]]
        st.dataframe(
            sub.style.format({
                "estimate_pp": "{:+.2f}", "se_pp": "{:.3f}",
                "ci_low_pp": "{:+.2f}", "ci_high_pp": "{:+.2f}", "n": "{:,}",
            }),
            width="stretch", hide_index=True,
        )
        effect_bars(sub, "estimate_pp", "ci_low_pp", "ci_high_pp", "method",
                    "Effect (percentage points)",
                    colors=["gray", "steelblue", "steelblue", "steelblue", "darkorange"], height=4)

    st.warning(
        "The 2SLS estimate is strongly negative. The first-stage F is above 1000, so the "
        "instrument is not statistically weak, but the negative point estimate suggests "
        "the exclusion restriction is violated. Posting hour correlates with unobserved "
        "user characteristics (timezone, hobbyist vs professional, urgency) that directly "
        "affect retention. Treat the IV result as evidence of unobserved confounding, not "
        "as the causal estimate. `tests/test_estimators.py` reproduces this failure mode on "
        "synthetic data."
    )


def page_robustness():
    st.title("Robustness")
    st.markdown(
        "Three checks on the headline D30 estimate: treatment-definition swaps, "
        "specification variations, and cohort-year subsamples."
    )

    rob = load_artifact("robustness.parquet")
    for kind, title in [
        ("treatment", "Treatment definition (D30 outcome)"),
        ("specification", "Specification (got-answer-within-24h, D30)"),
        ("subsample", "Cohort year (got-answer-within-24h, D30)"),
    ]:
        st.subheader(title)
        sub = rob[rob["kind"] == kind]
        st.dataframe(
            sub[["label", "controlled_pp", "se_pp", "ci_low", "ci_high"]].style.format({
                "controlled_pp": "{:+.2f}", "se_pp": "{:.3f}", "ci_low": "{:+.2f}", "ci_high": "{:+.2f}",
            }),
            width="stretch", hide_index=True,
        )
        effect_bars(sub, "controlled_pp", "ci_low", "ci_high", "label", "D30 effect (percentage points)")


def page_het():
    st.title("Heterogeneity")
    st.markdown(
        "Where does the average treatment effect concentrate? Four cuts: "
        "body length quartile, code-block presence, primary tag, cohort year."
    )

    het = load_artifact("heterogeneity.parquet")
    for kind, title in [
        ("body_quartile", "By body-length quartile"),
        ("code_block", "By code-block presence"),
        ("tag", "By primary tag"),
        ("year", "By cohort year"),
    ]:
        st.subheader(title)
        sub = het[het["kind"] == kind].sort_values("estimate_pp", ascending=False)
        st.dataframe(
            sub[["label", "n", "share", "estimate_pp", "ci_low", "ci_high"]].style.format({
                "n": "{:,}", "share": "{:.2%}",
                "estimate_pp": "{:+.2f}", "ci_low": "{:+.2f}", "ci_high": "{:+.2f}",
            }),
            width="stretch", hide_index=True,
        )
        effect_bars(sub, "estimate_pp", "ci_low", "ci_high", "label", "D30 effect (percentage points)")

    years = het[het["kind"] == "year"].set_index("label")["estimate_pp"]
    tags = het[het["kind"] == "tag"].set_index("label")["estimate_pp"]
    st.info(
        "Two findings worth noting. First, the answer-retention link nearly doubled "
        f"between 2018 ({years.min():+.2f} pp) and 2022 ({years.max():+.2f} pp), consistent with "
        "alternative help sources making SO answers more differentiating over time. Second, the "
        f"treatment effect varies sharply by language: {tags.idxmax()} users benefit most "
        f"({tags.max():+.1f} pp), {tags.idxmin()} users least ({tags.min():+.1f} pp). Likely reflects "
        "differences in alternative help sources and community size by language."
    )


def page_predictive():
    st.title("Predictive model")
    st.markdown(
        "Notebook 05 walks a four-step ladder. v1 is a logistic-regression baseline and a "
        "gradient-boosted classifier on 14 first-post features. v2 adds engineered features "
        "(top-30 tag one-hots, pairwise interactions, polynomial terms). v3 tunes the booster. "
        "v4 calibrates its probabilities. The ladder surfaces a real ceiling, not a "
        "model-engineering shortfall."
    )

    st.subheader("Model ladder, held-out metrics")
    metrics = load_artifact("predictive_metrics.parquet")
    st.dataframe(
        metrics.style.format({"roc_auc": "{:.4f}", "pr_auc": "{:.4f}", "brier": "{:.4f}"}),
        width="stretch", hide_index=True,
    )
    best = metrics.loc[metrics["roc_auc"].idxmax()]
    base = metrics[metrics["model"].str.startswith("v1 GBM")]["roc_auc"].iloc[0]
    st.caption(
        f"Best ROC AUC {best['roc_auc']:.4f} ({best['model']}), "
        f"{(best['roc_auc'] - base) * 100:+.2f} pp over the v1 GBM baseline."
    )

    st.subheader("Feature importance, v3 tuned GBM (mean |SHAP|, top 20)")
    shap_imp = load_artifact("predictive_shap.parquet").head(20)
    fig, ax = plt.subplots(figsize=(10, 8))
    y = np.arange(len(shap_imp))
    ax.barh(y, shap_imp["mean_abs_shap"], color="steelblue", alpha=0.85)
    ax.set_yticks(y); ax.set_yticklabels(shap_imp["feature"])
    ax.set_xlabel("Mean |SHAP value|")
    ax.invert_yaxis()
    st.pyplot(fig)
    plt.close(fig)

    st.subheader("Logistic baseline, standardised coefficients")
    coefs = load_artifact("predictive_logit_coefs.parquet")
    st.dataframe(coefs.style.format({"coef_std": "{:+.3f}"}), width="stretch", hide_index=True)

    h = load_headline()
    st.subheader("Why the AUC is what it is")
    st.markdown(
        "Three structural reasons.\n\n"
        f"1. The base rate is {h['active_d30_rate']*100:.0f}%. Models on imbalanced binary outcomes with "
        "weak features cap at moderate AUC.\n\n"
        "2. The biggest drivers of whether a new contributor returns are not "
        "observable from first-post data. Prior programming experience, motivation, "
        "alternative help sources, whether the user got their answer elsewhere. The "
        "14 first-post features are weak proxies for all of that.\n\n"
        "3. The ladder confirms the ceiling. Tag one-hots, interactions, polynomial terms, "
        "hyperparameter tuning and calibration together move AUC by less than half a "
        "percentage point. The information just isn't there.\n\n"
        "What would push AUC up meaningfully: TF-IDF or embeddings on body/title "
        "text (would require re-running sql-04 with the body column kept, about $0.14 "
        "in BigQuery scan). Out of scope here."
    )


def page_about():
    h = load_headline()
    st.title("About this project")
    st.markdown(
        f"""
The data lives in BigQuery's public Stack Overflow dataset, snapshot through
{h['data_snapshot_date']}. The analysis flow is five SQL files in sequence, followed by five
notebooks. SQL extracts cohort definitions, retention outcomes, engagement
funnel, first-post features, and an instrumental-variable lookup. Notebooks
do EDA, causal estimation with four side-by-side methods, robustness checks,
heterogeneity by user segment, and predictive modeling.

The four estimators live in `src/analysis/estimators.py` and are tested on synthetic
data with a known effect, including the case where an instrument violates the
exclusion restriction. This dashboard reads only the small summaries in `data/summary/`,
so it runs without a BigQuery project.

Tech stack: Python 3.12+, pandas, numpy, statsmodels for OLS and IPW,
linearmodels for 2SLS, scikit-learn for the predictive models, SHAP for feature
attribution, Streamlit for this dashboard, BigQuery for the data extraction.

Cost summary: roughly 44 GB of BigQuery scan across the five SQL files,
about $0.22 at the $5 per TB rate, well under the 1 TB per month free tier.

Source code on GitHub: [{REPO_URL.removeprefix('https://')}]({REPO_URL}).
"""
    )


PAGES = {
    "Overview": page_overview,
    "Funnel and retention": page_funnel,
    "Causal estimates": page_causal,
    "Robustness": page_robustness,
    "Heterogeneity": page_het,
    "Predictive model": page_predictive,
    "About the project": page_about,
}
PAGES[page]()
