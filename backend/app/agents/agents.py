import asyncio
import json
import os
import re
# import dotenv
import httpx
import requests
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from typing import Annotated, List, Literal, TypedDict
from langgraph.graph.message import add_messages
from langgraph.types import Send 
from langchain_openai import ChatOpenAI, OpenAI
from huggingface_hub import InferenceClient
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from huggingface_hub import InferenceClient
from services.event_manager import publish_event
from helpers.gpt_helper import call_gpt
from schemas.QualityAssessment import QualityAssessment
from schemas.Tasks import Tasks
from helpers.ollama_helper import call_ollama, call_ollama_structured, call_ollama_text, parse_structured_output
from helpers.gemini_helper import call_gemini_text
from schemas.Plan import Plan
from schemas.ProgressEvent import ProgressEvent
from schemas.State import ResearchSummary, SearchResult, State, TavilyResponse
from core.logger import AgentLogger
from core.prompt_loader import PromptLoader
from httpx import ReadTimeout, TimeoutException
from urllib.parse import urlparse

agent_logger  = AgentLogger()
deepseek_r1 = "deepseek-ai/DeepSeek-R1"

# logic to load prompt must be at a top, if written inside langgraph nodes, every node call prompt keeps loading
# region Load prompts
worker_prompt = PromptLoader.load_prompts(
        "blog_worker.md",
        input_variables=[
            "topic",
            "blog_title",
            "audience",
            "tone",
            "task_title",
            "goal",
            "bullets",
            "section_type",
            "research_summary",
            "target_words",
        ]
    )
orchestrator_prompt = PromptLoader.load_prompts(
        "blog_orchestrator.md",
        input_variables=["topic", "research_summary"]
    )
research_summarizer_prompt = PromptLoader.load_prompts(
        "research_summarizer.md",
        input_variables=["research_context", "topic"]
    )
editor_prompt = PromptLoader.load_prompts(
        "editor_prompt.md",
        input_variables=["blog_content", "topic"]
    )

judge_prompt = PromptLoader.load_prompts(
        "judge_prompt.md",
        input_variables=["blog_content", "topic"]
    )
# endregion Load prompts

TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY")

# llm = ChatOpenAI()
# llm = InferenceClient(model=deepseek_r1)

# client = OpenAI()

#region Models
MODEL_JUDGE = "deepseek-r1:8b"
MODEL_OTHER = "phi3:medium"
#endregion


def emit_progress_event(
    correlation_id: str | None,
    agent: str,
    message: str,
    status: str = "completed",
) -> ProgressEvent:
    event = ProgressEvent(agent=agent, message=message, status=status)
    if correlation_id:
        publish_event(
            correlation_id,
            {
                "agent": event.agent,
                "message": event.message,
                "status": event.status,
            },
        )
    return event


def emit_complete_event(correlation_id: str | None) -> None:
    if correlation_id:
        publish_event(correlation_id, {"type": "COMPLETE"})


#region Data Cleaning

