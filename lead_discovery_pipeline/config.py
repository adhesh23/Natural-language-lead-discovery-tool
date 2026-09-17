"""Unified configuration loader for the lead discovery pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class TargetCompanyConfig:
    industry: str = ""
    problem_solved: str = ""
    company_stage: str = ""
    customer_type: str = ""
    raw_query: str = ""


@dataclass
class DiscoveryConfig:
    enabled: bool = True
    call_cap: int = 10
    num_results_per_query: int = 10
    queries: List[str] = field(default_factory=list)
    seed_urls: List[str] = field(default_factory=list)


@dataclass
class EnrichmentConfig:
    enabled: bool = True
    timeout_seconds: float = 30.0
    max_content_length: int = 15000
    scrape_about_page: bool = True
    about_path_keywords: List[str] = field(default_factory=lambda: [
        "about", "team", "leadership", "company", "who-we-are"
    ])


@dataclass
class DecisionMakerConfig:
    enabled: bool = True
    target_roles: List[str] = field(default_factory=lambda: [
        "Head of Growth", "VP of Marketing", "Founder", "CEO"
    ])
    max_search_results: int = 5
    search_depth: str = "basic"


@dataclass
class ClassificationConfig:
    enabled: bool = True
    model: str = "meta/llama-3.2-11b-vision-instruct"
    temperature: float = 0.0
    icp_criteria: List[str] = field(default_factory=lambda: [
        "Company provides a B2B SaaS or technology platform",
        "Company is an early-to-mid stage growth company (roughly 10-150 headcount)",
        "Demonstrated commercial traction or institutional funding",
        "Has workflow, API, or automated capabilities in product",
    ])
    min_fit_score: float = 0.7


@dataclass
class FilterConfig:
    min_employees: int = 10
    max_employees: int = 150
    allowed_funding_stages: List[str] = field(default_factory=lambda: [
        "seed", "series a", "series b", "bootstrapped"
    ])
    allowed_countries: List[str] = field(default_factory=lambda: [
        "US", "United States", "USA"
    ])
    reject_foreign_cctld: bool = True


@dataclass
class StorageConfig:
    database_path: str = "data/leads.sqlite3"
    raw_leads_path: str = "data/raw_leads.json"
    enriched_leads_path: str = "data/enriched_leads.json"
    final_output_csv: str = "data/qualified_leads.csv"


@dataclass
class PipelineConfig:
    target_company: TargetCompanyConfig = field(default_factory=TargetCompanyConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    decision_maker: DecisionMakerConfig = field(default_factory=DecisionMakerConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


def load_config(config_path: str | Path = "config.yaml") -> PipelineConfig:
    """Load configuration from a YAML file, falling back to default values."""
    path = Path(config_path)
    data: Dict[str, Any] = {}

    if path.exists() and yaml is not None:
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded

    tc_data = data.get("target_company", {})
    disc_data = data.get("discovery", {})
    enrich_data = data.get("enrichment", {})
    dm_data = data.get("decision_maker", {})
    class_data = data.get("classification", {})
    filter_data = data.get("filters", {})
    storage_data = data.get("storage", {})

    return PipelineConfig(
        target_company=TargetCompanyConfig(
            industry=tc_data.get("industry", ""),
            problem_solved=tc_data.get("problem_solved", ""),
            company_stage=tc_data.get("company_stage", ""),
            customer_type=tc_data.get("customer_type", ""),
            raw_query=tc_data.get("raw_query", ""),
        ),
        discovery=DiscoveryConfig(
            enabled=disc_data.get("enabled", True),
            call_cap=disc_data.get("call_cap", 10),
            num_results_per_query=disc_data.get("num_results_per_query", 10),
            queries=disc_data.get("queries", []),
            seed_urls=disc_data.get("seed_urls", []),
        ),
        enrichment=EnrichmentConfig(
            enabled=enrich_data.get("enabled", True),
            timeout_seconds=float(enrich_data.get("timeout_seconds", 30.0)),
            max_content_length=int(enrich_data.get("max_content_length", 15000)),
            scrape_about_page=enrich_data.get("scrape_about_page", True),
            about_path_keywords=enrich_data.get("about_path_keywords", [
                "about", "team", "leadership", "company", "who-we-are"
            ]),
        ),
        decision_maker=DecisionMakerConfig(
            enabled=dm_data.get("enabled", True),
            target_roles=dm_data.get("target_roles", [
                "Head of Growth", "VP of Marketing", "Founder", "CEO"
            ]),
            max_search_results=int(dm_data.get("max_search_results", 5)),
            search_depth=dm_data.get("search_depth", "basic"),
        ),
        classification=ClassificationConfig(
            enabled=class_data.get("enabled", True),
            model=class_data.get("model", "meta/llama-3.2-11b-vision-instruct"),
            temperature=float(class_data.get("temperature", 0.0)),
            icp_criteria=class_data.get("icp_criteria", [
                "Company provides a B2B SaaS or technology platform",
                "Company is an early-to-mid stage growth company (roughly 10-150 headcount)",
                "Demonstrated commercial traction or institutional funding",
                "Has workflow, API, or automated capabilities in product",
            ]),
            min_fit_score=float(class_data.get("min_fit_score", 0.7)),
        ),
        filters=FilterConfig(
            min_employees=int(filter_data.get("min_employees", 10)),
            max_employees=int(filter_data.get("max_employees", 150)),
            allowed_funding_stages=filter_data.get("allowed_funding_stages", [
                "seed", "series a", "series b", "bootstrapped"
            ]),
            allowed_countries=filter_data.get("allowed_countries", [
                "US", "United States", "USA"
            ]),
            reject_foreign_cctld=filter_data.get("reject_foreign_cctld", True),
        ),
        storage=StorageConfig(
            database_path=storage_data.get("database_path", "data/leads.sqlite3"),
            raw_leads_path=storage_data.get("raw_leads_path", "data/raw_leads.json"),
            enriched_leads_path=storage_data.get("enriched_leads_path", "data/enriched_leads.json"),
            final_output_csv=storage_data.get("final_output_csv", "data/qualified_leads.csv"),
        ),
    )
