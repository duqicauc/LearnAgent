"""TTL 缓存：站点抓取结果缓存，避免重复抓取、降低源站压力。

数据落盘 data/cache/<key>.json，带时间戳与 TTL 判定。
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .tracing import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
DEFAULT_TTL = 3600  # 默认缓存 1 小时


class TTLCache:
    """本地 JSON 文件 TTL 缓存。"""

    def __init__(self, cache_dir: Path = CACHE_DIR, ttl: int = DEFAULT_TTL) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self._hits = 0
        self._misses = 0

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self.cache_dir / f"{safe}.json"

    def get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """命中且未过期返回缓存列表，否则返回 None。"""
        path = self._path(key)
        if not path.exists():
            self._misses += 1
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                record: Dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._misses += 1
            return None

        if time.time() - record["ts"] > self.ttl:
            self._misses += 1
            return None
        self._hits += 1
        return record["data"]

    def set(self, key: str, data: List[Dict[str, Any]]) -> None:
        """写入缓存。"""
        record = {"ts": time.time(), "data": data}
        with open(self._path(key), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    @property
    def stats(self) -> Dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}
