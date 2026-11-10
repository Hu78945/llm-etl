"""Paths and env-driven settings. Everything is overridable via environment variables."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = ROOT / "dbt"
TAXONOMY_CSV = DBT_DIR / "seeds" / "skill_taxonomy.csv"
RAW_POSTINGS = ROOT / "data" / "raw" / "postings.jsonl"
GROUND_TRUTH = ROOT / "data" / "raw" / "ground_truth.jsonl"
GOLDEN_LABELS = ROOT / "data" / "golden" / "golden_labels.jsonl"

DUCKDB_PATH = Path(os.environ.get("LLM_ETL_DUCKDB", ROOT / "warehouse" / "llm_etl.duckdb"))

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
# USD per million tokens (input, output). Defaults are Claude Haiku 5.5 list prices.
PRICE_IN_PER_MTOK = float(os.environ.get("LLM_PRICE_IN_PER_MTOK", "0.10"))
PRICE_OUT_PER_MTOK = float(os.environ.get("LLM_PRICE_OUT_PER_MTOK", "0.50"))
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "8"))
LLM_BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", "50"))

DEDUP_THRESHOLD = float(os.environ.get("DEDUP_THRESHOLD", "0.86"))


def use_llm() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
