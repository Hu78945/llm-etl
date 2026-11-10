UV ?= uv

.PHONY: install data run test lint clean

install:  ## create .venv with all dependency groups (dev + airflow)
	$(UV) sync --all-groups

data:  ## regenerate the synthetic feed + ground truth (deterministic, seed 42)
	$(UV) run llm-etl generate

run:  ## ingest -> dedup -> extract -> dbt build -> eval  (offline unless ANTHROPIC_API_KEY is set)
	$(UV) run llm-etl run

test: lint  ## unit + integration tests, including `dbt build` on a temp warehouse
	$(UV) run pytest

lint:
	$(UV) run ruff check .

clean:
	rm -rf warehouse dbt/target dbt/logs logs .pytest_cache .ruff_cache
