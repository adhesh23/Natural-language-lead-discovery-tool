import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from lead_discovery_pipeline.config import PipelineConfig, load_config
from lead_discovery_pipeline.nim_classifier import score_company_icp
from lead_discovery_pipeline.tavily_enrichment import lookup_decision_maker
from lead_discovery_pipeline.firecrawl import find_about_page_url, enrich_company_content


def test_load_config(tmp_path):
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(
        """
discovery:
  call_cap: 5
  queries:
    - "custom test query"
decision_maker:
  target_roles:
    - "Head of Sales"
classification:
  icp_criteria:
    - "Must be B2B software"
""",
        encoding="utf-8",
    )
    cfg = load_config(config_file)
    assert cfg.discovery.call_cap == 5
    assert cfg.discovery.queries == ["custom test query"]
    assert cfg.decision_maker.target_roles == ["Head of Sales"]
    assert cfg.classification.icp_criteria == ["Must be B2B software"]


def test_find_about_page_url():
    sample_md = "Welcome to our tool. Read more at [Our Leadership Team](/leadership) or contact us."
    url = find_about_page_url("https://example.com", sample_md)
    assert url == "https://example.com/leadership"


def test_score_company_icp_mock():
    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "fit_score": 0.85,
                        "is_qualified": True,
                        "matched_criteria": ["B2B SaaS product"],
                        "unmatched_criteria": [],
                        "reasoning": "Strong match for B2B criteria",
                    })
                }
            }
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        res = score_company_icp(
            "TestCo",
            "TestCo builds B2B cloud infrastructure workflows.",
            ["B2B SaaS product"],
            api_key="mock-key",
        )
        assert res["fit_score"] == 0.85
        assert res["is_qualified"] is True
        assert "B2B SaaS product" in res["matched_criteria"]


def test_lookup_decision_maker_mock():
    mock_hits = [
        {
            "title": "Jane Doe - VP Marketing - TechCo | LinkedIn",
            "url": "https://www.linkedin.com/in/janedoe",
            "content": "VP Marketing at TechCo managing growth.",
        }
    ]
    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "name": "Jane Doe",
                        "title": "VP Marketing",
                        "linkedin_url": "https://www.linkedin.com/in/janedoe",
                        "confidence": "high",
                        "reasoning": "Direct LinkedIn profile match",
                    })
                }
            }
        ]
    }

    with patch("lead_discovery_pipeline.tavily_enrichment.tavily_search", return_value=mock_hits):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_cm

            res = lookup_decision_maker(
                "TechCo",
                ["VP Marketing"],
                nim_key="mock-nim-key",
            )
            assert res.name == "Jane Doe"
            assert res.title == "VP Marketing"
            assert "linkedin.com/in/janedoe" in res.linkedin_url
            assert res.confidence == "high"
