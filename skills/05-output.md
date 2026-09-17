# Stage 5: Output Generation

## 1. Overview
Stage 5 aggregates, filters, and formats processed leads into final deliverables. Only candidates meeting or exceeding the qualification threshold (`is_qualified=True` and `fit_score >= min_fit_score`) are exported. Results are serialized to CSV and JSON formats at user-configured paths.

## 2. Implementation Status
- **Built**:
  - `lead_discovery_pipeline/orchestrator.py`: Filters qualified leads, triggers `generate_company_brief` for qualified candidates, maps candidate data to tabular columns including `company_brief`, and exports CSV and JSON files.
  - Dedup storage support (`lead_discovery_pipeline/dedup_store.py`).
- **Pending**:
  - None. Stage 5 is fully built.

## 3. Configuration Keys
Controlled under `config.yaml`:
```yaml
storage:
  database_path: "data/leads.sqlite3"          # SQLite database path for persistent deduplication
  raw_leads_path: "data/raw_leads.json"        # Intermediate discovery results
  enriched_leads_path: "data/enriched_leads.json" # Scraped content store
  final_output_csv: "data/qualified_leads.csv" # Final exported shortlist CSV
```

## 4. Key Functions and Classes
- `execute_pipeline(config_path)`: High-level orchestration function coordinating Stages 1 through 5, aggregating metrics, and triggering output file generation.
- `write_csv_output(records, output_path)`: Writes qualified leads with headers to CSV.
- `DedupStore`: SQLite-backed domain tracking ensuring leads across repeated runs are deduplicated.

## 5. Output Schema
Final output CSV columns:
| Column | Description |
|---|---|
| `company_name` | Name of the discovered company |
| `domain` | Normalized web domain |
| `url` | Company URL |
| `company_brief` | Concise 50–100 word factual company summary |
| `decision_maker_name` | Full name of identified executive |
| `decision_maker_title` | Title of identified executive |
| `decision_maker_linkedin` | Verified personal LinkedIn profile URL (`linkedin.com/in/*`) |
| `fit_score` | ICP fit score between 0.0 and 1.0 |
| `is_qualified` | Boolean indicator whether threshold was met |
| `matched_criteria` | Semicolon-separated list of satisfied ICP rules |
| `unmatched_criteria` | Semicolon-separated list of unmet ICP rules |
| `reasoning` | LLM justification for score and qualification |
