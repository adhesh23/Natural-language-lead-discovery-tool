# Stage 4: NIM Processing (ICP Scoring & Brief)

## 1. Overview
Stage 4 processes scraped web markdown using NVIDIA NIM LLMs to evaluate candidate companies against user-defined Ideal Customer Profile (ICP) criteria and generate concise, factual company briefs.

## 2. Implementation Status
- **Built**:
  - `score_company_icp()` in `lead_discovery_pipeline/nim_classifier.py`: Evaluates candidates dynamically against an arbitrary list of criteria passed from `config.yaml`, returning `fit_score` (0.0 to 1.0), boolean `is_qualified`, `matched_criteria`, and `unmatched_criteria`.
  - `generate_company_brief()` in `lead_discovery_pipeline/nim_classifier.py`: Generates a concise 50–100 word factual brief grounded strictly in scraped context (what company does, who it serves, differentiators/traction) and returns `INSUFFICIENT_CONTEXT_FLAG` for thin/empty scrapes.
  - Multi-key rotation support (`NVIDIA_API_KEY_1..3`, `NVIDIA_API_KEY`, `NIM_API_KEY`).
  - Strict JSON schema enforcement and prompt isolation.
- **Pending**:
  - None. Stage 4 is fully built.

## 3. Configuration Keys
Controlled under `config.yaml`:
```yaml
classification:
  enabled: true                                      # Enable or bypass LLM classification
  model: "meta/llama-3.2-11b-vision-instruct"        # NIM model identifier
  temperature: 0.0                                   # Deterministic output
  icp_criteria:                                      # Dynamic list of ICP criteria
    - "Company provides a B2B SaaS or technology platform"
    - "Company is an early-to-mid stage growth company (roughly 10-150 headcount)"
    - "Demonstrated commercial traction or institutional funding"
    - "Has workflow, API, or automated capabilities in product"
  min_fit_score: 0.7                                 # Minimum fit score threshold for qualification
```

## 4. Key Functions and Classes
- `score_company_icp(company_name, company_url, web_content, icp_criteria, min_fit_score, api_key)`: Sends prompt with criteria checklist to NVIDIA NIM API, parses the structured JSON response, computes fit score, and flags qualification.
- `generate_company_brief(company_name, company_context, api_key, model, temperature)`: Generates a 50–100 word factual summary grounded strictly in web context. Context below 60 characters immediately returns `INSUFFICIENT_CONTEXT_FLAG` ("Insufficient web context to generate factual brief.") without making an LLM API call.
- `_clean_json_response(raw_text)`: Strips markdown fences and extracts valid JSON objects from LLM outputs.

## 5. Failure Modes Handled
- **Thin / Missing Content**: Immediately detects context under 60 characters and returns `INSUFFICIENT_CONTEXT_FLAG` without making costly LLM calls or hallucinating facts.
- **JSON Parsing Errors**: Robust extraction handles markdown fences (````json ... ````) and cleans trailing characters. If parsing fails, logs warning and returns a zero score rather than crashing.
- **API Limits & Timeouts**: Retries or key rotation on network/quota errors; pipeline safely skips unscoreable records without losing previously processed items.
