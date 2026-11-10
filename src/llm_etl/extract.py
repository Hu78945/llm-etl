"""Bronze -> silver: incremental, cached, batched extraction plus quarantine."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from itertools import batched

import anthropic
import duckdb
from pydantic import ValidationError

from llm_etl import config, extract_llm
from llm_etl.extract_rules import extract_fields
from llm_etl.schema import JobPosting, format_errors

log = logging.getLogger(__name__)
RULES_EXTRACTOR = "rules:v1"


def extract_with_rules(text: str) -> dict:
    started = time.perf_counter()
    try:
        result, error = JobPosting.model_validate(extract_fields(text)).model_dump(), None
    except ValidationError as e:
        result, error = None, format_errors(e)
    return {"result": result, "error": error, "attempts": 1, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "latency_ms": int((time.perf_counter() - started) * 1000)}


def _pending(con: duckdb.DuckDBPyConnection, extractor: str) -> list[tuple[str, str]]:
    """Distinct texts not yet in the cache for this extractor. Duplicates are skipped:
    deduping *before* extraction means we never pay the LLM for a repost."""
    return con.execute("""
        SELECT DISTINCT b.content_hash, b.raw_text
        FROM bronze.raw_postings b
        WHERE b.posting_id NOT IN (SELECT posting_id FROM silver.duplicates)
          AND NOT EXISTS (SELECT 1 FROM silver.extraction_cache c
                          WHERE c.content_hash = b.content_hash AND c.extractor = ?)
        ORDER BY b.content_hash
    """, [extractor]).fetchall()


def _save(con: duckdb.DuckDBPyConnection, extractor: str, rows: list[tuple[str, dict]]) -> None:
    con.executemany(
        "INSERT INTO silver.extraction_cache (content_hash, extractor, result, error, attempts, "
        "input_tokens, output_tokens, cost_usd, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(h, extractor, json.dumps(o["result"]) if o["result"] else None, o["error"], o["attempts"],
          o["input_tokens"], o["output_tokens"], o["cost_usd"], o["latency_ms"]) for h, o in rows],
    )


def materialize_silver(con: duckdb.DuckDBPyConnection, extractor: str) -> None:
    """Rebuild silver tables from the cache. Cheap and idempotent: the cache is the state."""
    con.execute("BEGIN")
    con.execute("DELETE FROM silver.extracted_postings")
    con.execute("DELETE FROM silver.quarantine")
    base = """
        FROM bronze.raw_postings b
        JOIN silver.extraction_cache c ON c.content_hash = b.content_hash AND c.extractor = $1
        WHERE b.posting_id NOT IN (SELECT posting_id FROM silver.duplicates)
    """
    con.execute(f"""
        INSERT INTO silver.extracted_postings
        SELECT b.posting_id, b.content_hash, c.extractor,
               c.result->>'title', c.result->>'seniority',
               from_json(c.result->'skills', '["VARCHAR"]'),
               (c.result->>'salary_min')::INTEGER, (c.result->>'salary_max')::INTEGER,
               c.result->>'salary_currency', c.result->>'remote_policy', c.result->>'location'
        {base} AND c.error IS NULL
    """, [extractor])
    con.execute(f"INSERT INTO silver.quarantine SELECT b.posting_id, b.content_hash, c.extractor, c.error "
                f"{base} AND c.error IS NOT NULL", [extractor])
    con.execute("COMMIT")


def run_extraction(con: duckdb.DuckDBPyConnection, use_llm: bool | None = None, client=None) -> dict:
    use_llm = config.use_llm() if use_llm is None else use_llm
    if use_llm:
        extractor = extract_llm.extractor_name()
        fn = partial(extract_llm.extract, client or extract_llm.make_client())
    else:
        extractor, fn = RULES_EXTRACTOR, extract_with_rules

    pending = _pending(con, extractor)
    log.info("extractor=%s pending=%d", extractor, len(pending))
    tokens_in = tokens_out = 0
    cost = 0.0
    for batch in batched(pending, config.LLM_BATCH_SIZE):
        done, failure = [], None
        with ThreadPoolExecutor(max_workers=config.LLM_CONCURRENCY if use_llm else 1) as pool:
            futures = {pool.submit(fn, text): h for h, text in batch}
            for fut in as_completed(futures):
                try:
                    out = fut.result()
                except anthropic.APIError as e:  # rate limit / outage after SDK retries: not cached, retried next run
                    failure = failure or e
                    continue
                done.append((futures[fut], out))
                log.debug("hash=%s attempts=%d in=%d out=%d cost=$%.6f error=%s", futures[fut][:12],
                          out["attempts"], out["input_tokens"], out["output_tokens"], out["cost_usd"],
                          out["error"])
        _save(con, extractor, done)  # persist per batch: a crash loses at most one batch
        tokens_in += sum(o["input_tokens"] for _, o in done)
        tokens_out += sum(o["output_tokens"] for _, o in done)
        cost += sum(o["cost_usd"] for _, o in done)
        if failure:
            raise failure

    materialize_silver(con, extractor)
    silver, quarantined = (con.execute(f"SELECT count(*) FROM silver.{t}").fetchone()[0]
                           for t in ("extracted_postings", "quarantine"))
    return {"extractor": extractor, "extracted_now": len(pending), "silver_rows": silver,
            "quarantined": quarantined, "input_tokens": tokens_in, "output_tokens": tokens_out,
            "cost_usd": round(cost, 6)}
