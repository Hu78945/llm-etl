import os
import tempfile

import pytest

# Keep Airflow (imported by test_dag) from creating ~/airflow on the developer's machine.
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-home-"))
os.environ.pop("ANTHROPIC_API_KEY", None)  # tests are offline by design

from llm_etl import dedup, extract, warehouse


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    """A fresh warehouse with the full synthetic feed run through bronze -> silver (offline)."""
    path = tmp_path_factory.mktemp("wh") / "test.duckdb"
    con = warehouse.connect(path)
    warehouse.ingest(con)
    dedup.dedup(con)
    stats = extract.run_extraction(con, use_llm=False)
    yield con, stats, path
    con.close()
