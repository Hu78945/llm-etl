"""Integration: full feed through bronze -> silver on a temp DuckDB, then dbt build."""

import json

from llm_etl import config, evaluate, extract, pipeline, warehouse


def test_bronze_ingest_is_idempotent_and_detects_changes(loaded, tmp_path):
    con, *_ = loaded
    assert warehouse.ingest(con) == {"read": 702, "written": 0}

    rows = config.RAW_POSTINGS.read_text().splitlines()
    first = json.loads(rows[0])
    first["text"] += "\nUpdated: now offering a 4-day week."
    feed = tmp_path / "feed.jsonl"
    feed.write_text("\n".join([json.dumps(first), *rows[1:]]) + "\n")
    assert warehouse.ingest(con, feed) == {"read": 702, "written": 1}
    assert warehouse.ingest(con) == {"read": 702, "written": 1}  # restore the original


def test_extraction_is_incremental(loaded):
    con, first_run, _ = loaded
    assert first_run["extracted_now"] > 600
    # Re-running does no extraction work: everything is served from the content-hash cache ...
    assert extract.run_extraction(con, use_llm=False)["extracted_now"] == 0
    # ... and only the posting whose text changed is re-extracted.
    con.execute("UPDATE bronze.raw_postings SET raw_text = raw_text || ' ', content_hash = 'changed' "
                "WHERE posting_id = (SELECT min(posting_id) FROM silver.extracted_postings)")
    assert extract.run_extraction(con, use_llm=False)["extracted_now"] == 1


def test_every_bronze_row_routed_exactly_once(loaded):
    con, *_ = loaded
    counts = con.execute("""
        SELECT (SELECT count(*) FROM bronze.raw_postings),
               (SELECT count(*) FROM silver.extracted_postings)
             + (SELECT count(*) FROM silver.quarantine)
             + (SELECT count(*) FROM silver.duplicates)
    """).fetchone()
    assert counts[0] == counts[1]


def test_quality_against_ground_truth(loaded):
    """Regression guards on the measured numbers reported in the README."""
    con, *_ = loaded
    d = evaluate.dedup_metrics(con)
    assert d["recall"] == 1.0 and d["precision"] == 1.0
    q = evaluate.quarantine_metrics(con)
    assert q["invalid_caught"] == q["ground_truth_invalid"]
    standard = evaluate.extraction_metrics(con, extract.RULES_EXTRACTOR)["standard"]
    assert min(standard["field_accuracy"].values()) == 1.0


def test_dbt_build_passes(loaded, monkeypatch):
    con, _, path = loaded
    con.execute("CHECKPOINT")
    con.close()  # dbt opens the file itself
    monkeypatch.setenv("LLM_ETL_DUCKDB", str(path))
    assert pipeline.step_dbt("build")["success"]
    con = warehouse.connect(path)
    assert con.execute("SELECT count(*) FROM gold.mart_salary_bands").fetchone()[0] == 5
