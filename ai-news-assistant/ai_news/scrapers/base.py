"""BaseScraper 基类：统一 UA、超时、重试、请求间隔、错误分类。

所有站点抓取器继承本类，实现 scrape() 返回统一的 Item 结构：
    {title, url, source, published_at, summary, tags}
"""
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

MIN_REQUEST_INTERVAL = 1.0   # 每站点请求间隔 ≥ 1s（礼貌抓取）
REQUEST_TIMEOUT = 15         # 单次请求超时（秒）
MAX_RETRIES = 2              # 失败重试次数

# 站点白名单（安全防护：仅允许 SPEC §2 列出的域名）
ALLOWED_SITE_DOMAINS = {
    "huggingface": "hf-mirror.com",
    "github_trending": "github.com",
    "arxiv": "arxiv.org",
    "qbitai": "qbitai.com",
    "wired": "wired.com",
}


class ScrapeError(Exception):
    """抓取异常（分类：反爬/HTTP/网络/解析）。"""


class BaseScraper(ABC):
    """站点抓取器基类。"""

    name: str = "base"
    display_name: str = "Base"

    def __init__(
        self,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = REQUEST_TIMEOUT,
        interval: float = MIN_REQUEST_INTERVAL,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)
        self.timeout = timeout
        self.interval = interval
        self._last_request_at = 0.0

    # ── 请求基础设施 ──
    def _request(self, url: str, **kwargs: Any) -> bytes:
        """带请求间隔、重试、错误分类的 GET 请求。"""
        self._throttle()
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                return resp.content
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else -1
                if status == 403:
                    raise ScrapeError(f"{self.name}: 反爬拦截(403) url={url}") from exc
                if attempt < MAX_RETRIES:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise ScrapeError(f"{self.name}: HTTP {status} url={url}") from exc
            except requests.exceptions.RequestException as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise ScrapeError(
                    f"{self.name}: 请求失败 {type(exc).__name__} url={url}"
                ) from exc

    def _throttle(self) -> None:
        """保证请求间隔 ≥ interval。"""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last_request_at = time.monotonic()

    # ── 子类实现 ──
    @abstractmethod
    def scrape(self, keyword: str = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取并返回 Item 列表。失败时抛 ScrapeError，由调用方降级处理。"""
