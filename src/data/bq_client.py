"""BigQuery client wrapper for P1.

Provides three entry points:

  - get_client(project=None) -> bigquery.Client
        Returns an authenticated client. Reads GCP_PROJECT from env if no project
        is passed explicitly.

  - run_sql_file(name, project=None, params=None, dry_run=False)
        Reads a SQL file from sql/, optionally substitutes {placeholder} tokens
        from `params`, and executes against BigQuery. Returns a pandas DataFrame
        when dry_run is False, or a QueryJob (containing the cost estimate) when
        dry_run is True.

  - estimate_bytes(name, project=None, **params)
        Returns total bytes that WOULD be billed for a SQL file, without
        executing the query. The estimate itself is free.

Auth:
    Uses Application Default Credentials (ADC). Set up locally with
    `gcloud auth application-default login`. For HF Spaces deploy, store a
    service-account JSON as a Space secret and point GOOGLE_APPLICATION_CREDENTIALS
    at it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
from google.cloud import bigquery

# sql/ lives at the project root, one level above src/.
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def get_client(project: str | None = None) -> bigquery.Client:
    """Return a BigQuery client authenticated via Application Default Credentials.

    Args:
        project: GCP project ID. Defaults to the GCP_PROJECT environment variable.

    Raises:
        ValueError: if neither `project` nor GCP_PROJECT is set.
    """
    project = project or os.getenv("GCP_PROJECT")
    if not project:
        raise ValueError(
            "GCP_PROJECT environment variable not set and no `project` argument "
            "passed. Set GCP_PROJECT to your BigQuery billing project ID — e.g. "
            "`export GCP_PROJECT=p1-stackoverflow-retention-123456`."
        )
    return bigquery.Client(project=project)


def _read_sql(name: str, params: dict[str, Any] | None = None) -> str:
    """Read a SQL file from sql/ and apply Python str.format substitution.

    The SQL files use DECLARE statements for query-time parameters by default,
    so str.format substitution is only needed when callers want to programmatically
    override a parameter without editing the SQL file.
    """
    sql_path = SQL_DIR / name
    if not sql_path.exists():
        raise FileNotFoundError(
            f"SQL file not found: {sql_path}\n"
            f"Expected SQL files in: {SQL_DIR}"
        )
    sql = sql_path.read_text(encoding="utf-8")
    if params:
        sql = sql.format(**params)
    return sql


def run_sql_file(
    name: str,
    *,
    project: str | None = None,
    params: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> pd.DataFrame | bigquery.QueryJob:
    """Run a SQL file from sql/ and return results.

    Args:
        name: SQL filename in sql/ (e.g. '01_cohort_definition.sql')
        project: GCP project ID (defaults to GCP_PROJECT env var)
        params: dict of {placeholder: value} substitutions to apply to the SQL
        dry_run: if True, returns the QueryJob without executing.
                 Read `.total_bytes_processed` for the bytes-to-be-billed estimate.

    Returns:
        DataFrame of query results when dry_run is False.
        QueryJob (cost-estimation only) when dry_run is True.
    """
    sql = _read_sql(name, params)
    client = get_client(project)

    if dry_run:
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        return client.query(sql, job_config=job_config)

    return client.query(sql).to_dataframe(create_bqstorage_client=True)


def estimate_bytes(name: str, project: str | None = None, **params: Any) -> int:
    """Estimate bytes-billed for a SQL file via a free dry run.

    Args:
        name: SQL filename in sql/
        project: GCP project ID (defaults to GCP_PROJECT env var)
        **params: passed through to run_sql_file as the params dict

    Returns:
        Total bytes that would be processed by the query.

    Example:
        >>> b = estimate_bytes('01_cohort_definition.sql')
        >>> print(f"{b / 1e9:.2f} GB ({b * 5 / 1e12:.4f} USD at $5/TB)")
    """
    job = run_sql_file(
        name,
        project=project,
        params=params or None,
        dry_run=True,
    )
    return job.total_bytes_processed
