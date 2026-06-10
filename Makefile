.PHONY: install test lint dashboard pdf clean help \
        estimate-sql-01 sql-01 \
        estimate-sql-02 sql-02 \
        estimate-sql-03 sql-03 \
        estimate-sql-04 sql-04 \
        estimate-sql-05 sql-05

help:
	@echo "Targets:"
	@echo "  install            -- pip install -e .[dev]"
	@echo "  test               -- pytest tests/ -v"
	@echo "  lint               -- ruff check src tests"
	@echo "  dashboard          -- streamlit run src/dashboard/app.py"
	@echo "  pdf                -- render docs/EXEC_ONE_PAGER.md -> .pdf (requires pandoc)"
	@echo "  clean              -- remove data/processed, .pytest_cache, .ruff_cache"
	@echo ""
	@echo "SQL execution (one target per file, with dry-run cost-estimate variants):"
	@echo "  estimate-sql-XX    -- print bytes that WILL be billed for sql/XX_*.sql"
	@echo "  sql-XX             -- run sql/XX_*.sql and save result to data/processed/"
	@echo ""
	@echo "Always run estimate-sql-XX before sql-XX. The estimate is free."

# ── Install ───────────────────────────────────────────────────────────────────
install:
	pip install --upgrade pip
	pip install -e ".[dev]"

# ── Test & lint ───────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --tb=short

lint:
	ruff check src tests

# ── Dashboard ─────────────────────────────────────────────────────────────────
dashboard:
	streamlit run src/dashboard/app.py

# ── Exec one-pager render (requires pandoc) ───────────────────────────────────
pdf:
	pandoc docs/EXEC_ONE_PAGER.md -o docs/EXEC_ONE_PAGER.pdf --pdf-engine=xelatex || \
		(echo "pandoc not installed or render failed. Install pandoc, or paste docs/EXEC_ONE_PAGER.md into Google Docs and export PDF manually."; exit 1)

# ── SQL execution ─────────────────────────────────────────────────────────────
# Each SQL file gets two targets: estimate (dry-run, free) and run.
# The run target writes to data/processed/<output>.parquet.

estimate-sql-01:
	@python -c "from src.data.bq_client import estimate_bytes; b = estimate_bytes('01_cohort_definition.sql'); print(f'Will process {b/1e9:.2f} GB ({b*5/1e12:.4f} USD at $$5/TB)')"

sql-01:
	@python -c "from src.data.bq_client import run_sql_file; df = run_sql_file('01_cohort_definition.sql'); df.to_parquet('data/processed/cohort.parquet', index=False); print(f'{len(df):,} rows -> data/processed/cohort.parquet')"

estimate-sql-02:
	@python -c "from src.data.bq_client import estimate_bytes; b = estimate_bytes('02_retention_30d_180d.sql'); print(f'Will process {b/1e9:.2f} GB ({b*5/1e12:.4f} USD at $$5/TB)')"

sql-02:
	@python -c "from src.data.bq_client import run_sql_file; df = run_sql_file('02_retention_30d_180d.sql'); df.to_parquet('data/processed/retention.parquet', index=False); print(f'{len(df):,} rows -> data/processed/retention.parquet')"

estimate-sql-03:
	@python -c "from src.data.bq_client import estimate_bytes; b = estimate_bytes('03_funnel_first_post_to_engagement.sql'); print(f'Will process {b/1e9:.2f} GB ({b*5/1e12:.4f} USD at $$5/TB)')"

sql-03:
	@python -c "from src.data.bq_client import run_sql_file; df = run_sql_file('03_funnel_first_post_to_engagement.sql'); df.to_parquet('data/processed/funnel.parquet', index=False); print(f'{len(df):,} rows -> data/processed/funnel.parquet')"

estimate-sql-04:
	@python -c "from src.data.bq_client import estimate_bytes; b = estimate_bytes('04_leading_indicator_features.sql'); print(f'Will process {b/1e9:.2f} GB ({b*5/1e12:.4f} USD at $$5/TB)')"

sql-04:
	@python -c "from src.data.bq_client import run_sql_file; df = run_sql_file('04_leading_indicator_features.sql'); df.to_parquet('data/processed/features.parquet', index=False); print(f'{len(df):,} rows -> data/processed/features.parquet')"

estimate-sql-05:
	@python -c "from src.data.bq_client import estimate_bytes; b = estimate_bytes('05_quasi_experiment_treatment_assignment.sql'); print(f'Will process {b/1e9:.2f} GB ({b*5/1e12:.4f} USD at $$5/TB)')"

sql-05:
	@python -c "from src.data.bq_client import run_sql_file; df = run_sql_file('05_quasi_experiment_treatment_assignment.sql'); df.to_parquet('data/processed/treatment.parquet', index=False); print(f'{len(df):,} rows -> data/processed/treatment.parquet')"

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	rm -rf .pytest_cache .ruff_cache
	rm -rf data/processed/*.parquet data/processed/*.csv data/processed/*.pkl
	find . -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
