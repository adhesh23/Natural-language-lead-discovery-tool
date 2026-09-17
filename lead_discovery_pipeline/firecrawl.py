"""Firecrawl client with multi-key fallback and generic website content enrichment."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger(__name__)

FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"
_DEFAULT_TIMEOUT = 30.0


class FirecrawlError(Exception):
    """Base exception for Firecrawl API errors."""


class FirecrawlCreditsExhaustedError(FirecrawlError):
    """Raised when all available Firecrawl API keys have exhausted their credits."""


@dataclass
class FirecrawlClient:
    """Firecrawl client with multi-key credit fallback.

    Accepts an explicit list of API keys or auto-discovers them from environment:
    FIRECRAWL_API_KEY_1, FIRECRAWL_API_KEY_2, FIRECRAWL_API_KEY_3,
    falling back to FIRECRAWL_API_KEY if specific numbered keys are not set.
    """

    api_keys: list[str] = field(default_factory=list)
    active_key_index: int = 0
    http_fetch: Callable[..., Any] | None = None
    timeout: float = _DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.api_keys:
            discovered: list[str] = []
            for i in range(1, 10):
                k = os.getenv(f"FIRECRAWL_API_KEY_{i}")
                if k and k.strip():
                    discovered.append(k.strip())
            if not discovered:
                single = os.getenv("FIRECRAWL_API_KEY")
                if single and single.strip():
                    discovered.append(single.strip())
            self.api_keys = discovered

    @property
    def has_keys(self) -> bool:
        return bool(self.api_keys)

    def get_active_key(self) -> str | None:
        if 0 <= self.active_key_index < len(self.api_keys):
            return self.api_keys[self.active_key_index]
        return None

    def _is_credits_or_rate_limit_error(self, status_code: int, response_body: str) -> bool:
        """Determine if an HTTP response represents exhausted credits or quota limit."""
        if status_code in (402, 429):
            return True
        body_lower = response_body.lower()
        exhausted_keywords = (
            "insufficient credits",
            "credits exhausted",
            "payment required",
            "out of credits",
            "quota exceeded",
            "rate limit",
            "plan limit",
            "upgrade your plan",
        )
        return any(k in body_lower for k in exhausted_keywords)

    def scrape(
        self,
        url: str,
        *,
        formats: list[str] | None = None,
        only_main_content: bool = True,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Scrape a URL using Firecrawl with automatic fallback to secondary keys."""
        if not self.api_keys:
            _log.warning("[Firecrawl] No API keys configured (checked FIRECRAWL_API_KEY_1..3 and FIRECRAWL_API_KEY).")
            return {"success": False, "error": "No Firecrawl API keys configured"}

        formats = formats or ["markdown"]
        payload = {
            "url": url,
            "formats": formats,
            "onlyMainContent": only_main_content,
        }
        if extra_payload:
            payload.update(extra_payload)

        req_bytes = json.dumps(payload).encode("utf-8")
        scrape_url = f"{FIRECRAWL_BASE_URL}/scrape"

        total_keys = len(self.api_keys)
        for attempts_made in range(total_keys):
            key_idx = (self.active_key_index) % total_keys
            api_key = self.api_keys[key_idx]
            key_num = key_idx + 1

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "LeadDiscoveryPipeline/1.0",
            }

            try:
                if self.http_fetch:
                    resp_data = self.http_fetch(scrape_url, payload, headers)
                    _log.info("[Firecrawl] Scrape succeeded for %s using key #%d/%d", url, key_num, total_keys)
                    return resp_data

                req = urllib.request.Request(scrape_url, data=req_bytes, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    data = json.loads(resp_bytes.decode("utf-8"))
                    _log.info("[Firecrawl] Scrape succeeded for %s using key #%d/%d", url, key_num, total_keys)
                    return data

            except urllib.error.HTTPError as err:
                status_code = err.code
                err_body = ""
                try:
                    err_body = err.read().decode("utf-8")
                except Exception:
                    pass

                if self._is_credits_or_rate_limit_error(status_code, err_body):
                    next_idx = key_idx + 1
                    if next_idx < total_keys:
                        _log.warning(
                            "[Firecrawl] Key #%d/%d exhausted credits or rate-limited (HTTP %d: %s). "
                            "Switching to fallback key #%d/%d.",
                            key_num, total_keys, status_code, err_body[:100], next_idx + 1, total_keys
                        )
                        self.active_key_index = next_idx
                        continue
                    else:
                        _log.error(
                            "[Firecrawl] Key #%d/%d exhausted credits (HTTP %d). All %d configured keys are exhausted.",
                            key_num, total_keys, status_code, total_keys
                        )
                        self.active_key_index = 0
                        return {
                            "success": False,
                            "error": f"All {total_keys} Firecrawl keys exhausted credits: HTTP {status_code}",
                        }
                else:
                    _log.error("[Firecrawl] HTTP %d scraping %s with key #%d: %s", status_code, url, key_num, err_body[:120])
                    return {"success": False, "error": f"HTTP {status_code}: {err_body[:120]}"}

            except Exception as e:
                _log.error("[Firecrawl] Exception scraping %s with key #%d: %s", url, key_num, e)
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"All {total_keys} Firecrawl keys failed"}


def find_about_page_url(
    base_url: str,
    homepage_markdown: str,
    keywords: Optional[List[str]] = None,
) -> str:
    """Find an about/team link dynamically from homepage markdown or construct fallback."""
    search_keywords = [k.lower() for k in (keywords or ["about", "team", "leadership", "company", "who-we-are"])]
    clean_base = base_url.rstrip("/")
    matches = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', homepage_markdown)
    for text, href in matches:
        t_low = text.lower()
        h_low = href.lower()
        if any(k in t_low or k in h_low for k in search_keywords):
            if href.startswith("http"):
                return href
            elif href.startswith("/"):
                parsed = urllib.parse.urlparse(base_url)
                return f"{parsed.scheme}://{parsed.netloc}{href}"
    return f"{clean_base}/about"


def enrich_company_content(
    company_url: str,
    client: Optional[FirecrawlClient] = None,
    *,
    scrape_about: bool = True,
    about_keywords: Optional[List[str]] = None,
    max_length: int = 15000,
) -> Dict[str, Any]:
    """Generic company web content scraper returning homepage and about/team text."""
    firecrawl = client or FirecrawlClient()
    result = {
        "url": company_url,
        "homepage_scraped": False,
        "homepage_content": "",
        "about_url": "",
        "about_scraped": False,
        "about_content": "",
        "combined_content": "",
    }

    hp_res = firecrawl.scrape(company_url, formats=["markdown"])
    if hp_res.get("success"):
        hp_md = hp_res.get("data", {}).get("markdown", "")
        result["homepage_scraped"] = bool(hp_md)
        result["homepage_content"] = hp_md[:max_length]
    else:
        return result

    if scrape_about:
        about_url = find_about_page_url(company_url, result["homepage_content"], keywords=about_keywords)
        result["about_url"] = about_url
        about_res = firecrawl.scrape(about_url, formats=["markdown"])
        if about_res.get("success"):
            about_md = about_res.get("data", {}).get("markdown", "")
            result["about_scraped"] = bool(about_md)
            result["about_content"] = about_md[:max_length]

    result["combined_content"] = (
        f"{result['homepage_content']}\n\n{result['about_content']}"
    ).strip()[:max_length * 2]
    return result
