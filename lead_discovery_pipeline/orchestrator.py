"""End-to-end 4-stage pipeline orchestrator driven by config.yaml."""

from __future__ import annotations

from dataclasses import asdict
import csv
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lead_discovery_pipeline.config import PipelineConfig, load_config
from lead_discovery_pipeline.exa_discovery import ExaClient, run_discovery_pipeline
from lead_discovery_pipeline.firecrawl import FirecrawlClient, enrich_company_content
from lead_discovery_pipeline.tavily_enrichment import lookup_decision_maker
from lead_discovery_pipeline.nim_classifier import generate_company_brief, score_company_icp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("pipeline_orchestrator")


def execute_pipeline(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Execute the full 4-stage discovery, enrichment, lookup, and scoring pipeline."""
    cfg: PipelineConfig = load_config(config_path)
    _log.info("Loaded pipeline configuration from %s", config_path)

    # -------------------------------------------------------------
    # Stage 1: Discovery (Exa Semantic Search & Lookalikes)
    # -------------------------------------------------------------
    discovered_companies: List[Dict[str, Any]] = []
    if cfg.discovery.enabled:
        _log.info("=== Stage 1: Discovery (Exa) ===")
        discovery_result = run_discovery_pipeline(
            output_path=cfg.storage.raw_leads_path,
            cap=cfg.discovery.call_cap,
            queries=cfg.discovery.queries,
            seeds=cfg.discovery.seed_urls,
            config=asdict(cfg),
        )
        discovered_companies = discovery_result.get("candidates", [])
        _log.info("Discovered %d candidate companies", len(discovered_companies))
    else:
        _log.info("Stage 1 (Discovery) disabled in config; checking raw leads file")
        raw_file = Path(cfg.storage.raw_leads_path)
        if raw_file.exists():
            with open(raw_file, "r", encoding="utf-8") as f:
                discovered_companies = json.load(f)

    if not discovered_companies:
        _log.warning("No candidate companies to process.")
        return {"processed": 0, "qualified": 0}

    # -------------------------------------------------------------
    # Stages 2, 3, 4: Enrichment, Decision-Maker Lookup, Scoring
    # -------------------------------------------------------------
    firecrawl = FirecrawlClient(timeout=cfg.enrichment.timeout_seconds)
    enriched_results: List[Dict[str, Any]] = []
    qualified_rows: List[Dict[str, Any]] = []

    for idx, comp in enumerate(discovered_companies, 1):
        name = comp.get("title") or comp.get("name") or comp.get("domain", "")
        url = comp.get("url") or f"https://{comp.get('domain', '')}"
        domain = comp.get("domain", "")
        _log.info("[%d/%d] Processing company: %s (%s)", idx, len(discovered_companies), name, url)

        # Stage 2: Web Scraping & Context Enrichment (Firecrawl)
        content_info = {
            "homepage_content": comp.get("snippet", ""),
            "about_content": "",
            "combined_content": comp.get("snippet", ""),
        }
        if cfg.enrichment.enabled and url:
            _log.info("  -> Stage 2: Enriching web context via Firecrawl...")
            scraped = enrich_company_content(
                url,
                client=firecrawl,
                scrape_about=cfg.enrichment.scrape_about_page,
                about_keywords=cfg.enrichment.about_path_keywords,
                max_length=cfg.enrichment.max_content_length,
            )
            if scraped.get("combined_content"):
                content_info = scraped

        # Stage 3: Decision-Maker Identification (Tavily)
        dm_info = {
            "name": "",
            "title": "",
            "linkedin_url": "",
            "confidence": "none",
        }
        if cfg.decision_maker.enabled and name:
            _log.info("  -> Stage 3: Looking up decision makers for roles %s...", cfg.decision_maker.target_roles)
            dm_res = lookup_decision_maker(
                company_name=name,
                company_domain=domain,
                target_roles=cfg.decision_maker.target_roles,
                max_results=cfg.decision_maker.max_search_results,
            )
            dm_info = {
                "name": dm_res.name,
                "title": dm_res.title,
                "linkedin_url": dm_res.linkedin_url,
                "confidence": dm_res.confidence,
            }

        # Stage 4: ICP Classification & Scoring (NVIDIA NIM)
        scoring_info = {
            "fit_score": 0.0,
            "is_qualified": True,
            "matched_criteria": [],
            "unmatched_criteria": [],
            "reasoning": "Classification skipped",
        }
        if cfg.classification.enabled:
            _log.info("  -> Stage 4: Scoring against ICP criteria via NIM LLM...")
            scoring_info = score_company_icp(
                company_name=name,
                company_context=content_info.get("combined_content", ""),
                icp_criteria=cfg.classification.icp_criteria,
                model=cfg.classification.model,
                temperature=cfg.classification.temperature,
            )

        company_brief = ""
        is_lead_qualified = (
            scoring_info["is_qualified"]
            and scoring_info["fit_score"] >= cfg.classification.min_fit_score
        )
        if is_lead_qualified and cfg.classification.enabled:
            _log.info("  -> Stage 4: Generating company brief for qualified lead...")
            company_brief = generate_company_brief(
                company_name=name,
                company_context=content_info.get("combined_content", ""),
                model=cfg.classification.model,
                temperature=cfg.classification.temperature,
            )

        lead_record = {
            "company_name": name,
            "domain": domain,
            "url": url,
            "company_brief": company_brief,
            "decision_maker_name": dm_info["name"],
            "decision_maker_title": dm_info["title"],
            "decision_maker_linkedin": dm_info["linkedin_url"],
            "fit_score": scoring_info["fit_score"],
            "is_qualified": scoring_info["is_qualified"],
            "matched_criteria": "; ".join(scoring_info["matched_criteria"]),
            "unmatched_criteria": "; ".join(scoring_info["unmatched_criteria"]),
            "reasoning": scoring_info["reasoning"],
        }
        enriched_results.append(lead_record)

        if is_lead_qualified:
            qualified_rows.append(lead_record)

        time.sleep(0.2)

    # Save Enriched JSON
    enrich_out = Path(cfg.storage.enriched_leads_path)
    enrich_out.parent.mkdir(parents=True, exist_ok=True)
    with open(enrich_out, "w", encoding="utf-8") as f:
        json.dump(enriched_results, f, indent=2)

    # Save Final Qualified CSV
    csv_out = Path(cfg.storage.final_output_csv)
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    if qualified_rows:
        with open(csv_out, "w", encoding="utf-8", newline="") as f:
            fieldnames = [
                "company_name", "domain", "url", "company_brief",
                "decision_maker_name", "decision_maker_title", "decision_maker_linkedin",
                "fit_score", "is_qualified", "matched_criteria", "unmatched_criteria", "reasoning"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(qualified_rows)

    _log.info("Pipeline execution complete!")
    _log.info("Total processed: %d | Qualified leads: %d", len(enriched_results), len(qualified_rows))
    _log.info("Outputs written to %s and %s", cfg.storage.enriched_leads_path, cfg.storage.final_output_csv)

    return {
        "processed": len(enriched_results),
        "qualified": len(qualified_rows),
        "enriched_json": str(enrich_out),
        "qualified_csv": str(csv_out),
    }


if __name__ == "__main__":
    import sys
    conf = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    execute_pipeline(conf)
