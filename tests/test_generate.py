from llm_etl import config, generate


def test_committed_dataset_is_reproducible(tmp_path, monkeypatch):
    for name in ("RAW_POSTINGS", "GROUND_TRUTH", "GOLDEN_LABELS"):
        monkeypatch.setattr(generate, name, tmp_path / getattr(config, name).name)
    counts = generate.generate()
    assert counts == {"valid": 630, "duplicate": 60, "invalid": 12}
    for name in ("RAW_POSTINGS", "GROUND_TRUTH", "GOLDEN_LABELS"):
        assert (tmp_path / getattr(config, name).name).read_bytes() == getattr(config, name).read_bytes()
