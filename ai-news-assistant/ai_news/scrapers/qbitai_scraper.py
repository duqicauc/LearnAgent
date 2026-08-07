"""量子位 Scraper：抓取中文 AI 资讯（服务端渲染，结构稳定）。

替代说明：原计划机器之心为 SPA（JS 渲染）无法静态抓取，
改用同属 SPEC「中文 AI 资讯」类别的量子位。
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseScraper

QBITAI_HOME = "https://www.qbitai.com/"


def _title_tags(title: str) -> List[str]:
    """从标题提取英文关键词作标签（如 GPT、Claude）；停用词由管道统一过滤。"""
    return re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", title)[:4]


def _url_date(url: str) -> str:
    """从文章 URL 提取近似发布时间：qbitai 链接形如 /2026/07/463297.html，
    只有年月无具体日期。本月文章近似为「今天」（首页内容均为近期发布），
    历史月份取该月 1 日（保守口径，避免未来时间）。
    """
    m = re.search(r"/(20\d{2})/(\d{2})/", url)
    if not m:
        return ""
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return ""
    now = datetime.now()
    if (year, month) == (now.year, now.month):
        return now.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{year}-{month:02d}-01T00:00:00"


class QbitaiScraper(BaseScraper):
    name = "qbitai"
    display_name = "量子位"

    def scrape(self, keyword: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取量子位首页最新资讯文章。"""
        content = self._request(QBITAI_HOME)
        soup = BeautifulSoup(content, "html.parser")

        items: List[Dict[str, Any]] = []
        seen: set = set()
        # 文章链接形如 https://www.qbitai.com/2026/07/463297.html
        for a in soup.select("a[href*='qbitai.com/20']"):
            title = a.get_text(strip=True)
            url = a.get("href", "")
            if not title or len(title) < 8 or url in seen:
                continue
            seen.add(url)
            items.append(
                {
                    "title": title,
                    "url": url,
                    "source": self.display_name,
                    "published_at": _url_date(url),
                    "summary": "",
                    "tags": _title_tags(title),
                }
            )
            if len(items) >= limit:
                break
        return items