def _truncate_text(text: str, limit: int = 1500) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _normalize_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_domain_allowed(domain: str, allowed_domains: list[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in allowed_domains)


def _is_domain_blocked(domain: str, blocked_domains: list[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in blocked_domains)


def _rank_search_result(result: dict, allowed_domains: list[str]) -> float:
    url = (result.get("url") or "").lower()
    title = (result.get("title") or "").lower()
    content = (result.get("content") or "").lower()
    domain = _normalize_domain(url)

    score = float(result.get("score") or 0.0)

    if _is_domain_allowed(domain, allowed_domains):
        score += 1000.0

    doc_hints = ["docs", "documentation", "api", "reference", "sdk", "guide", "tutorial"]
    if any(h in url for h in doc_hints):
        score += 25.0

    tech_hints = ["engineering", "architecture", "design", "benchmark", "performance", "implementation"]
    if any(h in f"{title} {content}" for h in tech_hints):
        score += 10.0

    return score


def calculate_source_quality(result: dict) -> float:
    """
    Rank a Tavily search result by *research source quality* (not just relevance).

    - Starts from Tavily score
    - Boosts technical/engineering signals
    - Penalizes hiring/course/offer signals
    - Adjusts based on domain heuristics (docs/engineering vs job boards/course sellers)
    """
    try:
        quality_score = float(result.get("score") or 0.0)
    except Exception:
        quality_score = 0.0

    title = result.get("title") or ""
    url = result.get("url") or ""
    content = result.get("content") or ""
    combined = f"{title} {content} {url}".lower()

    technical_keywords = [
        "architecture",
        "framework",
        "frameworks",
        "implementation",
        "developer",
        "developers",
        "engineering",
        "production",
        "scalability",
        "performance",
        "observability",
        "debugging",
        "best practices",
        "tutorial",
        "example",
        "code",
        "github",
        "open source",
        "api",
        "sdk",
        "comparison",
        "benchmark",
        "design pattern",
        "workflow",
        "agent",
        "multi-agent",
        "tool calling",
        "memory",
        "orchestration",
        "langgraph",
        "semantic kernel",
        "autogen",
        "crewai",
        "llamaindex",
    ]

    low_value_keywords = [
        "salary",
        "hiring",
        "job opening",
        "apply now",
        "recruiter",
        "recruitment",
        "course",
        "training",
        "bootcamp",
        "discount",
        "offer",
        "enroll",
        "certification",
        "limited seats",
    ]

    for kw in technical_keywords:
        if kw in combined:
            quality_score += 0.05

    for kw in low_value_keywords:
        if kw in combined:
            quality_score -= 0.10

    domain = _normalize_domain(url)
    boost_domains = [
        "github.com",
        "medium.com",
        "dev.to",
        "microsoft.com",
        "aws.amazon.com",
        "cloud.google.com",
        "huggingface.co",
    ]
    penalize_domains = [
        # Job boards / recruiting platforms
        "indeed.com",
        "glassdoor.com",
        "monster.com",
        "naukri.com",
        "shine.com",
        "ziprecruiter.com",
        "lever.co",
        "greenhouse.io",
        "workable.com",
        # Course selling platforms
        "udemy.com",
        "coursera.org",
        "edx.org",
        "simplilearn.com",
        "upgrad.com",
        "intellipaat.com",
    ]

    if domain:
        if domain.startswith("docs."):
            quality_score += 0.20
        if domain.endswith(".dev"):
            quality_score += 0.20
        if any(domain == d or domain.endswith("." + d) for d in boost_domains):
            quality_score += 0.20
        if any(domain == d or domain.endswith("." + d) for d in penalize_domains):
            quality_score -= 0.30
    
    return quality_score


def clean_extracted_content(text: str) -> str:
    if not text:
        return ""

    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")

    # Remove Markdown images: ![alt](url) and reference-style image links.
    cleaned = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\[[^\]]*\]", "", cleaned)

    # Remove HTML <img ...> tags.
    cleaned = re.sub(r"(?is)<img\b[^>]*?>", "", cleaned)

    # Remove empty Markdown links: [](https://...)
    cleaned = re.sub(r"\[\s*\]\(\s*[^)]+\s*\)", "", cleaned)

    # Convert normal Markdown links to just their visible text.
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", cleaned)

    # Convert autolinks <https://...> to empty (usually noise).
    cleaned = re.sub(r"<https?://[^>]+>", "", cleaned)

    # Remove emails / WhatsApp / phone numbers.
    cleaned = re.sub(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(wa\.me|whatsapp\.com)\S*\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(?:\+?\d{1,3}[\s\-\.]?)?(?:\(?\d{2,4}\)?[\s\-\.]?)?\d{3,4}[\s\-\.]?\d{4}\b", "", cleaned)

    # Remove nav/menu/promotional noise lines (case-insensitive contains).
    nav_phrases = [
        "skip to content",
        "home",
        "courses",
        "contact",
        "about us",
        "privacy policy",
        "terms",
        "login",
        "sign up",
        "subscribe",
        "newsletter",
        "share this",
        "follow us",
        "related posts",
        "read more",
        "apply now",
        "enroll now",
        "book demo",
        "claim offer",
        "limited seats",
        "sponsor",
        "sponsored",
        "advertisement",
        "pricing",
        "discount",
        "offer",
        "buy now",
    ]
    nav_re = re.compile("|".join(re.escape(p) for p in nav_phrases), re.IGNORECASE)

    cleaned_lines: list[str] = []
    seen_consecutive: str | None = None
    in_code_block = False

    for line in cleaned.splitlines():
        raw_line = line
        stripped = raw_line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            cleaned_lines.append(raw_line.rstrip())
            seen_consecutive = stripped.lower()
            continue

        if not stripped:
            cleaned_lines.append("")
            seen_consecutive = ""
            continue

        if not in_code_block:
            lowered = stripped.lower()

            # Drop obvious nav/menu lines.
            if nav_re.search(lowered) and len(stripped) < 120:
                continue

            # Drop social lines / pure URLs.
            if re.search(r"(?i)\b(twitter|x\.com|linkedin|facebook|instagram)\b", lowered) and len(stripped) < 160:
                continue
            if re.fullmatch(r"https?://\S+", stripped):
                continue

            # Drop very short standalone lines unless they are headings.
            is_heading = stripped.startswith("#")
            if len(stripped) < 20 and not is_heading:
                continue

            # Drop duplicated consecutive lines (case-insensitive).
            if seen_consecutive is not None and lowered == seen_consecutive:
                continue
            seen_consecutive = lowered

        cleaned_lines.append(raw_line.rstrip())

    cleaned = "\n".join(cleaned_lines)

    # Normalize whitespace (keep paragraphs, remove excessive gaps).
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    return cleaned.strip()


def truncate_content(content: str, max_chars: int = 8000) -> str:
    if not content:
        return ""
    if len(content) <= max_chars:
        return content

    # Try not to cut mid-sentence: find a reasonable sentence boundary before max_chars.
    window_start = max(0, max_chars - 400)
    window = content[window_start:max_chars]

    boundary_matches = list(re.finditer(r"(?s)([.!?])(?:\s|\n)", window))
    if boundary_matches:
        cut_at = window_start + boundary_matches[-1].end()
        return content[:cut_at].rstrip()

    # Fallback: cut at the last newline.
    last_nl = content.rfind("\n", 0, max_chars)
    if last_nl != -1 and last_nl > max_chars * 0.6:
        return content[:last_nl].rstrip()

    return content[:max_chars].rstrip()

def generate_section_search_query(topic: str, task: Tasks) -> str:
    """
    Deterministically generate a concise Tavily query for a specific section.
    Must not call an LLM.
    """
    topic = (topic or "").strip()
    title = (getattr(task, "title", "") or "").strip()
    goal = (getattr(task, "goal", "") or "").strip()
    bullets = getattr(task, "bullets", None) or []
    section_type = (getattr(task, "section_type", "") or "").strip()

    # Weak words add noise and reduce search specificity.
    weak_words = {
        "understand",
        "learn",
        "guide",
        "introduction",
        "intro",
        "overview",
        "basics",
        "basic",
        "beginner",
        "getting",
        "started",
        "start",
        "tutorial",
        "explain",
        "discussion",
        "concepts",
        "core",
        "fundamentals",
    }
    stopwords = {
        "the","a","an","and","or","to","of","in","for","on","with","without","by","from","at","as",
        "is","are","be","been","being","this","that","these","those","it","its","your","you","we",
        "how","what","why","when","where",
    }

    def _tokenize(text: str) -> list[str]:
        # Keep framework names / acronyms / versions: "GPT-4", "PyTorch", "XGBoost", "CUDA", "v2.1"
        raw = re.findall(r"[A-Za-z][A-Za-z0-9\.\+\-_/]{1,}", text or "")
        tokens: list[str] = []
        for t in raw:
            tl = t.lower().strip("._-/")
            if not tl or tl in stopwords or tl in weak_words:
                continue
            # Drop very generic verbs and filler.
            if tl in {"use", "using", "build", "building", "make", "creating", "create", "write"}:
                continue
            tokens.append(t)
        return tokens

    # Weight title/bullets more than goal because they contain "technical nouns" and concrete requirements.
    weighted: dict[str, int] = {}

    def _add_tokens(tokens: list[str], weight: int):
        for tok in tokens:
            key = tok.lower()
            weighted[key] = weighted.get(key, 0) + weight

    _add_tokens(_tokenize(topic), 6)
    _add_tokens(_tokenize(title), 8)
    for b in bullets:
        _add_tokens(_tokenize(str(b)), 7)
    _add_tokens(_tokenize(goal), 3)

    # Add section-type hints (kept technical, not generic).
    section_type_l = section_type.lower()
    if section_type_l == "common_mistakes":
        _add_tokens(["pitfalls", "failure-modes", "edge-cases", "debugging", "production"], 5)
    elif section_type_l == "checklist":
        _add_tokens(["checklist", "production", "testing", "monitoring", "observability"], 5)
    elif section_type_l == "examples":
        _add_tokens(["code", "implementation", "minimal-example"], 4)

    # Preserve year-like tokens from topic (e.g., "2026") if present.
    for year in re.findall(r"\b20\d{2}\b", topic):
        weighted[year] = weighted.get(year, 0) + 6

    # Rank by weight then by token length (prefer informative tokens).
    ranked = sorted(
        weighted.items(),
        key=lambda kv: (kv[1], len(kv[0])),
        reverse=True,
    )

    # Compose a compact query: start with original topic (trimmed), then top keywords.
    # Keep query short to avoid diluting results.
    topic_compact = re.sub(r"\s{2,}", " ", topic).strip()
    base_tokens = _tokenize(topic_compact)
    base = " ".join(base_tokens[:10]) if base_tokens else topic_compact

    chosen: list[str] = []
    seen: set[str] = set()
    for tok, _w in ranked:
        if tok in seen:
            continue
        seen.add(tok)
        # avoid re-adding topic-only tokens aggressively; focus on title/bullet nouns
        if tok in {t.lower() for t in _tokenize(topic_compact)} and len(chosen) >= 8:
            continue
        chosen.append(tok)
        if len(chosen) >= 12:
            break

    # Always include some title tokens (technical nouns from title).
    title_tokens = _tokenize(title)
    for t in title_tokens[:4]:
        tl = t.lower()
        if tl not in seen and len(chosen) < 14:
            chosen.insert(0, tl)
            seen.add(tl)

    query = " ".join([p for p in [base, " ".join(chosen)] if p]).strip()
    query = re.sub(r"\s{2,}", " ", query)
    return query


def perform_section_research(query: str, correlationId: str | None = None) -> str:
    """
    Perform section-level research using Tavily search + extract + existing quality ranking and cleaning.
    Limits to a single best source to avoid excessive parallel API calls.
    """
    try:
        search_results = asyncio.run(tavily_search(query, max_results=15))
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {correlationId}] | [NODE: worker] | Section Tavily search failed: {e}"
        )
        return ""

    results: list[dict] = (search_results or {}).get("results") or []
    if not results:
        return ""

    ranked = []
    for r in results:
        try:
            ranked.append((calculate_source_quality(r), r))
        except Exception:
            ranked.append((0.0, r))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best = ranked[0][1] or {}
    best_url = best.get("url") or ""
    best_title = best.get("title") or ""

    if not best_url:
        # Fallback: use snippet content if no URL is present.
        snippet = clean_extracted_content(best.get("content") or "")
        return truncate_content(snippet, max_chars=6000)

    try:
        extracted_by_url = asyncio.run(tavily_extract([best_url]))
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {correlationId}] | [NODE: worker] | Section Tavily extract failed: {e}"
        )
        extracted_by_url = {}

    raw = extracted_by_url.get(best_url) or best.get("content") or ""
    cleaned = clean_extracted_content(raw)
    cleaned = truncate_content(cleaned, max_chars=12000)

    if not cleaned:
        return ""

    return (
        f"Source: {best_title}\n"
        f"URL: {best_url}\n\n"
        f"{cleaned}"
    )

