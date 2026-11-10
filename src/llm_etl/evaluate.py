"""Measured quality: extraction accuracy on the golden set, dedup and quarantine vs ground truth."""

import json
from collections import Counter

import duckdb

from llm_etl import config, dedup

SCALAR_FIELDS = ["title", "seniority", "salary_min", "salary_max", "salary_currency", "remote_policy", "location"]


def _jsonl(path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def _score(golden: list[dict], preds: dict[str, dict]) -> dict:
    correct = dict.fromkeys(SCALAR_FIELDS, 0)
    tp = fp = fn = exact_skills = 0
    for g in golden:
        p = preds.get(g["posting_id"], {})
        for f in SCALAR_FIELDS:
            correct[f] += bool(p) and _norm(p[f]) == _norm(g[f])
        ps, gs = set(p.get("skills", [])), set(g["skills"])
        tp, fp, fn = tp + len(ps & gs), fp + len(ps - gs), fn + len(gs - ps)
        exact_skills += bool(p) and ps == gs
    n = len(golden)
    precision, recall = tp / (tp + fp) if tp + fp else 0.0, tp / (tp + fn) if tp + fn else 0.0
    return {
        "records": n,
        "extracted": sum(g["posting_id"] in preds for g in golden),
        "field_accuracy": {f: round(c / n, 4) for f, c in correct.items()},
        "skills": {"precision": round(precision, 4), "recall": round(recall, 4),
                   "f1": round(2 * precision * recall / (precision + recall), 4) if tp else 0.0,
                   "exact_set_accuracy": round(exact_skills / n, 4)},
    }


def extraction_metrics(con: duckdb.DuckDBPyConnection, extractor: str) -> dict:
    """Field-level accuracy over the golden set, overall and per slice. A record the extractor
    quarantined counts as wrong on every field (it is missing from the warehouse)."""
    golden = _jsonl(config.GOLDEN_LABELS)
    rows = con.execute("""
        SELECT b.posting_id, c.result FROM bronze.raw_postings b
        JOIN silver.extraction_cache c ON c.content_hash = b.content_hash AND c.extractor = ?
        WHERE c.error IS NULL
    """, [extractor]).fetchall()
    preds = {pid: json.loads(result) for pid, result in rows}
    slices = sorted({g["slice"] for g in golden})
    return {"extractor": extractor, "overall": _score(golden, preds),
            **{s: _score([g for g in golden if g["slice"] == s], preds) for s in slices}}


def dedup_metrics(con: duckdb.DuckDBPyConnection, thresholds=(0.80, 0.85, 0.88, 0.90, 0.92, 0.95)) -> dict:
    truth = {t["posting_id"]: t for t in _jsonl(config.GROUND_TRUTH)}
    actual = {pid for pid, t in truth.items() if t["kind"] == "duplicate"}

    def score(found: list[tuple[str, str, float]]) -> dict:
        predicted = {d[0] for d in found}
        tp = len(predicted & actual)
        return {"flagged": len(predicted), "true_positives": tp, "false_positives": len(predicted - actual),
                "missed": len(actual - predicted),
                "precision": round(tp / len(predicted), 4) if predicted else 0.0,
                "recall": round(tp / len(actual), 4) if actual else 0.0,
                "correct_original": sum(truth[d[0]]["duplicate_of"] == d[1] for d in found if d[0] in actual)}

    current = con.execute("SELECT posting_id, duplicate_of, similarity FROM silver.duplicates").fetchall()
    ids, vectors = dedup.load_vectors(con)
    sims, pos = vectors @ vectors.T, {pid: i for i, pid in enumerate(ids)}
    # Separation margin: how similar the least-similar true repost is to its original, vs the most
    # similar earlier posting for any non-duplicate. A wide gap means the threshold is not fragile.
    dup_sims = [sims[pos[p], pos[truth[p]["duplicate_of"]]] for p in actual]
    nondup_max = max(sims[j, :j].max() for j in range(1, len(ids)) if ids[j] not in actual)
    return {"ground_truth_duplicates": len(actual), "threshold": config.DEDUP_THRESHOLD, **score(current),
            "min_duplicate_similarity": round(float(min(dup_sims)), 4),
            "max_non_duplicate_similarity": round(float(nondup_max), 4),
            "sweep": {str(t): score(dedup.find_duplicates(ids, vectors, t)) for t in thresholds}}


def quarantine_metrics(con: duckdb.DuckDBPyConnection) -> dict:
    truth = {t["posting_id"]: t["kind"] for t in _jsonl(config.GROUND_TRUTH)}
    rows = con.execute("SELECT posting_id, error FROM silver.quarantine").fetchall()
    flagged = {pid for pid, _ in rows}
    invalid = {pid for pid, kind in truth.items() if kind == "invalid"}
    return {"ground_truth_invalid": len(invalid), "quarantined": len(flagged),
            "invalid_caught": len(flagged & invalid), "valid_quarantined": len(flagged - invalid),
            "valid_quarantined_reasons": dict(Counter(e for pid, e in rows if pid not in invalid))}


def run_eval(con: duckdb.DuckDBPyConnection) -> dict:
    extractors = [r[0] for r in con.execute(
        "SELECT DISTINCT extractor FROM silver.extraction_cache ORDER BY extractor").fetchall()]
    cost = con.execute("""
        SELECT extractor, count(*), sum(input_tokens), sum(output_tokens), round(sum(cost_usd), 6),
               round(avg(attempts), 3) FROM silver.extraction_cache GROUP BY extractor ORDER BY extractor
    """).fetchall()
    return {
        "extraction": [extraction_metrics(con, e) for e in extractors],
        "llm_usage": [dict(zip(["extractor", "records", "input_tokens", "output_tokens", "cost_usd",
                                "avg_attempts"], r)) for r in cost],
        "dedup": dedup_metrics(con),
        "quarantine": quarantine_metrics(con),
    }
