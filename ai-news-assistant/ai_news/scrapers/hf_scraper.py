"""HuggingFace Scraper：使用官方公开 API 获取热门模型。

API: huggingface.co/api/models?sort=trendingScore&direction=-1
说明：国内网络访问 huggingface.co 不稳定，默认走官方国内镜像 hf-mirror.com
（同一套 API，可配置 HF_API_BASE 覆盖）。
"""
import json
import os
from typing import Any, Dict, List, Optional

from .base import BaseScraper

HF_API_MODELS = os.getenv("HF_API_BASE", "https://hf-mirror.com") + "/api/models"


class HuggingFaceScraper(BaseScraper):
    name = "huggingface"
    display_name = "HuggingFace"

    def scrape(self, keyword: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """抓取 HuggingFace 热门模型（按趋势分排序）。"""
        params: Dict[str, Any] = {
            "sort": "trendingScore",
            "direction": "-1",
            "limit": limit,
        }
        if keyword:
            params["search"] = keyword

        content = self._request(HF_API_MODELS, params=params)
        models = json.loads(content)

        items: List[Dict[str, Any]] = []
        for m in models:
            model_id = m.get("id") or m.get("modelId") or ""
            items.append(
                {
                    "title": model_id,
                    "url": f"https://huggingface.co/{model_id}",
                    "source": self.display_name,
                    "published_at": (m.get("createdAt") or ""),
                    "summary": (
                        f"下载量 {m.get('downloads', 0)}，点赞 {m.get('likes', 0)}，"
                        f"任务类型 {m.get('pipeline_tag') or '未知'}"
                    ),
                    "tags": (m.get("tags") or [])[:5],
                }
            )
        return items
