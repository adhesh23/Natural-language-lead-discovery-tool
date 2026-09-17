# Stage 1: Discovery (Exa Semantic Search & Lookalikes)

## 1. Overview
The Discovery stage discovers candidate companies matching the configured target company profile using Exa's neural search and find-similar lookalike capability. Queries are templated dynamically from structured targeting parameters in `config.yaml` (`target_company`), overridden via `raw_query`, or supplemented with explicit discovery queries and seed URLs.

## 2. Implementation Status
- **Built**:
  - `lead_discovery_pipeline/query_builder.py`: Implements `build_exa_query(config)` and `build_exa_queries(config)` to template `industry`, `problem_solved`, `company_stage`, and `customer_type` into natural language, with support for `raw_query` override and partial parameters.
  - `lead_discovery_pipeline/exa_discovery.py`: Full API client (`ExaClient`) supporting multi-key rotation (`EXA_API_KEY_1..3` falling back to `EXA_API_KEY`), error handling, rate/call budget guard (`ExaRateGuard`), and domain deduplication.
  - Integration: `orchestrator.py` passes `config` to `run_discovery_pipeline()`.
- **Pending**:
  - None. Stage 1 is fully built.

## 3. Configuration Keys
Controlled under `config.yaml`:
```yaml
target_company:
  industry: ""              # e.g. "vertical SaaS"
  problem_solved: ""        # e.g. "manages field service and claims processing operations"
  company_stage: ""         # e.g. "early-stage, funded"
  customer_type: ""         # e.g. "B2B enterprise"
  raw_query: ""             # Optional direct override string

discovery:
  enabled: true             # Toggle discovery stage
  call_cap: 10              # Hard ceiling on total Exa API requests
  num_results_per_query: 10 # Results requested per search call
  queries: []               # Supplementary query strings
  seed_urls: []             # Seed URLs for Exa findSimilar lookalike search
```

## 4. Key Functions and Classes
- `build_exa_query(config: dict) -> str`: Templates the 4 targeting attributes into a natural-language search query, handles `raw_query` override, or raises `ValueError` if criteria are empty.
- `build_exa_queries(config: dict) -> list[str]`: Aggregates templated target queries and explicit `discovery.queries`.
- `ExaClient`: Manages HTTP requests to Exa API (`/search` and `/findSimilar`), auto-discovers keys, and rotates on 401/429 failures.
- `ExaRateGuard`: Enforces `call_cap`, terminating discovery calls if budget is exhausted.
- `discover_by_query(query, num_results, client, guard)`: Executes neural search and standardizes candidate records.
- `discover_by_similar(seed_url, num_results, client, guard)`: Executes lookalike search and excludes self-referential seed domains.
- `run_discovery_pipeline(output_path, cap, client, queries, seeds, config)`: Orchestrates search calls, dedupes candidates by domain, and writes `raw_leads.json`.

## 5. Failure Modes & Validation
- **Broadened Query/Seed Requirement**: Discovery requires at least one query (templated or explicit) OR at least one seed URL. Having either satisfies the requirement; `run_discovery_pipeline()` raises `ValueError` only if both `target_queries` and `target_seeds` are empty.
- **Quota & Key Failures**: If an API key encounters 401 (auth failure) or 429 (quota exhaustion), `ExaClient` automatically fails over to the next numbered key. If all keys fail, it returns an empty list without crashing.
- **Budget Exceeded**: `ExaRateGuard` raises `RuntimeError` before outbound calls exceed `call_cap`.
- **Domain Deduplication**: Duplicates across search queries and seed results are stripped by domain name while preserving discovery order.
