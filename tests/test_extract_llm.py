"""LLM extractor behaviour with a fake Anthropic client (no network, no key)."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from llm_etl import config, extract, extract_llm, warehouse
from llm_etl.extract_llm import LLMOutput

GOOD = {"title": "Data Engineer", "seniority": "mid", "skills": ["python"], "salary_min": 100_000,
            "salary_max": 120_000, "salary_currency": "USD", "remote_policy": "remote", "location": None}


def response(fields: dict, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=LLMOutput(**fields), stop_reason=stop_reason, content=[],
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def fake_client(*responses):
    return SimpleNamespace(messages=FakeMessages(responses))


def test_validation_failure_is_fed_back_and_retried():
    client = fake_client(response({**GOOD, "salary_min": 130_000}), response(GOOD))
    out = extract_llm.extract(client, "Data Engineer ...")
    assert out["error"] is None and out["result"]["salary_min"] == 100_000
    assert out["attempts"] == 2
    assert (out["input_tokens"], out["output_tokens"]) == (2000, 200)
    assert out["cost_usd"] == pytest.approx((2000 * config.PRICE_IN_PER_MTOK + 200 * config.PRICE_OUT_PER_MTOK) / 1e6)
    retry_prompt = client.messages.calls[1]["messages"][-1]["content"]
    assert "salary_min 130000 > salary_max 120000" in retry_prompt
    assert client.messages.calls[0]["output_format"] is LLMOutput


def test_gives_up_after_max_attempts_with_reason():
    spam = {**GOOD, "title": None, "remote_policy": None}
    out = extract_llm.extract(fake_client(*[response(spam)] * extract_llm.MAX_ATTEMPTS), "EARN $$$")
    assert out["result"] is None and "title" in out["error"]
    assert out["attempts"] == extract_llm.MAX_ATTEMPTS


def test_refusal_is_not_retried():
    out = extract_llm.extract(fake_client(response(GOOD, stop_reason="refusal")), "...")
    assert out["attempts"] == 1 and "refusal" in out["error"]


def test_transient_api_errors_are_not_cached(tmp_path, monkeypatch):
    """A batch that hits an outage persists the records that succeeded and leaves the failed
    one uncached, so the next run retries only that record."""
    monkeypatch.setattr(config, "LLM_CONCURRENCY", 1)
    con = warehouse.connect(tmp_path / "t.duckdb")
    con.executemany("INSERT INTO bronze.raw_postings (posting_id, source, company, posted_at, raw_text, "
                    "content_hash) VALUES (?, 's', 'c', DATE '2026-06-01', ?, ?)",
                    [(f"P{i}", f"text {i}", f"h{i}") for i in range(3)])
    outage = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(anthropic.APIConnectionError):
        extract.run_extraction(con, use_llm=True,
                               client=fake_client(response(GOOD), outage, response(GOOD)))
    assert con.execute("SELECT count(*) FROM silver.extraction_cache").fetchone()[0] == 2

    stats = extract.run_extraction(con, use_llm=True, client=fake_client(response(GOOD)))
    assert stats["extracted_now"] == 1 and stats["silver_rows"] == 3
