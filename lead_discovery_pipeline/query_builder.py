"""Exa query builder templating target_company config into natural language search queries."""

from __future__ import annotations

from typing import Any, Dict, List


def build_exa_query(config: Dict[str, Any] | Any) -> str:
    """Template target_company parameters into a natural-language Exa search sentence.

    If raw_query is provided, it takes precedence and is returned as-is.
    Otherwise, templates industry, problem_solved, company_stage, and customer_type.
    Raises ValueError if all fields are empty.
    """
    tc: Dict[str, Any] = {}
    if isinstance(config, dict):
        tc = config.get("target_company", config)
    elif hasattr(config, "target_company"):
        target = getattr(config, "target_company")
        tc = target.__dict__ if hasattr(target, "__dict__") else {}
    elif hasattr(config, "__dict__"):
        tc = config.__dict__

    raw_query = tc.get("raw_query", "")
    if isinstance(raw_query, str) and raw_query.strip():
        return raw_query.strip()

    stage = str(tc.get("company_stage", "") or "").strip()
    customer = str(tc.get("customer_type", "") or "").strip()
    industry = str(tc.get("industry", "") or "").strip()
    problem = str(tc.get("problem_solved", "") or "").strip()

    descriptors = [part for part in (stage, customer, industry) if part]
    if not descriptors and not problem:
        raise ValueError("No target_company criteria or raw_query provided")

    prefix = " ".join(descriptors)
    base = f"{prefix} companies" if prefix else "companies"

    if problem:
        if problem.lower().startswith(("solving", "that", "to", "for")):
            return f"{base} {problem}"
        return f"{base} solving {problem}"

    return base


def build_exa_queries(config: Dict[str, Any] | Any) -> List[str]:
    """Build list of discovery queries from target_company and/or discovery.queries."""
    queries: List[str] = []

    try:
        q = build_exa_query(config)
        if q:
            queries.append(q)
    except ValueError:
        pass

    disc_queries: List[str] = []
    if isinstance(config, dict):
        disc_queries = config.get("discovery", {}).get("queries", [])
    elif hasattr(config, "discovery") and hasattr(config.discovery, "queries"):
        disc_queries = config.discovery.queries

    for dq in disc_queries:
        if dq and isinstance(dq, str) and dq.strip() and dq.strip() not in queries:
            queries.append(dq.strip())

    return queries
