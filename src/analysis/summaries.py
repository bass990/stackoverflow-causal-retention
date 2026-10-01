"""Small, committable summaries of the 1.77M-row master table for the dashboard.

`data/processed/` holds the raw BigQuery extracts and the master table (tens of MB,
gitignored). `data/summary/` holds what the dashboard actually needs (~50 KB,
committed), so `make dashboard` and the Docker image work on a fresh clone without a
BigQuery project or a notebook run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
SUMMARY = ROOT / "data" / "summary"

# Notebook outputs that are already small enough to commit as they are.
SMALL_ARTIFACTS = [
    "treatment_effects.parquet",   # notebook 02
    "robustness.parquet",          # notebook 03
    "heterogeneity.parquet",       # notebook 04
    "predictive_metrics.parquet",  # notebook 05
    "predictive_shap.parquet",     # notebook 05
    "predictive_logit_coefs.parquet",  # notebook 05
    "treatment.parquet",           # sql-05, hour-of-day instrument table
]


def cohort_monthly(master: pd.DataFrame) -> pd.DataFrame:
    """One row per cohort month: size, D30 rate, answer-within-24h rate, D180 rate."""
    m = master.copy()
    m["cohort_month"] = pd.to_datetime(m["cohort_month"]).dt.strftime("%Y-%m-%d")
    obs = m[m["d180_observable"] == 1]
    agg = m.groupby("cohort_month").agg(
        users=("user_id", "size"),
        d30_rate=("active_d30", "mean"),
        got_24h_rate=("got_answer_within_24h", "mean"),
    )
    obs_agg = obs.groupby("cohort_month").agg(
        d180_rate=("active_d180", "mean"),
        users_observable=("user_id", "size"),
    )
    out = agg.join(obs_agg, how="left").reset_index()
    out["d30_rate"] = out["d30_rate"].astype(float)
    out["got_24h_rate"] = out["got_24h_rate"].astype(float)
    out["d180_rate"] = out["d180_rate"].astype(float)
    return out


def headline(master: pd.DataFrame) -> dict:
    """The cohort-level numbers the README and the dashboard overview quote."""
    obs = master[master["d180_observable"] == 1]
    return {
        "n_question_first": int(len(master)),
        "n_d180_observable": int(len(obs)),
        "share_d180_observable": float(len(obs) / len(master)),
        "active_d30_rate": float(master["active_d30"].mean()),
        "active_d180_rate_observable": float(obs["active_d180"].mean()),
        "got_any_answer_rate": float(master["got_any_answer"].mean()),
        "got_answer_within_24h_rate": float(master["got_answer_within_24h"].mean()),
        "got_answer_within_1h_rate": float(master["got_answer_within_1h"].mean()),
        "has_code_block_rate": float(master["has_code_block"].mean()),
        "has_link_rate": float(master["has_link"].mean()),
        "has_image_rate": float(master["has_image"].mean()),
        "first_cohort_month": str(pd.to_datetime(master["cohort_month"]).min().date()),
        "last_cohort_month": str(pd.to_datetime(master["cohort_month"]).max().date()),
        "data_snapshot_date": str(pd.to_datetime(master["data_snapshot_date"]).max().date()),
    }


def build(processed: Path = PROCESSED, summary: Path = SUMMARY) -> list[Path]:
    """Write data/summary/ from data/processed/. Returns the files written."""
    import db_dtypes  # noqa: F401  registers BigQuery's dbdate dtype with pandas

    summary.mkdir(parents=True, exist_ok=True)
    written = []
    master = pd.read_parquet(processed / "master.parquet")
    p = summary / "cohort_monthly.parquet"
    cohort_monthly(master).to_parquet(p, index=False)
    written.append(p)
    p = summary / "headline.json"
    p.write_text(json.dumps(headline(master), indent=2) + "\n", encoding="utf-8")
    written.append(p)
    for name in SMALL_ARTIFACTS:
        src = processed / name
        if not src.exists():
            raise FileNotFoundError(f"{src} missing: run the notebook that produces it first")
        df = pd.read_parquet(src)
        # Re-write through pandas so the committed files carry no BigQuery-specific dtypes.
        df.to_parquet(summary / name, index=False)
        written.append(summary / name)
    return written


if __name__ == "__main__":
    for path in build():
        print(f"{path.relative_to(ROOT).as_posix()}  {path.stat().st_size / 1024:.1f} KB")
