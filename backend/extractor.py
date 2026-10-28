"""
extractor.py – Convert raw HTML into structured ExtractedRecord objects.
Uses BeautifulSoup for boilerplate removal and LLM for dynamic field extraction.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from llm_client import generate_json
from schemas import EvidenceSnippet, ExtractedRecord, ResearchPlan

log = logging.getLogger(__name__)

# Tags whose content is considered boilerplate
_NOISE_TAGS = [
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "form", "button", "svg", "iframe", "meta", "link",
]


# ──────────────────────────────────────────────
# HTML cleaning
# ──────────────────────────────────────────────

def clean_html(html: str) -> tuple[str, str, dict[str, str]]:
    """
    Returns (title, clean_text, metadata_dict) from raw HTML.
    Removes navigation, scripts, and repeated whitespace.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract metadata before removing tags
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or tag.get("property") or ""
        content = tag.get("content") or ""
        if name and content:
            meta[name.lower()] = content[:500]

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else "Untitled"
    title = title[:300]

    # Remove noise tags
    for tag in soup(set(_NOISE_TAGS)):
        tag.decompose()

    # Get readable text
    text = soup.get_text(separator="\n", strip=True)
    # Collapse excessive whitespace / blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Remove very short lines (likely navigation remnants)
    lines = [ln for ln in lines if len(ln) > 20]
    clean_text = "\n".join(lines)

    # Truncate to reasonable length for LLM
    clean_text = clean_text[:8000]

    return title, clean_text, meta


def extract_date(html: str, meta: dict[str, str]) -> Optional[str]:
    """Try to find a publication or update date."""
    # Check common meta tags first
    for key in ["article:published_time", "og:updated_time", "date", "pubdate", "published"]:
        if key in meta:
            return meta[key][:50]

    # Regex patterns in HTML text
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\w+ \d{1,2},? \d{4})\b",
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
    ]
    html_snippet = html[:3000]
    for pattern in date_patterns:
        m = re.search(pattern, html_snippet)
        if m:
            return m.group(1)
    return None


# ──────────────────────────────────────────────
# Dynamic field extraction via LLM
# ──────────────────────────────────────────────

_EXTRACT_PROMPT = """You are a data extraction agent. Extract specific fields from the webpage text below.

Research Topic: {topic}
Fields to extract: {fields}

Webpage Text (truncated):
---
{text}
---

Return ONLY valid JSON with the field names as keys and extracted values as strings.
If a field is not present in the text, use null.
Also include a "evidence_snippets" key with a list of {{field, snippet}} objects showing where each value came from.

Example:
{{
  "name": "Product X",
  "price": "$999",
  "rating": "4.5/5",
  "evidence_snippets": [
    {{"field": "name", "snippet": "...text where Product X was found..."}},
    {{"field": "price", "snippet": "...text with $999..."}}
  ]
}}"""


async def extract_dynamic_fields(
    text: str, plan: ResearchPlan, url: str
) -> tuple[dict[str, Any], list[EvidenceSnippet]]:
    """Use LLM to extract plan-defined fields from page text."""
    fields_desc = ", ".join(
        f"{k} ({v})" for k, v in plan.extraction_schema.items()
    ) or ", ".join(plan.required_fields)

    prompt = _EXTRACT_PROMPT.format(
        topic=plan.topic,
        fields=fields_desc,
        text=text[:4000],
    )

    data = await generate_json(prompt)
    if not data:
        return _fallback_extract(text, plan), []

    evidence: list[EvidenceSnippet] = []
    raw_snippets = data.pop("evidence_snippets", []) or []
    if isinstance(raw_snippets, list):
        for s in raw_snippets:
            if isinstance(s, dict) and "snippet" in s:
                evidence.append(
                    EvidenceSnippet(
                        text=str(s.get("snippet", ""))[:500],
                        source_url=url,
                        field_name=s.get("field"),
                        confidence=0.7,
                    )
                )

    # Remove null values
    dynamic = {k: v for k, v in data.items() if v is not None and v != ""}
    return dynamic, evidence


def _fallback_extract(text: str, plan: ResearchPlan) -> dict[str, Any]:
    """
    Simple keyword-based extraction when the LLM is unavailable.
    Finds price, rating, and date patterns from raw text.
    """
    result: dict[str, Any] = {}

    # Price
    price_m = re.search(r"[\$₹€£]\s*[\d,]+(?:\.\d{2})?", text)
    if price_m:
        result["price"] = price_m.group(0)

    # Rating
    rating_m = re.search(r"(\d\.?\d?)\s*/\s*5|rating[:\s]+(\d\.?\d?)", text, re.IGNORECASE)
    if rating_m:
        result["rating"] = (rating_m.group(1) or rating_m.group(2)) + "/5"

    return result


# ──────────────────────────────────────────────
# Main extraction entry point
# ──────────────────────────────────────────────

async def extract_page(
    url: str,
    final_url: str,
    html: str,
    plan: ResearchPlan,
) -> ExtractedRecord:
    """Build an ExtractedRecord from a fetched page."""
    parsed = urlparse(final_url or url)
    domain = parsed.netloc

    title, main_text, meta = clean_html(html)
    published_date = extract_date(html, meta)

    # Dynamic field extraction
    dynamic_fields, evidence_snippets = await extract_dynamic_fields(main_text, plan, final_url or url)

    # Check which required fields were found
    field_coverage = {
        field: (
            field in dynamic_fields
            or field.lower() in main_text.lower()
        )
        for field in plan.required_fields
    }

    # Generate evidence snippets for fields found via text matching (fallback)
    if not evidence_snippets:
        for field in plan.required_fields:
            idx = main_text.lower().find(field.lower())
            if idx >= 0:
                snippet_text = main_text[max(0, idx - 50): idx + 150].strip()
                evidence_snippets.append(
                    EvidenceSnippet(
                        text=snippet_text,
                        source_url=final_url or url,
                        field_name=field,
                        confidence=0.4,
                    )
                )

    record = ExtractedRecord(
        url=url,
        domain=domain,
        title=title,
        main_text=main_text[:3000],
        metadata=meta,
        published_date=published_date,
        collected_at=datetime.utcnow(),
        evidence_snippets=evidence_snippets[:20],
        field_coverage=field_coverage,
        dynamic_fields=dynamic_fields,
    )
    return record
