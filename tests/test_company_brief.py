import json
from unittest.mock import MagicMock, patch
import pytest

from lead_discovery_pipeline.nim_classifier import (
    INSUFFICIENT_CONTEXT_FLAG,
    generate_company_brief,
)


def test_generate_company_brief_thin_or_empty_context():
    # Empty string
    assert generate_company_brief("Acme", "") == INSUFFICIENT_CONTEXT_FLAG

    # Whitespace only
    assert generate_company_brief("Acme", "    \n\t  ") == INSUFFICIENT_CONTEXT_FLAG

    # Extremely thin context (< 60 chars)
    assert generate_company_brief("Acme", "Acme is a tool.") == INSUFFICIENT_CONTEXT_FLAG


def test_generate_company_brief_normal_context_mock():
    sample_context = (
        "Acme Corp provides automated logistics and fleet routing software for regional freight carriers. "
        "The platform integrates directly into dispatch management systems via REST APIs and real-time telemetry. "
        "With over 200 commercial fleets actively using its dispatch optimization algorithms, Acme helps logistics "
        "operators reduce deadhead miles and track regulatory compliance across the United States."
    )

    sample_brief = (
        "Acme Corp develops automated logistics and fleet routing software engineered specifically for regional freight carriers. "
        "Its platform integrates into dispatch management systems via REST APIs and real-time vehicle telemetry to optimize route scheduling. "
        "The company serves commercial freight operators across the United States, currently managing over 200 active fleets while reducing deadhead "
        "mileage and ensuring compliance with federal transportation regulations."
    )

    # Word count check on mock brief:
    word_count = len(sample_brief.split())
    assert 50 <= word_count <= 100

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": sample_brief
                }
            }
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        brief = generate_company_brief(
            "Acme Corp",
            sample_context,
            api_key="mock-nim-key",
        )

        assert brief == sample_brief
        assert 50 <= len(brief.split()) <= 100
        mock_urlopen.assert_called_once()


def test_generate_company_brief_missing_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NIM_API_KEY", raising=False)

    context = "A" * 100
    res = generate_company_brief("Acme Corp", context, api_key=None)
    assert "No NVIDIA NIM API key available" in res


def test_generate_company_brief_api_error():
    context = "A" * 100
    with patch("urllib.request.urlopen", side_effect=RuntimeError("Connection timeout")):
        res = generate_company_brief("Acme Corp", context, api_key="mock-key")
        assert "Brief generation failed" in res
