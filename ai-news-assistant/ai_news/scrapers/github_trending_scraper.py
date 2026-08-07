"""GitHub Trending Scraper：抓取本周热门开源项目。"""
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseScraper

GITHUB_TRENDING = "https://github.com/trending"


def _title_tags(repo: str) -> List[str]:
    """从仓库名提取标签（如 owner/name → [owner, name]）；停用词由管道统一过滤。"""
    return re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", repo)[:2]


class GithubTrendingScraper(BaseScraper):
    name = "github_trending"
    display_name = "GitHub Trending"

    def scrape(self, keyword: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 GitHub Trending（按周维度，可选语言 keyword，如 python/ai）。"""
        url = GITHUB_TRENDING
        if keyword:
            url += f"/{keyword}"
        url += "?since=weekly"

        content = self._request(url)
        soup = BeautifulSoup(content, "html.parser")

        items: List[Dict[str, Any]] = []
        for article in soup.select("article.Box-row")[:limit]:
            h2 = article.select_one("h2 a")
            if not h2:
                continue
            repo = h2.get("href", "").strip("/")
            desc_el = article.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            rel_time = article.select_one("relative-time")
            updated = rel_time.get("datetime", "") if rel_time else ""
            star_el = article.select_one("a[href$='/stargazers']")
            stars = star_el.get_text(strip=True).replace(",", "") if star_el else "0"

            items.append(
                {
                    "title": repo,
                    "url": f"https://github.com/{repo}",
                    "source": self.display_name,
                    "published_at": updated,
                    "summary": f"描述: {desc or '无'}（本周 Star: {stars}）",
                    "tags": _title_tags(repo),
                }
            )
        return items
