# AGENTS.md — Developer & AI Agent Guide

## 1. Project Purpose & Overview
This repository contains a generic, config-driven pipeline that discovers companies matching a user-defined Ideal Customer Profile (ICP), enriches them with public web context, identifies relevant executive decision-makers, and produces a scored, summarized shortlist. The tool is designed to be fully open-source and modular: targeting criteria, search queries, decision-maker roles, and scoring rules are defined entirely in configuration without hardcoding domain-specific or client-specific logic.

---

## 2. 5-Stage Architecture & Implementation Status

The pipeline is organized into five sequential stages. Based on the current codebase, the status of each stage is as follows:

```
[Config: target_company + ICP]
              │
              ▼
   Stage 1: Discovery (Exa)
              │
              ▼
   Stage 2: Web Enrichment (Firecrawl)
              │
              ▼
   Stage 3: Decision-Maker Lookup (Tavily)
              │
              ▼
   Stage 4: NIM Processing (Brief + Scoring)
              │
              ▼
   Stage 5: Output (CSV / JSON Shortlist)
```

### Stage 1: Discovery (`Exa`) — *Partially Built*
* **Intended Design:** Takes structured targeting parameters from `config.yaml` (`target_company`: `industry`, `problem_solved`, `company_stage`, `customer_type`) or an optional `raw_query` override, templates them into a natural-language search sentence, and executes neural search via Exa's API (and lookalike search via `findSimilar`) to discover candidate companies and their URLs.
* **Current Status:**
  * **Built:** Core Exa API client (`lead_discovery_pipeline/exa_discovery.py`), multi-key auto-discovery (`EXA_API_KEY_1..3`, `EXA_API_KEY`), failover on rate/auth limits, call-cap guard (`ExaRateGuard`), and domain deduplication.
  * **Still to be built:** `lead_discovery_pipeline/query_builder.py` to template the `target_company` fields into natural language sentences and integrate it directly into `exa_discovery.py`.

### Stage 2: Web Enrichment (`Firecrawl`) — *Built*
* **Intended Design:** Crawls each candidate's public-facing website (homepage, `/about`, `/team`, `/company` — strictly external pages, no auth/private access) and returns clean markdown context per company.
* **Current Status:**
  * **Built:** `lead_discovery_pipeline/firecrawl.py` provides `FirecrawlClient` with multi-key credit exhaustion rotation (`FIRECRAWL_API_KEY_1..3`, `FIRECRAWL_API_KEY`), automated about/team link discovery (`find_about_page_url`), and combined markdown scraping (`enrich_company_content`).

### Stage 3: Decision-Maker Lookup (`Tavily`) — *Built*
* **Intended Design:** Searches for executives matching user-configured `target_roles` (e.g. "Head of Growth", "VP Marketing", "Founder") at each candidate company, returning the individual's name, title, and personal LinkedIn profile URL (`linkedin.com/in/*`).
* **Current Status:**
  * **Built:** `lead_discovery_pipeline/tavily_enrichment.py` executes targeted LinkedIn queries via Tavily (`lookup_decision_maker`), extracts verified executive names and LinkedIn URLs, incorporates LLM validation/disambiguation, and provides heuristic fallbacks.

### Stage 4: NIM Processing (Brief & Scoring) — *Partially Built*
* **Intended Design:** Uses NVIDIA NIM LLMs for two distinct functions:
  1. **Company Brief:** Reads scraped web markdown and generates a concise 50–100 word summary covering what the company does, who it serves, and notable differentiators/traction signals — factual, no fluff, no repetitive naming.
  2. **ICP Scoring:** Evaluates the company against user-defined ICP criteria (pass/fail per rule), outputting a `fit_score` (0.0 to 1.0), `matched_criteria`, and `unmatched_criteria`. Only qualified companies proceed.
* **Current Status:**
  * **Built:** `score_company_icp` and `generate_company_brief` in `lead_discovery_pipeline/nim_classifier.py` dynamically evaluate ICP criteria and generate 50–100 word factual briefs grounded in scraped context.

### Stage 5: Output Generation — *Built*
* **Intended Design:** Compiles final records containing company name, domain, URL, brief, decision-maker details (name, title, LinkedIn URL), fit score, and matched/unmatched criteria into structured CSV and JSON files, strictly filtering to include only qualified leads.
* **Current Status:**
  * **Built:** `lead_discovery_pipeline/orchestrator.py` filters candidates by `is_qualified` and minimum score threshold, writing qualified results with `company_brief` to CSV and JSON.

---

## 3. Configuration & Secrets Management

All behavior must be driven by configuration files, never hardcoded in Python modules:

* **`config.yaml`**: The primary configuration file, divided into logical blocks:
  * `target_company`: Structured company targeting parameters (`industry`, `problem_solved`, `company_stage`, `customer_type`, and `raw_query`).
  * `discovery`: Execution controls (call caps, result counts, seed URLs).
  * `enrichment`: Scraping controls (timeout, max markdown characters, keywords).
  * `decision_maker`: Target titles list (`target_roles`) and search parameters.
  * `classification`: User-defined ICP criteria list and qualification score threshold (`min_fit_score`).
  * `filters`: Mechanical bounds (headcount range, allowed funding stages, country filters).
  * `storage`: Paths for database (`data/leads.sqlite3`), raw leads, and final CSV exports.
* **`.env` (templated by `.env.example`)**: API keys and environment variables:
  * `EXA_API_KEY` (or `EXA_API_KEY_1..3`)
  * `FIRECRAWL_API_KEY` (or `FIRECRAWL_API_KEY_1..3`)
  * `TAVILY_API_KEY`
  * `NVIDIA_API_KEY` (or `NIM_API_KEY`)
* **`lead_discovery_pipeline/config.py`**: Reads `config.yaml` and environment variables into typed dataclasses (`load_config()`).

---

## 4. Coding Conventions & Standards

* **Package Layout:** All source code lives under `lead_discovery_pipeline/`. Always use absolute imports:
  ```python
  from lead_discovery_pipeline.config import load_config
  from lead_discovery_pipeline.dedup_store import DedupStore
  ```
* **Python Standards:** Python 3.10+, `from __future__ import annotations`, dataclasses, and explicit type hints on all public interfaces.
* **Resilience & Key Rotation:** Network-facing modules must implement multi-key rotation (`KEY_1`, `KEY_2`, `KEY_3` fallback to `KEY`) and gracefully handle rate limits, timeouts, and quota exhaustion without crashing the pipeline.
* **User-Agent Header:** All outbound HTTP requests must use:
  ```
  User-Agent: LeadDiscoveryPipeline/1.0
  ```
* **Testing Pattern:** All test files reside in `tests/test_*.py`. Network calls in tests must be mocked (using `unittest.mock` or monkeypatching). No live API credits should be consumed during testing.

---

## 5. Verification Discipline

Before considering any change or PR complete:
1. Run the test suite:
   ```bash
   python -m pytest
   ```
   **All tests must pass with zero errors or failures.**
2. When introducing new functions or stages, write dedicated unit tests under `tests/`.

---

## 6. Strict Open-Source & Zero-Client-Data Rule

This is a generic open-source tool:
* **No hardcoded API keys or secrets:** Never put API tokens in source code or default parameters.
* **No client-identifying or company-specific data:** Never hardcode specific company names, client references, target URLs, or proprietary filter values into code.
* **All targeting and filtering logic must route through `config.yaml`:** Any user or engagement-specific criteria must be configured at runtime, keeping the codebase neutral and reusable.
* **No live run output in Git:** All CSVs, JSONs, and SQLite databases generated in `data/` or root are gitignored.
