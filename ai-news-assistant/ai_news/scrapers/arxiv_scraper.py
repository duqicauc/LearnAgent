"""arXiv Scraper：使用官方 Atom API 获取最新论文（cs.AI 等分类）。

官方 API 稳定且不反爬：export.arxiv.org/api/query
"""
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .base import BaseScraper

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}

DEFAULT_CATEGORY = "cs.AI"  # 可切换 cs.LG / cs.CL


class ArxivScraper(BaseScraper):
    name = "arxiv"
    display_name = "arXiv"

    def scrape(self, keyword: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 arXiv 最新论文。keyword 可选（如 "large language model"）。"""
        if keyword:
            query = f'cat:{DEFAULT_CATEGORY} AND all:"{keyword}"'
        else:
            query = f"cat:{DEFAULT_CATEGORY}"
        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": limit,
        }
        content = self._request(ARXIV_API, params=params)
        root = ET.fromstring(content)

        items: List[Dict[str, Any]] = []
        for entry in root.findall("atom:entry", NS):
            title = " ".join((entry.findtext("atom:title", default="", namespaces=NS) or "").split())
            url = entry.findtext("atom:id", default="", namespaces=NS).strip()
            published = entry.findtext("atom:published", default="", namespaces=NS).strip()
            summary = " ".join(
                (entry.findtext("atom:summary", default="", namespaces=NS) or "").split()
            )[:300]
            items.append(
                {
                    "title": title,
                    "url": url,
                    "source": self.display_name,
                    "published_at": published,
                    "summary": summary,
                    "tags": [DEFAULT_CATEGORY],
                }
            )
        return items
