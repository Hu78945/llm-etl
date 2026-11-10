"""Pipeline steps (shared by the CLI and the Airflow DAG) and the `llm-etl` CLI."""

import argparse
import json
import logging
import os
from contextlib import closing

from llm_etl import config, dedup, evaluate, extract, generate, warehouse

METRICS_PATH = config.ROOT / "reports" / "metrics.json"


def step_generate() -> dict:
    return generate.generate()


def step_ingest() -> dict:
    with closing(warehouse.connect()) as con:
        return warehouse.ingest(con)


def step_dedup() -> dict:
    with closing(warehouse.connect()) as con:
        return dedup.dedup(con)


def step_extract() -> dict:
    with closing(warehouse.connect()) as con:
        return extract.run_extraction(con)


def step_dbt(command: str = "build") -> dict:
    from dbt.cli.main import dbtRunner  # heavy import, only when needed

    os.environ.setdefault("LLM_ETL_DUCKDB", str(config.DUCKDB_PATH))  # profiles.yml reads it

    args = [command, "--project-dir", str(config.DBT_DIR), "--profiles-dir", str(config.DBT_DIR)]
    result = dbtRunner().invoke(args)
    if not result.success:
        raise RuntimeError(f"dbt {command} failed: {result.exception}")
    return {"dbt": command, "success": True}


def step_eval() -> dict:
    with closing(warehouse.connect()) as con:
        metrics = evaluate.run_eval(con)
    METRICS_PATH.parent.mkdir(exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


STEPS = {"generate": step_generate, "ingest": step_ingest, "dedup": step_dedup,
         "extract": step_extract, "dbt": step_dbt, "eval": step_eval}


def main() -> None:
    parser = argparse.ArgumentParser(prog="llm-etl", description=__doc__)
    parser.add_argument("step", choices=[*STEPS, "run"], help="'run' = ingest, dedup, extract, dbt, eval")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ["ingest", "dedup", "extract", "dbt", "eval"] if args.step == "run" else [args.step]:
        result = STEPS[name]()
        print(f"[{name}]", json.dumps(result, indent=2 if name == "eval" else None))


if __name__ == "__main__":
    main()
