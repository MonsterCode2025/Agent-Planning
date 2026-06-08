import os
import re

import requests

_SERP_KEY = os.getenv("SERPAPI_API_KEY")
_SERP_URL = "https://serpapi.com/search.json"


def web_search(query: str, language: str = "en", num: int = 5) -> list[dict]:
    if not _SERP_KEY:
        return [{"title": "[SerpAPI key missing]", "link": "", "snippet": "Set SERPAPI_API_KEY in .env"}]
    params = {
        "engine": "google",
        "q": query,
        "api_key": _SERP_KEY,
        "num": num,
        "hl": language,
    }
    try:
        r = requests.get(_SERP_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return [{"title": "[search error]", "link": "", "snippet": str(e)}]

    results = []
    for item in data.get("organic_results", [])[:num]:
        results.append(
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return results


_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def web_fetch(url: str, max_chars: int = 3000) -> str:
    if not url:
        return ""
    try:
        r = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PlanningAgent/1.0)"},
        )
        r.raise_for_status()
        html = r.text
    except requests.RequestException as e:
        return f"[fetch error: {e}]"

    html = _SCRIPT_RE.sub("", html)
    html = _STYLE_RE.sub("", html)
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]
