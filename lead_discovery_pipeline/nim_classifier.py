"""NVIDIA NIM LLM classification and ICP scoring module."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from typing import Any, List, Optional

NIM_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "meta/llama-3.2-11b-vision-instruct"
DEFAULT_NIM_KEY = ""

DEFAULT_SYSTEM_PROMPT = """You are an expert venture capital analyst classifying news articles for startup funding events.
Analyze the provided news article title and snippet, and determine if it represents a genuine early-stage venture funding round.

You must respond ONLY with a single valid JSON object with the following keys:
- "is_funding_event": boolean (true ONLY if a specific startup or private company raised investment capital/funding round; false for M&A, earnings reports, public market movements, layoffs, government funding, general market commentary, or mega-corps)
- "company_name": string (the exact company name that raised the money, or null if not a funding event)
- "estimated_stage": string (e.g., "seed", "Series A", "Series B", "later-stage-or-unclear")
- "likely_b2b_saas": boolean (true if the company provides software/tech services to businesses/enterprises; false if consumer-facing, B2C, crypto token, hardware only, or biotech/pharma non-software)
- "reasoning": string (brief 1-sentence explanation of your classification)

Do not include any markdown fences or commentary outside the JSON object."""


def classify_funding_article_nim(
    title: str,
    snippet: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout: float = 15.0,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> dict[str, Any]:
    """Classify a news article using NVIDIA NIM LLM."""
    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY") or DEFAULT_NIM_KEY
    if not key:
        return {
            "is_funding_event": False,
            "company_name": None,
            "estimated_stage": "later-stage-or-unclear",
            "likely_b2b_saas": False,
            "reasoning": "No NVIDIA NIM API key available",
            "passed": False,
        }

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Title: {title}\nSnippet: {snippet}"},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        NIM_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)
    except Exception as e:
        return {
            "is_funding_event": False,
            "company_name": None,
            "estimated_stage": "later-stage-or-unclear",
            "likely_b2b_saas": False,
            "reasoning": f"NIM call failed: {e}",
            "passed": False,
        }

    is_funding = bool(parsed.get("is_funding_event"))
    stage = str(parsed.get("estimated_stage") or "").strip()
    is_b2b = bool(parsed.get("likely_b2b_saas"))
    company = parsed.get("company_name")
    stage_valid = stage.lower() in ("seed", "series a", "series b", "pre-seed")

    passed = is_funding and stage_valid and is_b2b and bool(company)

    return {
        "is_funding_event": is_funding,
        "company_name": company,
        "estimated_stage": stage,
        "likely_b2b_saas": is_b2b,
        "reasoning": parsed.get("reasoning", ""),
        "passed": passed,
    }


def score_company_icp(
    company_name: str,
    company_context: str,
    icp_criteria: List[str],
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """Score and classify a candidate company against arbitrary user-defined ICP criteria."""
    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY") or DEFAULT_NIM_KEY
    if not key:
        return {
            "fit_score": 0.0,
            "is_qualified": False,
            "matched_criteria": [],
            "unmatched_criteria": list(icp_criteria),
            "reasoning": "No NVIDIA NIM API key available",
        }

    criteria_list_str = "\n".join(f"{i+1}. {c}" for i, c in enumerate(icp_criteria))
    system_prompt = (
        "You are an expert market research analyst evaluating company alignment against ideal customer profile (ICP) criteria.\n"
        "Evaluate the target company against the following specific criteria:\n\n"
        f"{criteria_list_str}\n\n"
        "STRICT OUTPUT INSTRUCTIONS:\n"
        "Respond ONLY with a single valid JSON object with the following keys:\n"
        '- "fit_score": float between 0.0 and 1.0 representing overall fit\n'
        '- "is_qualified": boolean (true if fit_score >= 0.7 and critical criteria are met)\n'
        '- "matched_criteria": list of strings matching the numbered criteria that the company satisfies\n'
        '- "unmatched_criteria": list of strings for criteria that were NOT met or had insufficient evidence\n'
        '- "reasoning": concise 1-2 sentence explanation of the score and assessment\n\n'
        "Do not include any markdown fences or explanation outside the JSON object."
    )

    user_prompt = (
        f"Target Company: {company_name}\n\n"
        f"Company Web Content & Context:\n{company_context[:10000]}"
    )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 400,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        NIM_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)

            return {
                "fit_score": float(parsed.get("fit_score", 0.0)),
                "is_qualified": bool(parsed.get("is_qualified", False)),
                "matched_criteria": list(parsed.get("matched_criteria", [])),
                "unmatched_criteria": list(parsed.get("unmatched_criteria", [])),
                "reasoning": str(parsed.get("reasoning", "")),
            }
    except Exception as e:
        return {
            "fit_score": 0.0,
            "is_qualified": False,
            "matched_criteria": [],
            "unmatched_criteria": list(icp_criteria),
            "reasoning": f"NIM scoring error: {e}",
        }


INSUFFICIENT_CONTEXT_FLAG = "Insufficient web context to generate factual brief."


def generate_company_brief(
    company_name: str,
    company_context: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    timeout: float = 25.0,
) -> str:
    """Generate a concise, factual 50-100 word company brief grounded strictly in web context."""
    if not company_context or len(company_context.strip()) < 60:
        return INSUFFICIENT_CONTEXT_FLAG

    key = api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY") or DEFAULT_NIM_KEY
    if not key:
        return "No NVIDIA NIM API key available"

    system_prompt = (
        "You are an expert research analyst writing a concise, objective company brief.\n"
        "Write a factual 50-100 word summary covering:\n"
        "1. What the company does (core product or platform capabilities)\n"
        "2. Who it serves (target customer profile or industry)\n"
        "3. Notable differentiators, workflow integrations, or traction signals mentioned in the context.\n\n"
        "STRICT REQUIREMENTS:\n"
        "- The output must be roughly 50 to 100 words in length.\n"
        "- Ground all statements strictly in the provided context. Do NOT invent or extrapolate funding, headcount, or metrics.\n"
        "- Return ONLY the summary text in a single paragraph without any bullet points, introductory labels, or markdown formatting."
    )

    user_prompt = (
        f"Company Name: {company_name}\n\n"
        f"Company Web Content & Context:\n{company_context[:10000]}"
    )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 250,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        NIM_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:markdown|text)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content).strip()
            return content
    except Exception as e:
        return f"Brief generation failed: {e}"