def format_research_summary_for_worker(summary: ResearchSummary) -> str:
    """
    Convert ResearchSummary into plain-text bullets for prompting.
    Avoid JSON/object repr and avoid leaking schema field names into the prompt.
    """
    if summary is None:
        return ""

    def _bullets(items: list[str], limit: int) -> str:
        items = [str(x).strip() for x in (items or []) if str(x).strip()]
        return "\n".join(f"- {x}" for x in items[:limit])

    parts: list[str] = []

    central_concepts = _bullets(summary.central_concepts, limit=10)
    if central_concepts:
        parts.append("Central Concepts:\n" + central_concepts)

    important_concepts = _bullets(summary.important_concepts, limit=10)
    if important_concepts:
        parts.append("Imp Concepts:\n" + important_concepts)

    supporting_concepts = _bullets(summary.supporting_concepts, limit=10)
    if supporting_concepts:
        parts.append("Supporting Concepts:\n" + supporting_concepts)

    details = _bullets(summary.technical_details, limit=10)
    if details:
        parts.append("Technical Insights:\n" + details)

    risks = _bullets(summary.risks_and_challenges, limit=8)
    if risks:
        parts.append("Risks & Failure Modes:\n" + risks)

    trends = _bullets(summary.important_trends, limit=8)
    if trends:
        parts.append("Important Trends:\n" + trends)

    return "\n\n".join(parts).strip()

