"""Every dashboard page renders from the committed summaries with no exceptions."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

# Absolute path: AppTest resolves relative paths against the test file in newer Streamlit
# releases and against the working directory in older ones.
APP = str(Path(__file__).resolve().parents[1] / "src" / "dashboard" / "app.py")

PAGES = [
    "Overview", "Funnel and retention", "Causal estimates", "Robustness",
    "Heterogeneity", "Predictive model", "About the project",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.title[0].value


def test_overview_quotes_the_headline_numbers():
    at = AppTest.from_file(APP, default_timeout=120).run()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Question-first cohort"] == "1,772,119"
    assert metrics["Active at D30"] == "24.0%"
    assert "+7.7 pp" in at.info[0].value
