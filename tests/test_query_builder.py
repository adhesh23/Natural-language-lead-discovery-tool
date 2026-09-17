import pytest
from lead_discovery_pipeline.query_builder import build_exa_query, build_exa_queries


def test_build_exa_query_raw_override():
    config = {
        "target_company": {
            "industry": "vertical SaaS",
            "problem_solved": "field service operations",
            "company_stage": "early-stage",
            "customer_type": "B2B",
            "raw_query": "Custom override search query",
        }
    }
    assert build_exa_query(config) == "Custom override search query"


def test_build_exa_query_all_four_fields():
    config = {
        "target_company": {
            "industry": "vertical SaaS",
            "problem_solved": "field service operations",
            "company_stage": "early-stage",
            "customer_type": "B2B",
        }
    }
    query = build_exa_query(config)
    assert query == "early-stage B2B vertical SaaS companies solving field service operations"


def test_build_exa_query_partial_fields():
    # Only industry
    assert build_exa_query({"target_company": {"industry": "fintech"}}) == "fintech companies"

    # Only problem_solved
    assert build_exa_query({"target_company": {"problem_solved": "cross-border payments"}}) == "companies solving cross-border payments"

    # Stage and customer_type
    assert build_exa_query({"target_company": {"company_stage": "early-stage", "customer_type": "B2B"}}) == "early-stage B2B companies"


def test_build_exa_query_empty_config_raises():
    with pytest.raises(ValueError, match="No target_company criteria or raw_query provided"):
        build_exa_query({})

    with pytest.raises(ValueError, match="No target_company criteria or raw_query provided"):
        build_exa_query({"target_company": {"industry": "", "problem_solved": "  ", "raw_query": ""}})


def test_build_exa_queries_combines_target_and_discovery_queries():
    config = {
        "target_company": {"industry": "developer tooling"},
        "discovery": {"queries": ["API monitoring and observability tools"]},
    }
    queries = build_exa_queries(config)
    assert "developer tooling companies" in queries
    assert "API monitoring and observability tools" in queries