# ==========================
# Reducer Helpers
# ==========================

def clean_section(section: str) -> str:

    if not section:
        return ""

    # remove placeholder URLs
    section = re.sub(
        r"https?://example\.com\S*",
        "",
        section,
        flags=re.IGNORECASE
    )

    # remove References heading
    section = re.sub(
        r"#+\s*References.*?$",
        "",
        section,
        flags=re.IGNORECASE | re.MULTILINE
    )

    return section.strip()
#endregion Data Cleaning


#region LangGraph Nodes
def tavily_search_node(state : State) -> dict:
    topic = state["topic"]
    agent_logger.log_state("tavily_search_node", state)
    # Call Tavily search api:
    search_results =  asyncio.run(tavily_search(topic))

    # Log the full Tavily response (entire `search_results`) for debugging/traceability
    try:
        agent_logger.logger.info(
            f"[CID: {state.get('correlationId')}] | "
            f"[NODE: tavily_search_node] | "
            f"search_results={json.dumps(search_results, ensure_ascii=False)}"
        )
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {state.get('correlationId')}] | "
            f"[NODE: tavily_search_node] | "
            f"Failed to log search_results: {e}"
        )
    
    # If no search results found
    if not search_results:
        print("No search results")
        return {"research_content" : search_results}
    # print(search_results['results'])
    
    # top_results = results["results"][:2]
    
    # agent_logger.log_state("tavily_search_node", "search completed")
    
    tavily_response = TavilyResponse(
        query = search_results.get("query"),
        results = [
            SearchResult(
                title = r.get("title"),
                content = r.get("content"),
                # url = r.get("url"),
                # score = r.get("score"),
            )
            for r in search_results.get('results')
        ],
        response_time = search_results.get("response_time"),
        request_id = search_results.get("request_id")
    )
    
    # agent_logger.log_state("tavily_search_node", "pydantic model binding completed")

    # for res in tavily_response.results:
    #     # agent_logger.log_state("tavily_search_node", state)
    #     agent_logger.log_state("URL", res.url)
    #     agent_logger.log_state("title", res.title)
    #     agent_logger.log_state("score", res.score)
    #     agent_logger.log_state("content", res.content)
    # print(f"tavily_response.results : \n",tavily_response.results)
    return {"research_content" : tavily_response.results}

