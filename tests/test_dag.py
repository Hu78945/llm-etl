import itertools

import pytest

from llm_etl import config

pytest.importorskip("airflow")


def test_dag_imports_and_is_wired_in_order():
    from airflow.dag_processing.dagbag import DagBag

    bag = DagBag(dag_folder=str(config.ROOT / "dags"))
    assert bag.import_errors == {}
    dag = bag.dags["llm_etl"]
    order = ["ingest", "dedup", "extract", "dbt_build", "evaluate"]
    assert [t.task_id for t in sorted(dag.tasks, key=lambda t: order.index(t.task_id))] == order
    for upstream, downstream in itertools.pairwise(order):
        assert dag.get_task(upstream).downstream_task_ids == {downstream}
    assert dag.get_task("extract").retries == 4
