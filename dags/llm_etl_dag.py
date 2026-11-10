"""Daily llm-etl run: ingest -> dedup -> extract -> dbt build -> eval.

Tasks are thin wrappers over llm_etl.pipeline, so the CLI and Airflow run identical code.
`extract` is safe to retry: finished records are cached, transient API failures are not,
so a retry resumes where the last attempt stopped and never re-pays for work already done.
DuckDB is a single-writer file, hence max_active_tasks=1; on Snowflake that limit can go.
"""

from datetime import datetime, timedelta

from airflow.sdk import dag, task

from llm_etl import pipeline


@dag(
    schedule="@daily",
    start_date=datetime(2026, 6, 1),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["llm-etl"],
)
def llm_etl():
    @task
    def ingest() -> dict:
        return pipeline.step_ingest()

    @task
    def dedup() -> dict:
        return pipeline.step_dedup()

    @task(retries=4, retry_exponential_backoff=True)
    def extract() -> dict:
        return pipeline.step_extract()

    @task
    def dbt_build() -> dict:
        return pipeline.step_dbt("build")

    @task
    def evaluate() -> dict:
        return pipeline.step_eval()

    ingest() >> dedup() >> extract() >> dbt_build() >> evaluate()


llm_etl()
