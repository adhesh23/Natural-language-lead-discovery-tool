# Stage 3: Decision-Maker Lookup (Tavily)

## 1. Overview
Stage 3 identifies executive decision-makers matching configured target roles (e.g. Founder, CEO, VP Marketing, Head of Growth) at candidate companies. It executes targeted queries through the Tavily Search API constrained to personal LinkedIn profiles (`site:linkedin.com/in/`), extracting verified executive names, titles, and profile links.

## 2. Implementation Status
- **Built**:
  - `lead_discovery_pipeline/tavily_enrichment.py`: Search execution and executive extraction.
  - Multi-key rotation support (`TAVILY_API_KEY_1..3` falling back to `TAVILY_API_KEY`).
  - LinkedIn profile URL extraction and validation (`extract_linkedin_profile_url`).
  - Decision-maker name and title extraction with regex heuristics (`extract_person_from_title`).
  - LLM-assisted validation fallback for ambiguous title matches.
- **Pending**:
  - None. Stage 3 is fully built.

## 3. Configuration Keys
Controlled under `config.yaml`:
```yaml
decision_maker:
  enabled: true             # Enable or disable decision-maker lookup
  target_roles:             # List of target titles/roles searched per company
    - "Head of Growth"
    - "VP of Marketing"
    - "Founder"
    - "CEO"
  max_search_results: 5     # Number of Tavily search results to fetch
  search_depth: "basic"     # Search depth ("basic" or "advanced")
```

## 4. Key Functions and Classes
- `lookup_decision_maker(company_name, company_url, target_roles, api_key, ...)`: Queries Tavily with LinkedIn-targeted operators for candidate executives and parses response items.
- `extract_linkedin_profile_url(results)`: Filters search results for valid `linkedin.com/in/*` profile links, excluding company directory pages and pulse posts.
- `extract_person_from_title(search_title, company_name)`: Uses heuristic parsing to split snippet and title headers into person name and job title.
- `disambiguate_with_llm(...)`: Optional LLM verification pass if heuristic extraction has low confidence or multiple competing profiles exist.

## 5. Failure Modes Handled
- **No Profile Found**: Returns empty fields with `confidence: "none"` without failing the pipeline run.
- **Ambiguous Titles / Directory Pages**: Enforces regex validation to ensure URLs match personal member patterns (`/in/[username]`) and ignores general company or job pages (`/company/`, `/jobs/`).
- **Network / API Key Quotas**: Rotates through available keys and fails gracefully to empty identification if Tavily is unreachable.
