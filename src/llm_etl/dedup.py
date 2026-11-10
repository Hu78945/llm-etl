"""Local, deterministic embeddings + semantic near-duplicate detection.

Embeddings are hashed character n-gram vectors (the "hashing trick"): no model download,
no network, bit-for-bit reproducible. They capture surface similarity, which is exactly
what a job-board repost is. Swap `embed` for a sentence-transformer if you need
paraphrase-level matching.
"""

import re
import zlib

import duckdb
import numpy as np

from llm_etl import config

DIM = 512
NGRAMS = (3, 4, 5)


def embed(text: str, dim: int = DIM) -> np.ndarray:
    t = re.sub(r"\s+", " ", text.lower()).strip()
    grams = [t[i : i + n] for n in NGRAMS for i in range(len(t) - n + 1)]
    vec = np.zeros(dim, dtype=np.float32)
    if not grams:
        return vec
    h = np.fromiter((zlib.crc32(g.encode()) for g in grams), dtype=np.uint32, count=len(grams))
    sign = np.where(h & 1, 1.0, -1.0).astype(np.float32)  # signed hashing reduces collision bias
    np.add.at(vec, (h >> 1) % dim, sign)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def embed_new(con: duckdb.DuckDBPyConnection) -> int:
    """Embed only texts not embedded before (keyed by content hash)."""
    todo = con.execute("""
        SELECT DISTINCT b.content_hash, b.raw_text FROM bronze.raw_postings b
        ANTI JOIN silver.posting_embeddings e USING (content_hash)
    """).fetchall()
    if todo:
        con.executemany("INSERT INTO silver.posting_embeddings VALUES (?, ?)",
                        [(h, embed(t).tolist()) for h, t in todo])
    return len(todo)


def find_duplicates(ids: list[str], vectors: np.ndarray, threshold: float) -> list[tuple[str, str, float]]:
    """Each posting whose cosine similarity to an EARLIER posting is >= threshold is a duplicate
    of that posting's original. `ids`/`vectors` must be in chronological order."""
    # ponytail: dense O(n^2) similarity, fine to ~20k rows; use an ANN index (DuckDB vss, FAISS) beyond.
    sims = vectors @ vectors.T
    original = {}
    out = []
    for j in range(1, len(ids)):
        i = int(np.argmax(sims[j, :j]))
        if sims[j, i] >= threshold:
            root = original.get(ids[i], ids[i])
            original[ids[j]] = root
            out.append((ids[j], root, float(sims[j, i])))
    return out


def load_vectors(con: duckdb.DuckDBPyConnection) -> tuple[list[str], np.ndarray]:
    rows = con.execute("""
        SELECT b.posting_id, e.embedding FROM bronze.raw_postings b
        JOIN silver.posting_embeddings e USING (content_hash)
        ORDER BY b.posted_at, b.posting_id
    """).fetchall()
    return [r[0] for r in rows], np.array([r[1] for r in rows], dtype=np.float32)


def dedup(con: duckdb.DuckDBPyConnection, threshold: float = config.DEDUP_THRESHOLD) -> dict[str, int]:
    embedded = embed_new(con)
    ids, vectors = load_vectors(con)
    dupes = find_duplicates(ids, vectors, threshold)
    con.execute("DELETE FROM silver.duplicates")
    if dupes:
        con.executemany("INSERT INTO silver.duplicates VALUES (?, ?, ?)", dupes)
    return {"embedded": embedded, "postings": len(ids), "duplicates": len(dupes)}
