"""抓取工具实现：按站点抓取（带 TTL 缓存），供工具注册表与抓取 Agent 复用。

与 scrapers/ 的关系：scrapers 是原子抓取器；本模块把它们包装为
「可被 LLM 工具调用、可被 FetcherAgent 并行调度」的能力。
"""
import json
from typing import Any, Dict, List, Optional

from ..core.cache import TTLCache
from ..scrapers.arxiv_scraper import ArxivScraper
from ..scrapers.github_trending_scraper import GithubTrendingScraper
from ..scrapers.hf_scraper import HuggingFaceScraper
from ..scrapers.qbitai_scraper import QbitaiScraper
from ..scrapers.wired_scraper import WiredScraper

_cache = TTLCache()

# 站点标识 → 抓取器实例
SCRAPERS: Dict[str, Any] = {
    "huggingface": HuggingFaceScraper(),
    "github_trending": GithubTrendingScraper(),
    "arxiv": ArxivScraper(),
    "qbitai": QbitaiScraper(),
    "wired": WiredScraper(),
}

DEFAULT_LIMIT = 10


def fetch_site_items(site: str, keyword: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    """抓取单个站点（带缓存），返回 Item 列表；失败返回空列表（失败隔离）。

    keyword 兼容策略：中文关键词只传给中文站点（qbitai），
    避免英文站点（HF/GitHub/arXiv/WIRED）收到中文检索词导致空结果。
    """
    if keyword and not keyword.isascii() and site != "qbitai":
        keyword = None
    cache_key = f"{site}:{keyword or 'latest'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    scraper = SCRAPERS.get(site)
    if scraper is None:
        return []
    try:
        items = scraper.scrape(keyword=keyword, limit=limit)
    except Exception:  # noqa: BLE001 - 单站点失败不阻断整体
        items = []
    _cache.set(cache_key, items)
    return items


def fetch_and_report(site: str, keyword: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> str:
    """工具版抓取：返回 JSON 字符串（LLM 回灌友好）。"""
    result = fetch_site_items(site, keyword, limit)
    return json.dumps({"site": site, "count": len(result), "items": result}, ensure_ascii=False)


# 5 个可注册工具（函数, 名称）
def fetch_huggingface(keyword: str = "", limit: int = DEFAULT_LIMIT) -> str:
    return fetch_and_report("huggingface", keyword or None, limit)


def fetch_github_trending(keyword: str = "", limit: int = DEFAULT_LIMIT) -> str:
    return fetch_and_report("github_trending", keyword or None, limit)


def fetch_arxiv(keyword: str = "", limit: int = DEFAULT_LIMIT) -> str:
    return fetch_and_report("arxiv", keyword or None, limit)


def fetch_qbitai(keyword: str = "", limit: int = DEFAULT_LIMIT) -> str:
    return fetch_and_report("qbitai", keyword or None, limit)


def fetch_wired(keyword: str = "", limit: int = DEFAULT_LIMIT) -> str:
    return fetch_and_report("wired", keyword or None, limit)
