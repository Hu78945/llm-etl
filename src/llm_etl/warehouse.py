"""DuckDB warehouse: DDL for bronze/silver and the incremental bronze load."""

import hashlib
import json
from pathlib import Path

import duckdb

from llm_etl import config

DDL = """
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS bronze.raw_postings (
    posting_id   VARCHAR PRIMARY KEY,
    source       VARCHAR NOT NULL,
    company      VARCHAR NOT NULL,
    posted_at    DATE NOT NULL,
    raw_text     VARCHAR NOT NULL,
    content_hash VARCHAR NOT NULL,
    ingested_at  TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Incremental state: one row per (text, extractor version). Re-runs never re-call the LLM
-- for text they have already seen. Also the per-record token/cost log.
CREATE TABLE IF NOT EXISTS silver.extraction_cache (
    content_hash  VARCHAR NOT NULL,
    extractor     VARCHAR NOT NULL,
    result        JSON,
    error         VARCHAR,
    attempts      INTEGER NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      DOUBLE NOT NULL DEFAULT 0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (content_hash, extractor)
);

CREATE TABLE IF NOT EXISTS silver.posting_embeddings (
    content_hash VARCHAR PRIMARY KEY,
    embedding    FLOAT[] NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.duplicates (
    posting_id   VARCHAR PRIMARY KEY,
    duplicate_of VARCHAR NOT NULL,
    similarity   DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.extracted_postings (
    posting_id      VARCHAR PRIMARY KEY,
    content_hash    VARCHAR NOT NULL,
    extractor       VARCHAR NOT NULL,
    title           VARCHAR NOT NULL,
    seniority       VARCHAR NOT NULL,
    skills          VARCHAR[] NOT NULL,
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_currency VARCHAR,
    remote_policy   VARCHAR NOT NULL,
    location        VARCHAR
);

CREATE TABLE IF NOT EXISTS silver.quarantine (
    posting_id   VARCHAR PRIMARY KEY,
    content_hash VARCHAR NOT NULL,
    extractor    VARCHAR NOT NULL,
    error        VARCHAR NOT NULL
);
"""


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    path = Path(path or config.DUCKDB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(DDL)
    return con


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def ingest(con: duckdb.DuckDBPyConnection, path: Path = config.RAW_POSTINGS) -> dict[str, int]:
    """Upsert the feed into bronze. Only new or changed postings are written."""
    rows = []
    with path.open() as f:
        for line in f:
            r = json.loads(line)
            rows.append((r["posting_id"], r["source"], r["company"], r["posted_at"], r["text"],
                         content_hash(r["text"])))
    existing = dict(con.execute("SELECT posting_id, content_hash FROM bronze.raw_postings").fetchall())
    changed = [r for r in rows if existing.get(r[0]) != r[5]]
    if changed:
        con.executemany(
            "INSERT OR REPLACE INTO bronze.raw_postings "
            "(posting_id, source, company, posted_at, raw_text, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
            changed,
        )
    return {"read": len(rows), "written": len(changed)}
