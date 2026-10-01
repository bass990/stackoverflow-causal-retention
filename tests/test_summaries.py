"""Summary builders on a tiny fake master table, and the committed summary files."""
from __future__ import annotations

import json

import pandas as pd

from src.analysis import summaries


def _fake_master() -> pd.DataFrame:
    return pd.DataFrame({
        "user_id": range(8),
        "cohort_month": ["2018-01-01"] * 4 + ["2018-02-01"] * 4,
        "active_d30": [1, 0, 0, 0, 1, 1, 0, 0],
        "active_d180": [0, 0, 0, 0, 1, 0, 0, 0],
        "d180_observable": [1, 1, 1, 1, 1, 1, 0, 0],
        "got_any_answer": [1, 1, 0, 1, 1, 1, 1, 0],
        "got_answer_within_24h": [1, 0, 0, 1, 1, 1, 0, 0],
        "got_answer_within_1h": [1, 0, 0, 0, 1, 0, 0, 0],
        "has_code_block": [1, 1, 1, 0, 1, 1, 1, 1],
        "has_link": [0, 0, 1, 0, 0, 0, 0, 0],
        "has_image": [0] * 8,
        "data_snapshot_date": ["2022-09-25"] * 8,
    })


def test_cohort_monthly_rates():
    out = summaries.cohort_monthly(_fake_master())
    assert out["cohort_month"].tolist() == ["2018-01-01", "2018-02-01"]
    assert out["users"].tolist() == [4, 4]
    assert out["d30_rate"].tolist() == [0.25, 0.5]
    assert out["got_24h_rate"].tolist() == [0.5, 0.5]
    # February: only two of four users are D180-observable and one of those returned.
    assert out["users_observable"].tolist() == [4, 2]
    assert out["d180_rate"].tolist() == [0.0, 0.5]


def test_headline_numbers():
    h = summaries.headline(_fake_master())
    assert h["n_question_first"] == 8
    assert h["n_d180_observable"] == 6
    assert h["active_d30_rate"] == 3 / 8
    assert h["active_d180_rate_observable"] == 1 / 6
    assert h["got_any_answer_rate"] == 6 / 8
    assert h["first_cohort_month"] == "2018-01-01" and h["last_cohort_month"] == "2018-02-01"
    assert h["data_snapshot_date"] == "2022-09-25"
    json.dumps(h)  # must be JSON-serialisable


def test_committed_summary_matches_readme():
    """The committed summary files are what the dashboard shows; keep them honest."""
    te = pd.read_parquet(summaries.SUMMARY / "treatment_effects.parquet").set_index(["outcome", "method"])
    assert abs(te.loc[("D30", "Controlled OLS"), "estimate_pp"] - 7.69) < 0.01
    assert abs(te.loc[("D180", "Controlled OLS"), "estimate_pp"] - 1.48) < 0.01
    assert te.loc[("D30", "2SLS (hour IV)"), "estimate_pp"] < -15
    h = json.loads((summaries.SUMMARY / "headline.json").read_text(encoding="utf-8"))
    assert h["n_question_first"] == 1_772_119
    assert abs(h["active_d30_rate"] - 0.240) < 0.001
    months = pd.read_parquet(summaries.SUMMARY / "cohort_monthly.parquet")
    assert len(months) == 57
    assert months["users"].sum() == h["n_question_first"]
