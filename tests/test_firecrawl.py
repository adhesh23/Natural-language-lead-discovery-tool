import pytest
from lead_discovery_pipeline.firecrawl import FirecrawlClient


def test_firecrawl_auto_discovers_numbered_keys(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY_1", "key-one")
    monkeypatch.setenv("FIRECRAWL_API_KEY_2", "key-two")
    monkeypatch.setenv("FIRECRAWL_API_KEY_3", "key-three")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    client = FirecrawlClient()
    assert client.api_keys == ["key-one", "key-two", "key-three"]
    assert client.get_active_key() == "key-one"


def test_firecrawl_falls_back_to_single_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY_1", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY_2", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY_3", raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fallback-key")

    client = FirecrawlClient()
    assert client.api_keys == ["fallback-key"]
    assert client.get_active_key() == "fallback-key"


def test_firecrawl_switches_keys_on_credit_exhaustion():
    calls = []

    def mock_fetch(url, payload, headers):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            # First key fails with credits exhausted
            import urllib.error
            from io import BytesIO
            fp = BytesIO(b'{"error": "Payment Required: Insufficient credits"}')
            raise urllib.error.HTTPError(url, 402, "Payment Required", {}, fp)
        return {"success": True, "data": {"markdown": "# Scraped Content"}}

    client = FirecrawlClient(
        api_keys=["key-1", "key-2", "key-3"],
        http_fetch=mock_fetch,
    )

    result = client.scrape("https://example.com")

    assert result["success"] is True
    assert result["data"]["markdown"] == "# Scraped Content"
    assert calls == ["Bearer key-1", "Bearer key-2"]
    # The active key index advanced to key-2
    assert client.active_key_index == 1
    assert client.get_active_key() == "key-2"


def test_firecrawl_reports_failure_when_all_keys_exhausted():
    calls = []

    def mock_fetch(url, payload, headers):
        calls.append(headers["Authorization"])
        import urllib.error
        from io import BytesIO
        fp = BytesIO(b'{"error": "Rate limit / credits exhausted"}')
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, fp)

    client = FirecrawlClient(
        api_keys=["key-1", "key-2"],
        http_fetch=mock_fetch,
    )

    result = client.scrape("https://example.com")

    assert result["success"] is False
    assert "exhausted credits" in result["error"]
    assert calls == ["Bearer key-1", "Bearer key-2"]

