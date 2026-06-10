"""Smoke tests — verify the package layout without hitting BigQuery.

These tests run in CI without any GCP credentials. They check:
  - The sql/ directory exists and is reachable from the package.
  - The first SQL file (01_cohort_definition.sql) is present and has expected content.
  - get_client raises a clear error when GCP_PROJECT is unset.

Live BigQuery tests are dev-only — they require ADC and would consume billable
bytes. Run them locally via `make sql-01`, not in CI.
"""
from __future__ import annotations

import pytest

from src.data import bq_client


def test_sql_dir_exists():
    """sql/ should exist at project root, one level above src/."""
    assert bq_client.SQL_DIR.is_dir(), f"Expected sql/ at {bq_client.SQL_DIR}"


def test_first_sql_file_exists_and_has_content():
    """01_cohort_definition.sql is the Day-1 ship."""
    cohort_sql = bq_client.SQL_DIR / "01_cohort_definition.sql"
    assert cohort_sql.exists(), "01_cohort_definition.sql is missing — scaffold incomplete."

    content = cohort_sql.read_text(encoding="utf-8").lower()
    # Spot-check key concepts that should appear in the cohort SQL
    assert "first_post" in content, "Cohort SQL should reference first_post concept"
    assert "row_number" in content, "Cohort SQL should rank posts per user"
    assert "study_start_date" in content, "Cohort SQL should declare study window"


def test_get_client_requires_project(monkeypatch):
    """Without GCP_PROJECT set, get_client should fail with a clear error."""
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with pytest.raises(ValueError, match="GCP_PROJECT"):
        bq_client.get_client()
