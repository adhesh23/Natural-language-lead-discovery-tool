from lead_discovery_pipeline.dedup_store import DedupStore, StoredSignal, normalize_domain


def test_normalize_domain_removes_url_details_and_www() -> None:
    assert normalize_domain("https://www.Example.com:443/pricing?ref=test") == "example.com"


def test_add_returns_false_when_normalized_domain_already_exists(tmp_path) -> None:
    store = DedupStore(tmp_path / "dedup.sqlite3")

    assert store.exists("example.com") is False
    assert store.add(
        "Example", "https://www.example.com", "funding", "2026-09-13", "Series A news"
    ) is True
    assert store.exists("http://example.com/careers") is True
    assert store.add(
        "Example renamed", "example.com", "product_launch", "2026-09-14", "AI launch"
    ) is False
    assert [signal.signal_type for signal in store.get_signals("example.com")] == [
        "funding",
        "product_launch",
    ]


def test_get_returns_the_original_persistent_record(tmp_path) -> None:
    database_path = tmp_path / "dedup.sqlite3"
    DedupStore(database_path).add(
        "Acme", "acme.com", "ai_job_posting", "2026-09-13", "ML engineer listing"
    )

    stored = DedupStore(database_path).get("https://www.acme.com")

    assert stored is not None
    assert stored.domain == "acme.com"
    assert stored.company_name == "Acme"


def test_duplicate_signal_is_stored_only_once(tmp_path) -> None:
    store = DedupStore(tmp_path / "dedup.sqlite3")
    signal = ("funding", "2026-09-13", "Acme raises a seed round")

    assert store.add("Acme", "acme.com", *signal) is True
    assert store.add("Acme", "www.acme.com", *signal) is False
    assert store.get_signals("acme.com") == [StoredSignal(*signal)]


def test_signal_summary_and_filter_result_persist(tmp_path) -> None:
    store = DedupStore(tmp_path / "dedup.sqlite3")
    store.add("Acme", "acme.com", "funding", "2026-09-13", "Acme raises a Seed round")

    assert store.get_signal_summary("acme.com").total_signals == 1
    store.save_filter_result("Acme", "acme.com", True, ["size: unknown, no signal available"])

    result = store.get_filter_result("acme.com")
    assert result is not None
    assert result.passed is True
    assert result.reasons == ("size: unknown, no signal available",)