def research_node(state: State) -> dict:
    """
    Architecture B node:
    Performs topic-level web research before planning begins and returns a single combined
    `research_context` string for downstream planning/orchestration.
    """
    correlation_id = state.get("correlationId")
    topic = state["topic"]
    agent_logger.log_state("research_node", state)
    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_node] | Starting web research | topic={topic!r}"
    )

    emit_progress_event(
        correlation_id=correlation_id,
        agent="Research Agent",
        message="Searching web sources...",
        status="running"
    )


    try:
        search_results = asyncio.run(tavily_search(topic, max_results=5))
    except (ReadTimeout, TimeoutException) as e:
        agent_logger.logger.exception(
            f"[CID: {correlation_id}] | [NODE: research_node] | Tavily search timed out: {e}"
        )
        event = emit_progress_event(
            correlation_id=correlation_id,
            agent="Research Agent",
            message=f"Web research timed out for {topic}; no sources extracted",
            status="failed",
        )

        return {
            "research_context": "",
            "progress_events": [event],
        }

    # Debug: log the full Tavily search response (log file only).
    try:
        search_json = json.dumps(search_results, indent=2, ensure_ascii=False)
        agent_logger.logger.info(
            f"[CID: {correlation_id}] | [NODE: research_node] | tavily_search_response_length={len(search_json)}"
        )
        agent_logger.logger.info(
            f"[CID: {correlation_id}] | [NODE: research_node] | tavily_search_response={_truncate_text(search_json, limit=20000)}"
        )
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {correlation_id}] | [NODE: research_node] | Failed to log Tavily search response: {e}"
        )

    results = (search_results or {}).get("results") or []

    emit_progress_event(
        correlation_id=correlation_id,
        agent="Research Agent",
        message=f"Found {len(results)} candidate sources",
        status="running"
    )

    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_node] | Tavily search completed | results_count={len(results)}"
    )

    # Debug: log per-result fields (log file only).
    try:
        for i, r in enumerate(results, start=1):
            agent_logger.logger.info(
                f"[CID: {correlation_id}] | [NODE: research_node] | result_index={i} | "
                f"title={r.get('title')!r} | url={r.get('url')!r} | "
                f"score={r.get('score')!r} | content_preview={_truncate_text(r.get('content') or '', limit=800)!r}"
            )
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {correlation_id}] | [NODE: research_node] | Failed to log result fields: {e}"
        )

    blocked_domains = [
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
    ]

    # Filter out social media before extracting (Architecture B wants research sources, not social posts).
    filtered: list[dict] = []
    for r in results:
        url = r.get("url") or ""
        domain = _normalize_domain(url)
        if not domain:
            continue
        if _is_domain_blocked(domain, blocked_domains):
            agent_logger.logger.info(
                f"[CID: {correlation_id}] | [NODE: research_node] | filtered_blocked_domain={domain} | url={url}"
            )
            continue
        filtered.append(r)

    # Rank sources by research-quality before selecting URLs for extraction.
    scored: list[tuple[float, dict]] = []
    for r in filtered:
        quality = calculate_source_quality(r)
        scored.append((quality, r))
        agent_logger.logger.info(
            f"[CID: {correlation_id}] | [NODE: research_node] | source_quality | "
            f"url={r.get('url')} | tavily_score={r.get('score')} | quality_score={quality}"
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    top_results = [r for _, r in scored[:5]]
    top_urls = [r.get("url") for r in top_results if r.get("url")]

    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_node] | Selected top sources | urls={top_urls}"
    )
    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_node] | selected_research_sources={json.dumps(top_urls, ensure_ascii=False)}"
    )

    extracted_by_url: dict[str, str] = {}
    if top_urls:
        try:
            extracted_by_url = asyncio.run(tavily_extract(top_urls))
            agent_logger.logger.info(
                f"[CID: {correlation_id}] | [NODE: research_node] | Tavily extract completed | extracted_count={len(extracted_by_url)}"
            )

            # Clean extracted content before assembling research_context, and log size deltas.
            cleaned_by_url: dict[str, str] = {}
            for u in top_urls:
                raw = extracted_by_url.get(u, "") or ""
                cleaned = clean_extracted_content(raw)
                cleaned_by_url[u] = cleaned
                removed_pct = 0
                if len(raw) > 0:
                    removed_pct = int(round((1.0 - (len(cleaned) / max(len(raw), 1))) * 100))
                agent_logger.logger.info(
                    f"[CID: {correlation_id}] | [NODE: research_node] | extract_cleaning | url={u} | raw={len(raw)} | cleaned={len(cleaned)} | removed={removed_pct}%"
                )

            extracted_by_url = cleaned_by_url

            # Log extracted content previews (URL + content) for debugging/traceability.
            for u in top_urls:
                agent_logger.logger.info(
                    f"[CID: {correlation_id}] | [NODE: research_node] | extracted_url={u} | extracted_content_full=\n{extracted_by_url.get(u, '')}"
                )
        except (ReadTimeout, TimeoutException) as e:
            agent_logger.logger.exception(
                f"[CID: {correlation_id}] | [NODE: research_node] | Tavily extract timed out: {e}"
            )
            extracted_by_url = {}
    else:
        agent_logger.logger.warning(
            f"[CID: {correlation_id}] | [NODE: research_node] | No URLs to extract (no search results or missing url fields)"
        )

    blocks: list[str] = []
    for index, r in enumerate(top_results, start=1):
        title = r.get("title") or f"Source {index}"
        url = r.get("url") or ""
        extracted_content = extracted_by_url.get(url, "") if url else ""
        blocks.append(
            f"Source {index}:\n\n{title}\n\n{extracted_content}".strip()
        )

    research_context = "\n\n---\n\n".join(blocks).strip()

    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_node] | Research completed | research_context_chars={len(research_context)}"
    )
    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_node] | research_context_full=\n{research_context}"
    )

    event = emit_progress_event(
        correlation_id=correlation_id,
        agent="Research Agent",
        message="Completed web research",
        status="completed",
    )
    return {
        "research_context": research_context,
        "progress_events": [event],
    }

def research_summarizer_node(state: State) -> dict:
    correlation_id = state.get("correlationId")
    topic=state.get("topic")
    research_context = (state.get("research_context", "") or "")[:25000]

    agent_logger.log_state("research_summarizer_node", state)
    agent_logger.logger.info(
        f"[CID: {correlation_id}] | [NODE: research_summarizer] | Input research chars={len(research_context)}"
    )
    emit_progress_event(
        correlation_id=correlation_id,
        agent="Research Analyst Agent",
        message="Analyzing research corpus...",
        status="running"
    )


    formatted_prompt = research_summarizer_prompt.format(research_context=research_context, topic = topic)

    raw_output = call_ollama(formatted_prompt, MODEL_OTHER)
    summary = parse_structured_output(raw_output, ResearchSummary)

    if len(summary.central_concepts) == 0 and len(summary.technical_details) == 0:
        agent_logger.logger.warning(f"[CID:{correlation_id}] Empty summary. Using fallback.")
        summary = ResearchSummary(
            central_concepts=[
                f"High-level overview of {topic}",
                "Key concepts and architectures (details gathered per section)",
                "Implementation approaches (details gathered per section)",
            ],
            technical_details=[
                "Worker agents will gather section-specific technical details from sources"
            ],
            risks_and_challenges=[],
            important_trends=[],
        )

    try:
        summary_json = json.dumps(summary.model_dump(), ensure_ascii=False)
        # agent_logger.logger.info(
        #     f"[CID: {correlation_id}] | [NODE: research_summarizer] | "
        #     f"Extracted concepts={len(summary.core_concepts)} | "
        #     f"Technical details={len(summary.technical_details)} | "
        #     f"Research Summary Details={summary_json} | "
        #     f"Summary chars={len(summary_json)}"
        # )
        agent_logger.info(
                f"Central Concepts={len(summary.central_concepts)} | "
                f"Imp Concepts={len(summary.important_concepts)} | "
                f"Supporting Concepts={len(summary.supporting_concepts)} | "
                f"Frameworks={len(summary.frameworks_and_tools)} | "
                f"Metrics={len(summary.evaluation_metrics)} | "
                f"Technical={len(summary.technical_details)} | "
                f"Production={len(summary.production_considerations)}"
                f"Research Summary Details={summary_json} | "
                f"Summary chars={len(summary_json)}"
                )

    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {correlation_id}] | [NODE: research_summarizer] | Failed to log summary stats: {e}"
        )

    event = emit_progress_event(
        correlation_id=correlation_id,
        agent="Research Analyst Agent",
        message="Extracted research insights",
        status="completed",
    )

    return {"research_summary": summary, "progress_events": [event]}

