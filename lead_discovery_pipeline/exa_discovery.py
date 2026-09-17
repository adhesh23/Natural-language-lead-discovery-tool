"""Exa semantic search and find-similar discovery module for the lead discovery pipeline."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests

from lead_discovery_pipeline.dedup_store import normalize_domain
from lead_discovery_pipeline.query_builder import build_exa_queries

_log = logging.getLogger("exa_discovery")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

EXA_SEARCH_URL = "https://api.exa.ai/search"
EXA_FIND_SIMILAR_URL = "https://api.exa.ai/findSimilar"
DEFAULT_CALL_CAP = 10
_DEFAULT_TIMEOUT = 25.0


class ExaRateGuard:
    """Explicit guardrail capping total Exa API calls per run."""

    def __init__(self, max_calls: int = DEFAULT_CALL_CAP) -> None:
        self.max_calls = max_calls
        self.calls_made = 0

    def record_call(self, endpoint_name: str) -> None:
        if self.calls_made >= self.max_calls:
            raise RuntimeError(
                f"Exa API call limit reached ({self.calls_made}/{self.max_calls}). "
                f"Halting immediately to protect rate/budget quota."
            )
        self.calls_made += 1
        _log.info(
            "Exa API call #%d / %d executed: %s",
            self.calls_made,
            self.max_calls,
            endpoint_name,
        )


@dataclass
class ExaClient:
    """Exa client with multi-key fallback across EXA_API_KEY_1..3 and EXA_API_KEY.
    
    Mirrors FirecrawlClient multi-key pattern:
    - Auto-discovers numbered keys EXA_API_KEY_1..3, falling back to EXA_API_KEY.
    - On failure (timeout, 401, 429, 5xx), automatically falls through to next key.
    - Retains active key index for subsequent requests.
    - If all keys fail, logs clearly and returns None without crashing the run.
    """

    api_keys: List[str] = field(default_factory=list)
    active_key_index: int = 0
    http_post: Optional[Callable[..., Any]] = None
    timeout: float = _DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.api_keys:
            discovered: List[str] = []
            for i in range(1, 10):
                k = os.getenv(f"EXA_API_KEY_{i}")
                if k and k.strip():
                    discovered.append(k.strip())
            if not discovered:
                single = os.getenv("EXA_API_KEY")
                if single and single.strip():
                    discovered.append(single.strip())
            
            # Fallback to checking Windows User registry if environment was not refreshed
            if not discovered:
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as env_key:
                        for i in range(1, 10):
                            try:
                                val, _ = winreg.QueryValueEx(env_key, f"EXA_API_KEY_{i}")
                                if val and str(val).strip():
                                    discovered.append(str(val).strip())
                            except FileNotFoundError:
                                pass
                        if not discovered:
                            try:
                                val, _ = winreg.QueryValueEx(env_key, "EXA_API_KEY")
                                if val and str(val).strip():
                                    discovered.append(str(val).strip())
                            except FileNotFoundError:
                                pass
                except Exception:
                    pass

            self.api_keys = discovered

    @property
    def has_keys(self) -> bool:
        return bool(self.api_keys)

    def get_active_key(self) -> Optional[str]:
        if 0 <= self.active_key_index < len(self.api_keys):
            return self.api_keys[self.active_key_index]
        return None

    def post(self, url: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Sends POST request to Exa with automatic key failover."""
        if not self.api_keys:
            _log.warning("[Exa] No API keys configured (checked EXA_API_KEY_1..3 and EXA_API_KEY).")
            return None

        total_keys = len(self.api_keys)
        endpoint_name = urlparse(url).path or url

        for _ in range(total_keys):
            key_idx = self.active_key_index % total_keys
            api_key = self.api_keys[key_idx]
            key_num = key_idx + 1

            headers = {
                "x-api-key": api_key,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            try:
                if self.http_post:
                    resp_data = self.http_post(url, payload, headers)
                    _log.info("[Exa] Request to %s succeeded using key #%d/%d", endpoint_name, key_num, total_keys)
                    return resp_data

                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                # Treat 401 (auth), 429 (rate/quota), and 5xx as failover triggers
                if resp.status_code in (401, 402, 403, 429) or resp.status_code >= 500:
                    raise requests.exceptions.HTTPError(
                        f"HTTP {resp.status_code}: {resp.text[:120]}", response=resp
                    )
                resp.raise_for_status()
                data = resp.json()
                _log.info("[Exa] Request to %s succeeded using key #%d/%d", endpoint_name, key_num, total_keys)
                return data

            except Exception as err:
                next_idx = key_idx + 1
                if next_idx < total_keys:
                    _log.warning(
                        "[Exa] Key #%d/%d failed (%s). Switching to fallback key #%d/%d.",
                        key_num, total_keys, err, next_idx + 1, total_keys,
                    )
                    self.active_key_index = next_idx
                    continue
                else:
                    _log.error(
                        "[Exa] Key #%d/%d failed (%s). All %d configured keys failed for %s. Skipping this discovery call.",
                        key_num, total_keys, err, total_keys, endpoint_name,
                    )
                    self.active_key_index = 0  # reset for future calls
                    return None

        return None


_DEFAULT_CLIENT = ExaClient()
_DEFAULT_GUARD = ExaRateGuard(DEFAULT_CALL_CAP)


def _format_exa_candidate(item: Dict[str, Any], discovery_source: str, query_or_seed: str) -> Dict[str, Any]:
    url = item.get("url") or ""
    domain = normalize_domain(url)
    title = (item.get("title") or "").strip()
    
    highlights = item.get("highlights")
    snippet = ""
    if isinstance(highlights, list) and highlights:
        snippet = " ".join(str(h).strip() for h in highlights if h)
    elif item.get("text"):
        snippet = str(item["text"])[:300].strip()
    elif item.get("summary"):
        snippet = str(item["summary"]).strip()

    return {
        "title": title,
        "url": url,
        "domain": domain,
        "snippet": snippet,
        "discovery_source": discovery_source,
        "discovery_meta": query_or_seed,
    }


def discover_by_query(
    query: str,
    num_results: int = 10,
    client: Optional[ExaClient] = None,
    guard: Optional[ExaRateGuard] = None,
) -> List[Dict[str, Any]]:
    """Calls Exa's search endpoint using ExaClient with multi-key fallback."""
    active_guard = guard or _DEFAULT_GUARD
    active_guard.record_call(f"search (query: '{query[:40]}...')")

    active_client = client or _DEFAULT_CLIENT
    payload = {
        "query": query,
        "numResults": num_results,
        "contents": {"highlights": True},
    }

    data = active_client.post(EXA_SEARCH_URL, payload)
    if not data:
        _log.warning("[Exa] discover_by_query received no response (all keys failed or unavailable).")
        return []

    candidates: List[Dict[str, Any]] = []
    for item in data.get("results", []):
        cand = _format_exa_candidate(item, discovery_source="exa_query", query_or_seed=query)
        if cand["domain"]:
            candidates.append(cand)
    return candidates


def discover_by_similar(
    seed_url: str,
    num_results: int = 10,
    client: Optional[ExaClient] = None,
    guard: Optional[ExaRateGuard] = None,
) -> List[Dict[str, Any]]:
    """Calls Exa's find-similar endpoint using ExaClient with multi-key fallback."""
    active_guard = guard or _DEFAULT_GUARD
    active_guard.record_call(f"findSimilar (seed: '{seed_url}')")

    active_client = client or _DEFAULT_CLIENT

    normalized_url = seed_url.strip()
    if not normalized_url.startswith("http://") and not normalized_url.startswith("https://"):
        normalized_url = f"https://{normalized_url}"

    payload = {
        "url": normalized_url,
        "numResults": num_results,
        "contents": {"highlights": True},
    }

    data = active_client.post(EXA_FIND_SIMILAR_URL, payload)
    if not data:
        _log.warning("[Exa] discover_by_similar received no response (all keys failed or unavailable).")
        return []

    seed_domain = normalize_domain(seed_url)
    candidates: List[Dict[str, Any]] = []
    for item in data.get("results", []):
        cand = _format_exa_candidate(item, discovery_source="exa_similar", query_or_seed=seed_url)
        if cand["domain"] and cand["domain"] != seed_domain:
            candidates.append(cand)
    return candidates


def run_discovery_pipeline(
    output_path: str = "data/raw_leads.json",
    cap: int = DEFAULT_CALL_CAP,
    client: Optional[ExaClient] = None,
    queries: Optional[List[str]] = None,
    seeds: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Runs query and find-similar discovery, dedupes by domain, and saves raw leads."""
    guard = ExaRateGuard(max_calls=cap)
    active_client = client or ExaClient()

    target_queries: List[str] = []
    if queries:
        target_queries.extend([q for q in queries if q])
    if config:
        for bq in build_exa_queries(config):
            if bq not in target_queries:
                target_queries.append(bq)

    target_seeds = seeds if seeds is not None else []

    if not target_queries and not target_seeds:
        raise ValueError(
            "No discovery queries or seed URLs provided. "
            "Configure 'target_company', 'discovery.queries', or 'discovery.seed_urls'."
        )

    _log.info("Starting Exa discovery run (Cap: %d calls, Keys: %d)...", cap, len(active_client.api_keys))
    for idx, s in enumerate(target_seeds, 1):
        _log.info("Configured Seed URL #%d: '%s'", idx, s)
    for idx, q in enumerate(target_queries, 1):
        _log.info("Configured Query #%d: '%s'", idx, q)
    
    all_raw_candidates: List[Dict[str, Any]] = []

    # 1. Query searches
    for q in target_queries:
        if guard.calls_made >= guard.max_calls:
            _log.warning("Call cap reached before executing query: %s", q)
            break
        _log.info("Executing Exa search with query: '%s'", q)
        q_results = discover_by_query(query=q, num_results=10, client=active_client, guard=guard)
        _log.info("discover_by_query returned %d items", len(q_results))
        all_raw_candidates.extend(q_results)

    # 2. Similar searches
    for s in target_seeds:
        if guard.calls_made >= guard.max_calls:
            _log.warning("Call cap reached before executing seed: %s", s)
            break
        _log.info("Executing Exa findSimilar with seed URL: '%s'", s)
        s_results = discover_by_similar(seed_url=s, num_results=10, client=active_client, guard=guard)
        _log.info("discover_by_similar ('%s') returned %d items", s, len(s_results))
        all_raw_candidates.extend(s_results)

    # Deduplicate by domain preserving order
    seen_domains = set()
    deduped_candidates: List[Dict[str, Any]] = []
    for item in all_raw_candidates:
        dom = item["domain"]
        if dom and dom not in seen_domains:
            seen_domains.add(dom)
            deduped_candidates.append(item)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(deduped_candidates, f, indent=2)

    _log.info(
        "Discovery complete. Saved %d deduped candidates to %s using %d Exa API calls.",
        len(deduped_candidates),
        output_path,
        guard.calls_made,
    )

    return {
        "calls_made": guard.calls_made,
        "max_calls": guard.max_calls,
        "candidates": deduped_candidates,
        "output_file": str(out_file),
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = run_discovery_pipeline()
    print(f"\n--- EXA DISCOVERY SUMMARY ---")
    print(f"Exa API calls used: {result['calls_made']} / {result['max_calls']}")
    print(f"Total deduped raw candidates: {len(result['candidates'])}")
    print(f"Output saved to: {result['output_file']}\n")
    for idx, c in enumerate(result["candidates"], 1):
        print(f"{idx}. [{c['domain']}] {c['title']}")
        print(f"   URL: {c['url']}")
        print(f"   Source: {c['discovery_source']}")
        snippet_clean = c['snippet'][:160].replace("\n", " ")
        print(f"   Snippet: {snippet_clean}...")
