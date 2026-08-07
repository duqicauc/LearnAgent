"""M2 验收脚本：逐个运行 5 个 Scraper → 五阶段管道 → 缓存命中验证。

运行方式：
    python test_scrapers.py
"""
import json
import time

from ai_news.core.cache import TTLCache
from ai_news.pipeline import run_pipeline
from ai_news.scrapers.arxiv_scraper import ArxivScraper
from ai_news.scrapers.base import BaseScraper, ScrapeError
from ai_news.scrapers.github_trending_scraper import GithubTrendingScraper
from ai_news.scrapers.hf_scraper import HuggingFaceScraper
from ai_news.scrapers.qbitai_scraper import QbitaiScraper
from ai_news.scrapers.wired_scraper import WiredScraper

SCRAPERS: list[BaseScraper] = [
    HuggingFaceScraper(),
    GithubTrendingScraper(),
    ArxivScraper(),
    QbitaiScraper(),
    WiredScraper(),
]


def fetch_with_cache(name: str, scraper: BaseScraper, limit: int = 10) -> list[dict]:
    """带 TTL 缓存抓取：命中缓存不发起网络请求。"""
    cache = TTLCache(ttl=300)
    key = f"{name}:latest"
    cached = cache.get(key)
    if cached is not None:
        print(f"  [缓存命中] {name} -> {len(cached)} 条")
        return cached
    items = scraper.scrape(limit=limit)
    cache.set(key, items)
    print(f"  [已抓取] {name} -> {len(items)} 条（已写入缓存）")
    return items


def main() -> None:
    print("=" * 60)
    print("M2 验收：Scraper + 数据管道 + 缓存")
    print("=" * 60)

    raw_by_source: dict[str, list[dict]] = {}
    for scraper in SCRAPERS:
        try:
            items = fetch_with_cache(scraper.name, scraper)
            raw_by_source[scraper.name] = items
        except ScrapeError as exc:
            print(f"  [⚠️ 失败降级] {scraper.name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [⚠️ 未知错误] {scraper.name}: {type(exc).__name__}: {exc}")
        time.sleep(0.5)

    print("\n--- 五阶段管道 ---")
    result = run_pipeline(raw_by_source)
    stats = result["stats"]
    print(f"总条目: {stats['total']} | 去重: {stats['deduped']} | 来源分布: {stats['by_source']}")
    print(f"Top 热词: {stats['top_keywords'][:10]}")

    print("\n--- 示例条目 ---")
    for it in result["items"][:5]:
        print(f"  [{it['source']}] {it['title'][:55]}")

    # 缓存二次命中验证
    print("\n--- 缓存二次命中验证 ---")
    for scraper in SCRAPERS:
        cache = TTLCache(ttl=300)
        hits = cache.get(f"{scraper.name}:latest")
        print(f"  {scraper.name}: {'命中 ✅' if hits else '未命中'}")

    print("\nM2 验收完成 ✅")


if __name__ == "__main__":
    main()
