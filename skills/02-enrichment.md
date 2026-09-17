# Stage 2: Web Enrichment (Firecrawl)

## 1. Overview
Stage 2 enriches discovered companies with public website context by scraping clean markdown from candidate homepages and secondary `/about`, `/team`, or `/company` pages using the Firecrawl API. Only public-facing information is scraped; no private or authenticated resources are accessed.

## 2. Implementation Status
- **Built**:
  - `lead_discovery_pipeline/firecrawl.py`: Complete Firecrawl scraping integration.
  - Multi-key credit exhaustion rotation (`FIRECRAWL_API_KEY_1..3` falling back to `FIRECRAWL_API_KEY`).
  - Automated about/team page URL discovery via regex and markdown parsing (`find_about_page_url`).
  - Combined markdown scraping and truncation (`enrich_company_content`).
- **Pending**:
  - None. Stage 2 is fully built.

## 3. Configuration Keys
Controlled under `config.yaml`:
```yaml
enrichment:
  enabled: true                 # Enable or bypass web scraping
  timeout_seconds: 30.0         # HTTP request timeout per page
  max_content_length: 15000     # Maximum characters of markdown retained
  scrape_about_page: true       # Whether to discover and scrape an about/team page
  about_path_keywords:          # Keywords used to match subpage links
    - "about"
    - "team"
    - "leadership"
    - "company"
```

## 4. Key Functions and Classes
- `FirecrawlClient`: Manages requests to `https://api.firecrawl.dev/v1/scrape`, automatically rotating keys on 402/429/auth failures.
- `find_about_page_url(base_url, markdown)`: Scans markdown content for links matching keywords like `/about`, `/team`, or `/leadership` and resolves them against the base domain.
- `enrich_company_content(url, client, scrape_about, about_keywords, max_length)`: Fetches homepage content, identifies and scrapes relevant secondary pages if enabled, combines markdown, and truncates to `max_content_length`.

## 5. Failure Modes Handled
- **Quota / Rate Limits**: Automatically cycles through configured API keys when HTTP 402 (payment/credit required) or 429 (rate limit) is returned.
- **Scrape Failures & Timeouts**: If a company website fails to scrape or times out, the pipeline logs a warning and falls back to the discovery search snippet rather than halting execution.
- **Large Payloads**: Content is truncated to `max_content_length` to prevent context overflow in downstream LLM processing.
