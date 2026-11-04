import json

from premonition.meta_probe import MODELS, save_probe, verified_access


def test_api_proof_is_bound_to_the_tested_key_and_all_models(tmp_path):
    entries = [{"model": model, "status": 200, "usd": 0.001} for model in MODELS]
    assert verified_access(tmp_path, "test-key") is False
    save_probe(tmp_path, "test-key", entries, True)
    assert verified_access(tmp_path, "test-key") is True
    assert verified_access(tmp_path, "other-key") is False
    save_probe(tmp_path, "test-key", entries[:-1], True)
    assert verified_access(tmp_path, "test-key") is False
    save_probe(tmp_path, "test-key", entries, False)
    assert verified_access(tmp_path, "test-key") is False


def test_probe_keeps_credentials_and_request_content_out_of_report(tmp_path):
    report = save_probe(tmp_path, "test-key", [{"model": "model", "status": 200, "api_key": "test-key", "prompt": "private"}], False)
    text = (tmp_path / "real" / "meta_smoke" / "access.json").read_text()
    assert "test-key" not in text and "private" not in text
    assert report["events"] == [{"model": "model", "status": 200}]
    assert json.loads(text)["synthetic_input"] is True