def orchestrator(state : State) -> dict:
    agent_logger.log_state("orchestrator", state)
    topic = state["topic"]

    research_summary = state["research_summary"]
    agent_logger.logger.info("Research Summary:\n%s", research_summary.model_dump_json(indent=2))
    try:
        research_summary_json = (
            research_summary.model_dump_json(indent=2)
            if hasattr(research_summary, "model_dump_json")
            else json.dumps(research_summary, ensure_ascii=False, indent=2)
        )
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {state.get('correlationId')}] | [NODE: orchestrator] | Failed to serialize research_summary: {e}"
        )
        research_summary_json = "{}"

    try:
        central_concepts_count = len(getattr(research_summary, "central_concepts", []) or [])
        technical_details_count = len(getattr(research_summary, "technical_details", []) or [])
        agent_logger.logger.info(
            f"[CID: {state.get('correlationId')}] | [NODE: orchestrator] | "
            f"Received concepts={central_concepts_count} | Technical details={technical_details_count}"
        )
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {state.get('correlationId')}] | [NODE: orchestrator] | Failed to log research_summary stats: {e}"
        )

    formatted_prompt = orchestrator_prompt.format(
        topic=topic,
        central_concepts = research_summary.central_concepts,
        important_concepts = research_summary.important_concepts,
        supporting_concepts = research_summary.supporting_concepts,
        frameworks_and_tools = research_summary.frameworks_and_tools,
        evaluation_metrics = research_summary.evaluation_metrics,
        technical_details = research_summary.technical_details,
        production_considerations = research_summary.production_considerations,
        risks_and_challenges = research_summary.risks_and_challenges,
        important_trends = research_summary.important_trends,
        research_summary=research_summary_json,
    )
    # print("formatted_prompt  completed")
    #agent_logger.log_prompt(node_name="orchestrator", correlationId= state.get("correlationId"), prompt=formatted_prompt)
    #plan = llm.with_structured_output(Plan).invoke(formatted_prompt)
    emit_progress_event(
        correlation_id=state.get("correlationId"),
        agent="Planning Agent",
        message="Creating article outline...",
        status="running"
    )

    raw_output = call_ollama(formatted_prompt, MODEL_OTHER)
    # print("call ollama  completed")
    plan = parse_structured_output(raw_output, Plan)
    
    try:
        plan_json = json.dumps(plan.model_dump(), ensure_ascii=False)
        agent_logger.logger.info(
            f"[CID: {state.get('correlationId')}] | [NODE: orchestrator] | "
            f"Plan Details={plan_json} | "
            f"Plan chars={len(plan_json)}"
        )
    except Exception as e:
        agent_logger.logger.exception(
            f"[CID: {state.get('correlationId')}] | [NODE: orchestrator] | Failed to log plan stats: {e}"
        )

    event = emit_progress_event(
        correlation_id=state.get("correlationId"),
        agent="Planning Agent",
        message="Created writing plan",
        status="completed",
    )

    return {"plan" : plan, "progress_events": [event]}

def fanout(state : State):
    agent_logger.log_state("fanout", state)
    return [Send("worker", {"task" : task, "topic" : state['topic'], "plan" : state['plan'],
                            "research_summary": state["research_summary"],
                            "correlationId": state["correlationId"]})
        for task in state["plan"].tasks]

