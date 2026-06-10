"""
Streamlit dashboard for the Stack Overflow new-contributor retention project.

Runs locally on the artifacts produced by the SQL pipeline and the 5 notebooks:
    data/processed/master.parquet            (notebook 01)
    data/processed/treatment_effects.parquet (notebook 02)
    data/processed/robustness.parquet        (notebook 03)
    data/processed/heterogeneity.parquet     (notebook 04)
    data/processed/predictive_*.parquet      (notebook 05)

Launch with `make dashboard` or `streamlit run src/dashboard/app.py`.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

import db_dtypes  # noqa: F401  (registers BQ dbdate with pandas)

# ── Setup ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "processed"

st.set_page_config(
    page_title="SO new-contributor retention",
    page_icon=":bar_chart:",
    layout="wide",
)


# ── Cached loaders ────────────────────────────────────────────────────────────
@st.cache_data
def load_master():
    df = pd.read_parquet(DATA_DIR / "master.parquet")
    df["cohort_month_dt"] = pd.to_datetime(df["cohort_month"])
    return df


@st.cache_data
def load_artifact(name):
    return pd.read_parquet(DATA_DIR / name)


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
    "Built as part of a portfolio of causal-inference projects."
)


# ── Pages ─────────────────────────────────────────────────────────────────────
def page_overview():
    st.title("Stack Overflow new-contributor retention")
    st.markdown(
        "Causal-inference project on 1.77M new Stack Overflow contributors who posted "
        "their first question between January 2018 and September 2022. The question: "
        "**does getting an answer to your first question keep you on the platform?**"
    )

    master = load_master()
    obs = master[master["d180_observable"] == 1]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Question-first cohort", f"{len(master):,}")
    c2.metric("Active at D30", f"{master['active_d30'].mean()*100:.1f}%")
    c3.metric("Active at D180 (observable)", f"{obs['active_d180'].mean()*100:.1f}%")
    c4.metric("Got answer within 24h", f"{master['got_answer_within_24h'].mean()*100:.1f}%")

    st.subheader("Cohort size by month")
    cohort_size = master.groupby("cohort_month_dt").size().reset_index(name="users")
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(cohort_size["cohort_month_dt"], cohort_size["users"], marker="o", color="steelblue")
    ax.set_ylabel("users")
    ax.set_title("Monthly new-contributor count, 2018-01 to 2022-09")
    ax.grid(alpha=0.3)
    st.pyplot(fig)

    st.subheader("Headline finding")
    st.info(
        "Getting an answer within 24 hours of your first question is associated with "
        "**+7.7 pp higher D30 retention** (controlled OLS, 95% CI [+7.56, +7.82]). "
        "The effect shrinks to +1.5 pp at six months. The estimate is robust to "
        "swapping covariates, adding tighter time fixed effects, and stratifying "
        "by propensity score. An instrumental-variable analysis using posting-hour "
        "as the IV failed exclusion-restriction sanity checks and is reported but "
        "not used as the headline."
    )


def page_funnel():
    st.title("Funnel and retention")
    master = load_master()
    obs = master[master["d180_observable"] == 1]

    st.subheader("Engagement funnel, first question")
    funnel = pd.DataFrame({
        "stage": ["Posted first question", "Got any answer ever",
                  "Got answer within 24h", "Got answer within 1h"],
        "rate": [
            1.0,
            master["got_any_answer"].mean(),
            master["got_answer_within_24h"].mean(),
            master["got_answer_within_1h"].mean(),
        ],
    })
    funnel["pct"] = (funnel["rate"] * 100).round(1)
    st.dataframe(funnel[["stage", "pct"]].rename(columns={"pct": "% of cohort"}), use_container_width=True)

    st.subheader("Retention outcomes")
    ret = pd.DataFrame({
        "outcome": ["Active at D30", "Active at D180 (observable)"],
        "pct": [master["active_d30"].mean() * 100, obs["active_d180"].mean() * 100],
    })
    st.dataframe(ret, use_container_width=True)

    st.subheader("Cohort-month trend, retention and engagement rates")
    agg = master.groupby("cohort_month_dt").agg(
        d30=("active_d30", "mean"),
        got_24h=("got_answer_within_24h", "mean"),
    ).reset_index()
    obs_agg = obs.groupby("cohort_month_dt").agg(d180=("active_d180", "mean")).reset_index()
    agg = agg.merge(obs_agg, on="cohort_month_dt", how="left")
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(agg["cohort_month_dt"], agg["d30"] * 100, marker="o", label="D30 retention", color="steelblue")
    ax.plot(agg["cohort_month_dt"], agg["got_24h"] * 100, marker="o", label="Got answer within 24h", color="orange")
    ax.plot(agg["cohort_month_dt"], agg["d180"] * 100, marker="o", label="D180 retention", color="green")
    ax.set_ylabel("rate (%)"); ax.legend(); ax.grid(alpha=0.3)
    st.pyplot(fig)


def page_causal():
    st.title("Causal estimates")
    st.markdown(
        "Four estimators applied to the same treatment, got-answer-within-24h, "
        "for the D30 and D180 outcomes. The naive lift is shown for reference."
    )

    te = load_artifact("treatment_effects.parquet")

    for outcome in ["D30", "D180"]:
        st.subheader(f"{outcome} outcome")
        sub = te[te["outcome"] == outcome].copy()
        sub = sub[["method", "estimate_pp", "se_pp", "ci_low_pp", "ci_high_pp", "n"]]
        st.dataframe(
            sub.style.format({
                "estimate_pp": "{:+.2f}", "se_pp": "{:.3f}",
                "ci_low_pp": "{:+.2f}", "ci_high_pp": "{:+.2f}",
                "n": "{:,}",
            }),
            use_container_width=True,
        )

        fig, ax = plt.subplots(figsize=(10, 4))
        y = np.arange(len(sub))
        colors = ["gray", "steelblue", "steelblue", "steelblue", "darkorange"]
        ax.barh(y, sub["estimate_pp"], color=colors, alpha=0.85)
        for i, row in sub.reset_index(drop=True).iterrows():
            if pd.notna(row["ci_low_pp"]):
                ax.plot([row["ci_low_pp"], row["ci_high_pp"]], [i, i], "k-", lw=2)
            ax.text(row["estimate_pp"] + 0.1, i, f"{row['estimate_pp']:+.2f}", va="center")
        ax.set_yticks(y); ax.set_yticklabels(sub["method"])
        ax.axvline(0, color="black", lw=0.5)
        ax.set_xlabel("Effect (percentage points)")
        ax.invert_yaxis()
        st.pyplot(fig)

    st.warning(
        "The 2SLS estimate is strongly negative. The first-stage F is above 1000, so the "
        "instrument is not statistically weak, but the negative point estimate suggests "
        "the exclusion restriction is violated. Posting hour correlates with unobserved "
        "user characteristics (timezone, hobbyist vs professional, urgency) that directly "
        "affect retention. Treat the IV result as evidence of unobserved confounding, not "
        "as the causal estimate."
    )


def page_robustness():
    st.title("Robustness")
    st.markdown(
        "Three checks on the headline +7.7 pp D30 estimate. Treatment-definition swaps, "
        "specification variations, and cohort-year subsamples."
    )

    rob = load_artifact("robustness.parquet")

    for kind, title in [
        ("treatment", "Treatment definition (D30 outcome)"),
        ("specification", "Specification (got-answer-within-24h, D30)"),
        ("subsample", "Cohort year (got-answer-within-24h, D30)"),
    ]:
        st.subheader(title)
        sub = rob[rob["kind"] == kind].copy()
        st.dataframe(
            sub[["label", "controlled_pp", "se_pp", "ci_low", "ci_high"]]
            .style.format({
                "controlled_pp": "{:+.2f}", "se_pp": "{:.3f}",
                "ci_low": "{:+.2f}", "ci_high": "{:+.2f}",
            }),
            use_container_width=True,
        )

        fig, ax = plt.subplots(figsize=(10, max(3, len(sub) * 0.4)))
        y = np.arange(len(sub))
        ax.barh(y, sub["controlled_pp"], color="steelblue", alpha=0.85)
        for i, row in sub.reset_index(drop=True).iterrows():
            ax.plot([row["ci_low"], row["ci_high"]], [i, i], "k-", lw=2)
            ax.text(row["controlled_pp"] + 0.1, i, f"{row['controlled_pp']:+.2f}", va="center")
        ax.set_yticks(y); ax.set_yticklabels(sub["label"])
        ax.axvline(0, color="black", lw=0.5)
        ax.set_xlabel("D30 effect (percentage points)")
        ax.invert_yaxis()
        st.pyplot(fig)


def page_het():
    st.title("Heterogeneity")
    st.markdown(
        "Where does the +7.7 pp average treatment effect concentrate? Four cuts. "
        "By body length quartile, by code-block presence, by primary tag, by cohort year."
    )

    het = load_artifact("heterogeneity.parquet")

    for kind, title in [
        ("body_quartile", "By body-length quartile"),
        ("code_block", "By code-block presence"),
        ("tag", "By primary tag"),
        ("year", "By cohort year"),
    ]:
        st.subheader(title)
        sub = het[het["kind"] == kind].copy().sort_values("estimate_pp", ascending=False)
        st.dataframe(
            sub[["label", "n", "share", "estimate_pp", "ci_low", "ci_high"]]
            .style.format({
                "n": "{:,}", "share": "{:.2%}",
                "estimate_pp": "{:+.2f}", "ci_low": "{:+.2f}", "ci_high": "{:+.2f}",
            }),
            use_container_width=True,
        )

        fig, ax = plt.subplots(figsize=(10, max(3, len(sub) * 0.4)))
        y = np.arange(len(sub))
        ax.barh(y, sub["estimate_pp"], color="steelblue", alpha=0.85)
        for i, row in sub.reset_index(drop=True).iterrows():
            ax.plot([row["ci_low"], row["ci_high"]], [i, i], "k-", lw=2)
            ax.text(row["estimate_pp"] + 0.1, i, f"{row['estimate_pp']:+.2f}", va="center")
        ax.set_yticks(y); ax.set_yticklabels(sub["label"])
        ax.axvline(0, color="black", lw=0.5)
        ax.set_xlabel("D30 effect (percentage points)")
        ax.invert_yaxis()
        st.pyplot(fig)

    st.info(
        "Two findings worth noting. First, the answer-retention link nearly doubled "
        "between 2018 (+5.96 pp) and 2022 (+11.03 pp), consistent with alternative "
        "help sources making SO answers more differentiating over time. Second, the "
        "treatment effect varies sharply by language: R and Android users benefit "
        "most (+10 pp), C++ users least (+3.7 pp). Likely reflects differences in "
        "alternative help sources and community size by language."
    )


def page_predictive():
    st.title("Predictive model")
    st.markdown(
        "Two notebooks. Notebook 05 trains a logistic-regression baseline and a "
        "gradient-boosted classifier on 14 first-post features. Notebook 06 adds "
        "engineered features (top-30 tag one-hots, pairwise interactions, polynomial "
        "terms), tunes the gradient booster, and calibrates probabilities. The "
        "comparison surfaces a real ceiling, not a model-engineering shortfall."
    )

    st.subheader("Notebook 05, v1 baseline")
    metrics = load_artifact("predictive_metrics.parquet")
    st.dataframe(
        metrics.style.format({"roc_auc": "{:.4f}", "pr_auc": "{:.4f}", "brier": "{:.4f}"}),
        use_container_width=True,
    )

    st.subheader("Notebook 06, v2-v4 improvements")
    try:
        v2_metrics = load_artifact("predictive_v2_metrics.parquet")
        st.dataframe(
            v2_metrics.style.format({"roc_auc": "{:.4f}", "pr_auc": "{:.4f}", "brier": "{:.4f}"}),
            use_container_width=True,
        )
    except FileNotFoundError:
        st.info("Run notebook 06 to populate v2-v4 metrics.")

    st.subheader("Feature importance, v3 tuned GBM (mean |SHAP|)")
    try:
        shap_imp = load_artifact("predictive_v2_shap.parquet").head(20)
        fig, ax = plt.subplots(figsize=(10, 8))
        y = np.arange(len(shap_imp))
        ax.barh(y, shap_imp["mean_abs_shap"], color="steelblue", alpha=0.85)
        ax.set_yticks(y); ax.set_yticklabels(shap_imp["feature"])
        ax.set_xlabel("Mean |SHAP value|")
        ax.invert_yaxis()
        st.pyplot(fig)
    except FileNotFoundError:
        shap_imp = load_artifact("predictive_shap.parquet")
        fig, ax = plt.subplots(figsize=(10, 6))
        y = np.arange(len(shap_imp))
        ax.barh(y, shap_imp["mean_abs_shap"], color="steelblue", alpha=0.85)
        ax.set_yticks(y); ax.set_yticklabels(shap_imp["feature"])
        ax.set_xlabel("Mean |SHAP value|")
        ax.invert_yaxis()
        st.pyplot(fig)

    st.subheader("Why the AUC is what it is")
    st.markdown(
        "Three structural reasons.\n\n"
        "1. The base rate is 24%. Models on imbalanced binary outcomes with "
        "weak features cap at moderate AUC.\n\n"
        "2. The biggest drivers of whether a new contributor returns are not "
        "observable from first-post data. Prior programming experience, motivation, "
        "alternative help sources, whether the user got their answer elsewhere. The "
        "14 first-post features are weak proxies for all of that.\n\n"
        "3. Notebook 06 confirms the structural ceiling. Adding tag one-hots, "
        "interactions, polynomial terms, hyperparameter tuning, and calibration "
        "moves AUC by less than half a percentage point. The combined v2/v3 gain "
        "over v1 is +0.4 pp. The information just isn't there.\n\n"
        "What would push AUC up meaningfully: TF-IDF or embeddings on body/title "
        "text (would require re-running sql-04 with the body column kept, +$0.14 "
        "in BQ scan). Out of scope here."
    )


def page_about():
    st.title("About this project")
    st.markdown(
        """
The data lives in BigQuery's public Stack Overflow dataset, snapshot through
2022-09-25. The analysis flow is five SQL files in sequence, followed by five
notebooks. SQL extracts cohort definitions, retention outcomes, engagement
funnel, first-post features, and an instrumental-variable lookup. Notebooks
do EDA, causal estimation with four side-by-side methods, robustness checks,
heterogeneity by user segment, and predictive modeling.

Tech stack: Python 3.12, pandas, numpy, statsmodels for OLS and IPW,
linearmodels for 2SLS, sklearn for the predictive models, SHAP for feature
attribution, streamlit for this dashboard, BigQuery for the data extraction.

Cost summary: roughly 44 GB of BigQuery scan across the five SQL files,
about $0.22 at the $5 per TB rate, well under the 1 TB per month free tier.

Source code on GitHub at github.com/bass990/stackoverflow-retention-causal.
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
