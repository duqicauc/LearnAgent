"""WIRED AI Scraper：抓取国际 AI 行业资讯（服务端渲染，结构稳定）。

替代说明：原计划 TechCrunch 被 Cloudflare Turnstile 拦截无法静态抓取，
改用同属 SPEC「国际行业媒体」类别的 WIRED AI 频道。
"""
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseScraper

WIRED_AI = "https://www.wired.com/tag/artificial-intelligence/"


def _title_tags(title: str) -> List[str]:
    """从标题提取英文关键词作标签（如 Anthropic、Claude）；停用词由管道统一过滤。"""
    return re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", title)[:3]


class WiredScraper(BaseScraper):
    name = "wired"
    display_name = "WIRED AI"

    def scrape(self, keyword: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 WIRED AI 频道最新文章。"""
        content = self._request(WIRED_AI)
        soup = BeautifulSoup(content, "html.parser")

        items: List[Dict[str, Any]] = []
        seen: set = set()
        # 文章链接为相对路径 /story/<slug>，标题在 h2/h3 内
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href.startswith("/story/"):
                continue
            h = a.find(["h2", "h3"])
            if not h:
                continue
            title = h.get_text(strip=True)
            if not title or len(title) < 12 or href in seen:
                continue
            seen.add(href)

            time_el = a.find("time")
            published = time_el.get("datetime", "") if time_el else ""

            items.append(
                {
                    "title": title,
                    "url": "https://www.wired.com" + href,
                    "source": self.display_name,
                    "published_at": published,
                    "summary": "",
                    "tags": _title_tags(title),
                }
            )
            if len(items) >= limit:
                break
        return items