def worker(payload : dict) -> dict:
    agent_logger.log_state("worker_start", payload)
    task = payload["task"]
    topic = payload["topic"]
    plan = payload["plan"]
    research_summary = payload.get("research_summary")
    agent_logger.logger.info(f"Research Summary Type={type(research_summary)}")
    correlationId = payload.get("correlationId")
    central_concepts = research_summary.central_concepts
    important_concepts = research_summary.important_concepts
    supporting_concepts = research_summary.supporting_concepts
    frameworks_and_tools = research_summary.frameworks_and_tools
    evaluation_metrics = research_summary.evaluation_metrics
    technical_details = research_summary.technical_details
    production_considerations = research_summary.production_considerations
    risks_and_challenges = research_summary.risks_and_challenges
    important_trends = research_summary.important_trends

    agent_logger.logger.info(
            f"[CID: {correlationId}] | "
            f"[NODE: worker] | "
            f"worker_start | "
            f"task_id={getattr(task, 'id', None)} | "
            f"task_title={getattr(task, 'title', '')}"
        )

    research_summary_text = format_research_summary_for_worker(research_summary)
    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | global_summary_chars={len(research_summary_text)}"
    )

    blog_title = getattr(plan, "blog_title", "") or ""
    audience = getattr(plan, "audience", "") or ""
    tone = getattr(plan, "tone", "") or ""
    task_title = getattr(task, "title", "") or ""
    goal = getattr(task, "goal", "") or ""
    bullets_list = getattr(task, "bullets", None) or []
    bullets_text = "\n".join([f"- {b}" for b in bullets_list]) if bullets_list else ""
    section_type = getattr(task, "section_type", "") or ""
    target_words = max(int(getattr(task, "target_words", None) or 200), 250)

    formatted_prompt = worker_prompt.format(
        topic=topic,
        blog_title=blog_title,
        audience=audience,
        tone=tone,
        task_title=task_title,
        goal=goal,
        bullets=bullets_text,
        section_type=section_type,
        research_summary=research_summary_text,
        
        central_concepts="\n".join(central_concepts),
        important_concepts="\n".join(important_concepts),
        supporting_concepts="\n".join(supporting_concepts),

        frameworks_and_tools="\n".join(
            frameworks_and_tools
        ),

        evaluation_metrics="\n".join(
            evaluation_metrics
        ),

        technical_details="\n".join(
            technical_details
        ),

        production_considerations="\n".join(
            production_considerations
        ),

        risks_and_challenges="\n".join(
            risks_and_challenges
        ),

        important_trends="\n".join(
            important_trends
        ),

        target_words=target_words
        )

    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | "
        f"pre_ollama | task_title={task_title!r} | prompt_len={len(formatted_prompt)}"
    )
    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | prompt_first_1000={_truncate_text(formatted_prompt, limit=1000)}"
    )
    
    # log_prompt creating too much prompts in log file
    agent_logger.log_prompt(node_name="worker", correlationId= correlationId, prompt=formatted_prompt)
    #raw_output = call_ollama(formatted_prompt)
    emit_progress_event(
        correlation_id=correlationId,
        agent="Writer Agent",
        message=f"Writing: {task_title}",
        status="running"
    )


    section_md = call_ollama_text(formatted_prompt, MODEL_OTHER) #llm.invoke(formatted_prompt).content.strip()

    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | post_ollama | response_len={len(section_md or '')}"
    )
    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | raw_response={_truncate_text(section_md or '', limit=20000)}"
    )

    def is_invalid_worker_output(text: str | None) -> bool:
        if not text:
            return True
        stripped = text.strip()
        if stripped == "":
            return True
        if stripped.startswith("{") and stripped.endswith("}"):
            return True
        if len(stripped) < 500:
            return True
        return False

    if is_invalid_worker_output(section_md):
        retry_prompt = (
            formatted_prompt
            + "\n\nYour previous response was invalid.\n"
            "Generate markdown article content only.\n"
            "Do not output JSON.\n"
            "Do not output metadata."
        )
        section_md = call_ollama_text(retry_prompt, MODEL_OTHER)

    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | generated_section_chars={len(section_md or '')}"
    )
    agent_logger.logger.info(
        f"[CID: {correlationId}] | [NODE: worker] | generated_section_preview={_truncate_text(section_md or '', limit=300)}"
    )
    # print("sections : ",section_md)
    post_event = emit_progress_event(
        correlation_id=correlationId,
        agent="Writer Agent",
        message=f"Writing: {getattr(task, 'title', '') or 'Untitled Section'}",
        status="completed",
    )

    return {"sections": [section_md], "progress_events": [post_event]}

def edit_blog(topic : str, blog_content: str, correlationId : str)-> str:
    formatted_prompt = editor_prompt.format(topic = topic, blog_content = blog_content)

    # edited_blog = call_ollama_text(
    #     formatted_prompt,
    #     MODEL_JUDGE
    # )

    edited_blog = call_gemini_text(formatted_prompt)
    #edited_blog = call_ollama_text(formatted_prompt, MODEL_JUDGE)
    event = emit_progress_event(
        correlation_id=correlationId,
        agent="Editor Agent",
        message="Editing final article",
        status="completed",
    )
    return edited_blog.strip()

def reducer(state : State) -> dict:
    agent_logger.log_state("reducer", state)
    title = state["plan"].blog_title
    # body = "\n\n".join(state["sections"]).strip()
    cleaned_sections = [
        clean_section(section)
        for section in state["sections"]
    ]

    body = "\n\n".join(cleaned_sections).strip()

    emit_progress_event(
        correlation_id=state.get("correlationId"),
        agent="Editor Agent",
        message="Polishing article...",
        status="running"
    )

    edited_blog = edit_blog(topic=state["topic"],blog_content=body, correlationId = state.get('correlationId'))

    # final_blog = f"# {title}\n\n{edited_blog}\n\n"
    final_blog = edited_blog
    # save to file
    filename = "generated_blog.md"
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok= True)
    output_path = output_dir/filename
    agent_logger.logger.info(
        f"[CID: {state.get('correlationId')}] | [NODE: reducer] | Writing markdown file | "
        f"path={str(output_path)} | markdown_chars={len(final_blog)}"
    )
    output_path.write_text(final_blog, encoding="utf-8")
    agent_logger.logger.info(
        f"[CID: {state.get('correlationId')}] | [NODE: reducer] | Markdown file created successfully | "
        f"path={str(output_path)}"
    )

    event = emit_progress_event(
        correlation_id=state.get("correlationId"),
        agent="Reducer Agent",
        message="Creating final markdown",
        status="completed",
    )

    return {"final": final_blog, "progress_events": [event]}

