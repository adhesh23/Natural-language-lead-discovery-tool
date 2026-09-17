"""Tavily search enrichment and decision-maker lookup module with rate limiting and LLM verification."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

from lead_discovery_pipeline.nim_classifier import (
    DEFAULT_MODEL,
    DEFAULT_NIM_KEY,
    NIM_API_URL,
)
from lead_discovery_pipeline.rate_limits import DailyRequestCounter

_log = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"
DEFAULT_TAVILY_KEY = ""
TAVILY_DAILY_CAP = 100

NON_COMPANY_HOSTS = {
    "ycombinator.com",
    "www.ycombinator.com",
    "linkedin.com",
    "www.linkedin.com",
    "twitter.com",
    "x.com",
    "github.com",
    "crunchbase.com",
    "www.crunchbase.com",
    "producthunt.com",
    "www.producthunt.com",
    "facebook.com",
    "youtube.com",
    "medium.com",
    "substack.com",
    "pitchbook.com",
    "techcrunch.com",
    "news.ycombinator.com",
}


@dataclass
class DecisionMakerResult:
    name: str = ""
    title: str = ""
    linkedin_url: str = ""
    confidence: str = "none"
    reasoning: str = ""


@dataclass
class CompanyEnrichmentResult:
    company_name: str
    description: str = ""
    website: str | None = None
    domain: str | None = None
    linkedin_url: str | None = None
    founder_info: str | None = None
    confidence: str = "low"
    reasoning: str = ""
    decision_makers: List[DecisionMakerResult] = field(default_factory=list)


def tavily_search(
    query: str,
    *,
    api_key: str | None = None,
    max_results: int = 5,
    search_depth: str = "basic",
    timeout: float = 15.0,
    counter: DailyRequestCounter | None = None,
) -> list[dict[str, Any]]:
    """Execute a search query via Tavily with rate limit protection."""
    key = api_key or os.getenv("TAVILY_API_KEY") or DEFAULT_TAVILY_KEY
    if not key:
        _log.error("No Tavily API key available (set TAVILY_API_KEY)")
        return []

    if counter and not counter.try_acquire("tavily", TAVILY_DAILY_CAP):
        _log.warning("Tavily daily rate limit reached (%d queries)", TAVILY_DAILY_CAP)
        return []

    payload = {
        "api_key": key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }

    req = urllib.request.Request(
        TAVILY_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "LeadDiscoveryPipeline/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except Exception as e:
        _log.error("Tavily search error for query %r: %s", query, e)
        return []


def lookup_decision_maker(
    company_name: str,
    target_roles: List[str],
    *,
    company_domain: str = "",
    tavily_key: str | None = None,
    nim_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_results: int = 5,
    counter: DailyRequestCounter | None = None,
) -> DecisionMakerResult:
    """Find a decision-maker matching configured target roles for a target company."""
    roles_formatted = " OR ".join(f'"{r}"' if " " in r else r for r in target_roles)
    query = f'site:linkedin.com/in/ "{company_name}" ({roles_formatted})'
    
    hits = tavily_search(
        query,
        api_key=tavily_key,
        max_results=max_results,
        counter=counter,
    )
    if not hits:
        # Fallback broader query
        broad_query = f'"{company_name}" ({roles_formatted}) LinkedIn'
        hits = tavily_search(
            broad_query,
            api_key=tavily_key,
            max_results=max_results,
            counter=counter,
        )

    if not hits:
        return DecisionMakerResult(confidence="none", reasoning="No candidate search hits returned")

    results_text = ""
    for i, h in enumerate(hits[:5], 1):
        results_text += (
            f"Result #{i}:\n"
            f"Title: {h.get('title', '')}\n"
            f"URL: {h.get('url', '')}\n"
            f"Snippet: {h.get('content', '')[:350]}\n\n"
        )

    target_roles_str = ", ".join(target_roles)
    system_prompt = (
        "You are an executive research agent identifying target decision-makers at companies.\n"
        f"Target Company: '{company_name}' (Domain: '{company_domain}')\n"
        f"Target Roles of Interest: {target_roles_str}\n\n"
        "STRICT DISAMBIGUATION RULES:\n"
        "1. Identify a person who genuinely works at this specific company in one of the target roles.\n"
        "2. Extract their direct personal LinkedIn profile URL (must contain linkedin.com/in/).\n"
        "3. If no person matching the criteria is found with high confidence, return null values. Do not hallucinate.\n\n"
        "Respond ONLY with a single valid JSON object:\n"
        "{\n"
        '  "name": string or null,\n'
        '  "title": string or null,\n'
        '  "linkedin_url": string or null,\n'
        '  "confidence": "high" | "medium" | "low" | "none",\n'
        '  "reasoning": string\n'
        "}"
    )

    user_prompt = f"Search Results:\n{results_text}"
    key = nim_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY") or DEFAULT_NIM_KEY

    if not key:
        # Heuristic fallback without LLM
        for h in hits:
            u = h.get("url", "")
            if "linkedin.com/in/" in u:
                return DecisionMakerResult(
                    name=h.get("title", "").split("-")[0].strip(),
                    title=target_roles[0] if target_roles else "",
                    linkedin_url=u.split("?")[0].rstrip("/"),
                    confidence="medium",
                    reasoning="Heuristic fallback extraction",
                )
        return DecisionMakerResult(confidence="none", reasoning="No NIM key and no profile found")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 250,
    }

    req = urllib.request.Request(
        NIM_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)

            li = parsed.get("linkedin_url") or ""
            if "linkedin.com/in/" not in li.lower():
                li = ""

            return DecisionMakerResult(
                name=str(parsed.get("name") or "").strip(),
                title=str(parsed.get("title") or "").strip(),
                linkedin_url=li.split("?")[0].rstrip("/") if li else "",
                confidence=str(parsed.get("confidence") or "low"),
                reasoning=str(parsed.get("reasoning") or ""),
            )
    except Exception as e:
        _log.warning("LLM decision-maker extraction error for %s: %s", company_name, e)
        return DecisionMakerResult(confidence="error", reasoning=str(e))


def verify_and_extract_with_llm(
    company_name: str,
    description: str,
    search_results: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> CompanyEnrichmentResult:
    """Extract official website, LinkedIn page, and leadership using LLM."""
    if not search_results:
        return CompanyEnrichmentResult(
            company_name=company_name,
            description=description,
            confidence="low",
            reasoning="No search results returned by Tavily",
        )

    formatted_results = []
    for i, r in enumerate(search_results, 1):
        formatted_results.append(
            f"[{i}] Title: {r.get('title', '')}\n"
            f"    URL: {r.get('url', '')}\n"
            f"    Snippet: {r.get('content', '')[:300]}"
        )
    results_text = "\n\n".join(formatted_results)

    system_prompt = (
        "You are an expert tech startup researcher.\n"
        "Given a target company's name and description, analyze the candidate web search results "
        "and determine the authentic company website, official LinkedIn company page, and founder(s) or leaders.\n\n"
        "Rules:\n"
        "1. Disambiguation: Ensure the result matches the specific company matching the description.\n"
        "2. Website: Must be the company's actual product/corporate domain. Never return aggregators.\n"
        "3. LinkedIn: Must be the company's official LinkedIn company page if present.\n"
        "4. Founders: Any founder or leadership names and personal profile URLs mentioned.\n"
        "5. Confidence: 'high', 'medium', or 'low'.\n\n"
        "Respond ONLY with a single JSON object with these keys:\n"
        "{\n"
        '  "website": string or null,\n'
        '  "domain": string or null,\n'
        '  "linkedin_url": string or null,\n'
        '  "founders": string or null,\n'
        '  "confidence": "high" | "medium" | "low",\n'
        '  "reasoning": string\n'
        "}"
    )

    user_content = (
        f"Target Company: {company_name}\n"
        f"Description: {description}\n\n"
        f"Candidate Search Results:\n{results_text}"
    )

    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY") or DEFAULT_NIM_KEY
    if not key:
        return _fallback_rule_extraction(company_name, description, search_results)

    body = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 300,
    }

    req = urllib.request.Request(
        NIM_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)

            return CompanyEnrichmentResult(
                company_name=company_name,
                description=description,
                website=parsed.get("website"),
                domain=parsed.get("domain"),
                linkedin_url=parsed.get("linkedin_url"),
                founder_info=parsed.get("founders"),
                confidence=parsed.get("confidence", "low"),
                reasoning=parsed.get("reasoning", ""),
            )
    except Exception as e:
        _log.warning("LLM verification failed for %s: %s", company_name, e)
        return _fallback_rule_extraction(company_name, description, search_results)


def _fallback_rule_extraction(
    company_name: str,
    description: str,
    search_results: list[dict[str, Any]],
) -> CompanyEnrichmentResult:
    """Fallback heuristic extraction if NIM LLM is unavailable or times out."""
    website = None
    domain = None
    linkedin_url = None
    founder_info = None

    for r in search_results:
        url = r.get("url", "")
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]

        if "linkedin.com/company/" in url and not linkedin_url:
            linkedin_url = url
        elif "linkedin.com/in/" in url and not founder_info:
            founder_info = f"{r.get('title', '')} ({url})"
        elif host not in NON_COMPANY_HOSTS and not website:
            website = f"{parsed.scheme}://{parsed.netloc}"
            domain = host

    confidence = "medium" if (website and linkedin_url) else ("low" if not website else "medium")
    return CompanyEnrichmentResult(
        company_name=company_name,
        description=description,
        website=website,
        domain=domain,
        linkedin_url=linkedin_url,
        founder_info=founder_info,
        confidence=confidence,
        reasoning="Extracted via heuristic fallback",
    )


def enrich_company(
    company_name: str,
    description: str = "",
    *,
    tavily_key: str | None = None,
    counter: DailyRequestCounter | None = None,
) -> CompanyEnrichmentResult:
    """Run Tavily search + verification for a single company."""
    query = f"{company_name} {description}".strip()
    results = tavily_search(query, api_key=tavily_key, counter=counter)

    if not results or len(results) < 2:
        secondary_query = f"{company_name} official website company linkedin"
        more_results = tavily_search(secondary_query, api_key=tavily_key, counter=counter)
        results.extend(more_results)

    return verify_and_extract_with_llm(company_name, description, results)
