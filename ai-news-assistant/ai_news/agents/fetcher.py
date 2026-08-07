"""抓取 Agent：并行调度多站点抓取，单站点失败隔离。

知识点：多智能体分工 + 并行调度（ThreadPoolExecutor）+ 失败隔离降级。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from ..core.tracing import Tracer
from ..tools.fetchers import fetch_site_items


class FetcherAgent:
    """负责按计划并行抓取各站点数据。"""

    def __init__(self) -> None:
        self.tracer = Tracer.get()

    def fetch(
        self,
        sites: List[str],
        keyword: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """并行抓取多站点，返回 {site: [items]}。失败站点降级为空列表。"""
        self.tracer.step("fetcher", "fetch_start", {"sites": sites, "limit": limit})
        results: Dict[str, List[Dict[str, Any]]] = {}
        workers = max(1, min(len(sites), 5))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_site_items, site, keyword, limit): site
                for site in sites
            }
            for future in as_completed(futures):
                site = futures[future]
                try:
                    results[site] = future.result()
                except Exception as exc:  # noqa: BLE001 - 失败隔离
                    self.tracer.step("fetcher", "site_failed", {"site": site, "error": str(exc)})
                    results[site] = []

        ok_sites = [s for s, v in results.items() if v]
        total = sum(len(v) for v in results.values())
        self.tracer.step(
            "fetcher", "fetch_done",
            {"sites_ok": ok_sites, "total_items": total, "failed": len(sites) - len(ok_sites)},
        )
        return results