def publish_to_devto_node(state : State) -> dict:
    
    api_key = os.getenv("DEVTO_API_KEY")

    if not api_key:
        #print("Dev.to API key missing")
        return {"published_url":""}

    final_blog=state["final"]
    plan = state["plan"]
    title = plan.blog_title
    url = "https://dev.to/api/articles"
    headers = {
        "api_key" : api_key,
        "Content-Type" : "application/json"
    }

    payload = {
        "article" : {
            "title" : title,
            "published" : True,
            "body_markdown" : final_blog,
            "tags" : ["ai","machinelearning","deeplearning"]
        }
    }

    try:
        response = requests.post(url=url, json=payload, headers=headers)
        if response.status_code != 201:
            #print("Dev.to publishing failed")
            return {"published_url":""}
        data = response.json()
        article_url = data.get("url","")
        #print("Published URL : ", article_url)

        return {"published_url": article_url}
    
    except Exception as e:
        #print("Publish error : ", str(e))
        return {"published_url":""}

def judge(state : State) -> dict:
    
    topic = state["topic"]
    blog_content = state["final"]

    quality_assessment = review_and_judge_blog(topic=topic, blog_content=blog_content)

    progress_events = emit_progress_event(
        correlation_id=state.get("correlationId"),
        agent="Judge Agent",
        message="Evaluating article quality",
        status="completed"
    )
    return {"quality_assessment" : quality_assessment, "progress_events" : [progress_events] }


#endregion LangGraph Nodes


g = StateGraph(State)
g.add_node("tavily_search_node", tavily_search_node)
g.add_node("research_node", research_node)
g.add_node("research_summarizer_node", research_summarizer_node)
g.add_node("orchestrator", orchestrator)
g.add_node("worker", worker)
g.add_node("reducer", reducer)
g.add_node("judge", judge)
# g.add_node("publish_to_devto_node", publish_to_devto_node)

g.add_edge(START, "research_node")
g.add_edge("research_node", "research_summarizer_node")
g.add_edge("research_summarizer_node", "orchestrator")
g.add_conditional_edges("orchestrator", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", "judge")
g.set_finish_point("judge")

workflow = g.compile()

#not required for fast api 
# blog = app.invoke({"topic" : "Write a blog on self attention"})
# print(blog)

# Required for FastAPI 
def run_blog_writer(topic : str, correlationId : str):
    result = workflow.invoke({"topic" : topic, "correlationId" : correlationId})
    emit_complete_event(correlationId)
    return result


# External API calls 


async def tavily_search(topic: str, max_results: int = 5):
    #print("tavily_search method invoked")
    url = "https://api.tavily.com/search"
    payload = {
        "api_key" : TAVILY_API_KEY,
        "query" : topic,
        "search_depth" : "advanced",
        "max_results" : max_results,
    }

    timeout = httpx.Timeout(30.0, connect=10.0)
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        except (ReadTimeout, TimeoutException):
            if attempt == 2:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))


async def tavily_extract(urls: list[str]) -> dict[str, str]:
    """
    Tavily Extract API wrapper.
    Returns a mapping of url -> extracted content.
    """
    url = "https://api.tavily.com/extract"
    payload = {
        "api_key": TAVILY_API_KEY,
        "urls": urls,
    }

    timeout = httpx.Timeout(45.0, connect=10.0)
    data: dict = {}
    extract_response: dict = {}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                extract_response = response.json() or {}
                data = extract_response
            break
        except (ReadTimeout, TimeoutException):
            if attempt == 2:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))

    # Debug: log the full Tavily extract response so we can validate its shape (log file only).
    try:
        extract_json = json.dumps(extract_response, indent=2, ensure_ascii=False)
        agent_logger.logger.info(f"[NODE: tavily_extract] | extract_response_length={len(extract_json)}")
        agent_logger.logger.info(
            f"[NODE: tavily_extract] | extract_response={_truncate_text(extract_json, limit=20000)}"
        )
    except Exception as e:
        agent_logger.logger.exception(f"[NODE: tavily_extract] | Failed to log extract_response: {e}")

    results = data.get("results") or []
    extracted: dict[str, str] = {}
    for r in results:
        source_url = r.get("url")
        content = r.get("raw_content") or r.get("content") or ""
        if source_url:
            extracted[source_url] = content

    # Log extract output as (url, preview) so you can see what was researched.
    try:
        summary = [
            {"url": u, "content_preview": _truncate_text(extracted.get(u, ""), limit=800)}
            for u in urls
        ]
        agent_logger.logger.info(
            f"[NODE: tavily_extract] | extracted_summary={json.dumps(summary, ensure_ascii=False)}"
        )
    except Exception as e:
        agent_logger.logger.exception(f"[NODE: tavily_extract] | Failed to log extracted summary: {e}")

    return extracted
     
def review_and_judge_blog(topic : str, blog_content : str, provider : str = "openai") -> QualityAssessment:
    
    formatted_prompt = judge_prompt.format(blog_content=blog_content, topic = topic)
    if provider == "ollama":
        raw_output = call_ollama_structured(formatted_prompt, MODEL_JUDGE)
    elif provider == "openai": 
         raw_output = call_gpt(formatted_prompt)
    else:
        raise ValueError(f"Unsupported Provider {provider}")
    
    final_assessment = parse_structured_output(raw_output, QualityAssessment)
    return final_assessment


# blog_path = Path("output/generated_blog.md")
# blog_content = blog_path.read_text(encoding="utf-8")

# assessment = review_and_judge_blog(topic="RAG Evaluation",blog_content=blog_content, provider="ollama")

# print(assessment.model_dump_json(indent=2))

# publish_event("test123", {"message" : "hello"})

    
