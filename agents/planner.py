"""
Planner Agent: Single LLM call to route queries to sub-agents.

Input:  parsed query (companies, years, topics, analysis_type)
Output: which agents to call + structured inputs for each
"""

import os
import json
import re
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = "openai/gpt-oss-120b"

PLANNER_SYSTEM_PROMPT = """You are a financial query planner. Given a parsed user query, decide which agents to call.

Available agents:
- retriever: Fetches data from Neo4j (graph), ChromaDB (semantic), DuckDB (numerical). ALWAYS called.
- analyst: Runs calculations — growth rates, margins, comparisons, trends. Call when query involves numbers, comparisons, or trends.
- visualizer: Generates charts. Call when analysis_included=true OR query asks for charts/visualization.
- reporter: Generates a structured markdown report. Call when analysis_included=true OR query asks for a report/summary.

Return ONLY valid JSON. Do not include any text before or after the JSON.
{
  "agents": ["retriever", "analyst"],
  "retriever_input": {
    "companies": ["AMD"],
    "years": [2021],
    "query": "original query"
  },
  "analyst_input": {
    "type": "growth|margins|comparison|trends",
    "focus": "revenue"
  },
  "visualizer_input": {
    "chart_types": ["bar", "line", "comparison"],
    "title_hint": "AMD Revenue Trend"
  },
  "reporter_input": {
    "format": "executive_summary"
  },
  "reasoning": "brief explanation of why these agents"
}"""


def _default_plan(parsed: dict, analysis_included: bool, reason: str = "fallback plan") -> dict:
    """Return a safe default plan when the LLM call fails or returns bad JSON."""
    return {
        "agents": ["retriever", "analyst"] + (["visualizer", "reporter"] if analysis_included else []),
        "retriever_input": {
            "companies": parsed.get("companies", []),
            "years": parsed.get("years", []),
            "query": parsed.get("raw_query", ""),
        },
        "analyst_input": {"type": parsed.get("analysis_type", "general"), "focus": "general"},
        "reasoning": reason,
    }


def plan_query(parsed: dict, analysis_included: bool = False) -> dict:
    """Single LLM call to decide which agents to invoke and their inputs."""
    from groq import Groq

    user_msg = json.dumps({
        "companies": parsed.get("companies", []),
        "years": parsed.get("years", []),
        "topics": parsed.get("topics", []),
        "analysis_type": parsed.get("analysis_type", "general"),
        "analysis_included": analysis_included,
        "raw_query": parsed.get("raw_query", ""),
    })

    try:
        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content
    except Exception as e:
        logger.warning(f"Planner LLM call failed ({e}); using fallback plan")
        return _default_plan(parsed, analysis_included, reason="llm_call_failed")

    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            plan = json.loads(match.group())
            if "retriever" not in plan.get("agents", []):
                plan.setdefault("agents", []).insert(0, "retriever")
            return plan
        except json.JSONDecodeError as e:
            logger.warning(f"Planner returned invalid JSON ({e}); using fallback plan")
            return _default_plan(parsed, analysis_included, reason="json_parse_failed")

    logger.warning("Planner response contained no JSON; using fallback plan")
    return _default_plan(parsed, analysis_included, reason="no_json_in_response")