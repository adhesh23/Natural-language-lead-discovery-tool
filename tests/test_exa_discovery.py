import pytest
from lead_discovery_pipeline.exa_discovery import (
    ExaClient,
    ExaRateGuard,
    discover_by_query,
    discover_by_similar,
)


def test_exa_auto_discovers_numbered_keys(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY_1", "exa-one")
    monkeypatch.setenv("EXA_API_KEY_2", "exa-two")
    monkeypatch.setenv("EXA_API_KEY_3", "exa-three")
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    client = ExaClient()
    assert client.api_keys == ["exa-one", "exa-two", "exa-three"]
    assert client.get_active_key() == "exa-one"


def test_exa_falls_back_to_single_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY_1", raising=False)
    monkeypatch.delenv("EXA_API_KEY_2", raising=False)
    monkeypatch.delenv("EXA_API_KEY_3", raising=False)
    monkeypatch.setenv("EXA_API_KEY", "exa-fallback-key")

    client = ExaClient()
    assert client.api_keys == ["exa-fallback-key"]
    assert client.get_active_key() == "exa-fallback-key"


def test_exa_key_failover_key1_and_key2_fail_key3_succeeds():
    calls = []

    def mock_post(url, payload, headers):
        api_key = headers["x-api-key"]
        calls.append(api_key)
        if api_key == "key-1":
            # Simulate 401 Unauthorized / auth failure
            raise Exception("HTTP 401: Unauthorized API key")
        elif api_key == "key-2":
            # Simulate 429 Rate / credit quota limit
            raise Exception("HTTP 429: Quota exceeded")
        elif api_key == "key-3":
            return {
                "results": [
                    {
                        "title": "Third-Key SaaS Platform",
                        "url": "https://thirdkey-saas.com/overview",
                        "highlights": ["Configurable workflow SaaS platform"],
                    }
                ]
            }
        raise RuntimeError("Unexpected key")

    client = ExaClient(
        api_keys=["key-1", "key-2", "key-3"],
        http_post=mock_post,
    )

    guard = ExaRateGuard(max_calls=10)
    results = discover_by_query("B2B SaaS workflows", num_results=5, client=client, guard=guard)

    assert len(results) == 1
    assert results[0]["domain"] == "thirdkey-saas.com"
    assert results[0]["title"] == "Third-Key SaaS Platform"
    # Verifies key-1 and key-2 were tried before key-3 succeeded
    assert calls == ["key-1", "key-2", "key-3"]
    # Verifies active key persisted at index 2 (key-3)
    assert client.active_key_index == 2
    assert client.get_active_key() == "key-3"


def test_exa_skips_when_all_keys_fail_without_crashing():
    calls = []

    def mock_post(url, payload, headers):
        calls.append(headers["x-api-key"])
        raise Exception("HTTP 500: Internal Server Error")

    client = ExaClient(
        api_keys=["key-1", "key-2", "key-3"],
        http_post=mock_post,
    )

    guard = ExaRateGuard(max_calls=10)
    # Both discover_by_query and discover_by_similar should gracefully return [] without crashing
    query_res = discover_by_query("test query", num_results=5, client=client, guard=guard)
    similar_res = discover_by_similar("https://example.com", num_results=5, client=client, guard=guard)

    assert query_res == []
    assert similar_res == []
    assert guard.calls_made == 2


def test_exa_rate_guard_halts_at_cap():
    guard = ExaRateGuard(max_calls=2)
    guard.record_call("call_1")
    guard.record_call("call_2")

    with pytest.raises(RuntimeError, match="Exa API call limit reached"):
        guard.record_call("call_3")

