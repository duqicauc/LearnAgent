"""工具 JSON Schema 定义。

- M1：占位工具 get_cached_data（缓存查询）
- M3：5 个抓取工具 fetch_*（对应 5 个已实测站点）
"""
import json
from typing import Callable, List, Tuple

from .fetchers import (
    fetch_arxiv,
    fetch_github_trending,
    fetch_huggingface,
    fetch_qbitai,
    fetch_wired,
)

# ── 占位工具：缓存查询（M2 实现真实缓存逻辑） ──
GET_CACHED_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_cached_data",
        "description": "查询指定站点/关键词的抓取缓存数据。若命中缓存可直接使用，避免重复抓取。",
        "parameters": {
            "type": "object",
            "properties": {
                "site": {
                    "type": "string",
                    "description": "站点标识，如 huggingface、arxiv、github_trending",
                },
                "keyword": {
                    "type": "string",
                    "description": "检索关键词，可为空",
                },
            },
            "additionalProperties": False,
        },
    },
}


def get_cached_data(site: str = None, keyword: str = None) -> str:
    """M1 占位实现：缓存逻辑将在 M2（core/cache.py）落地。"""
    return json.dumps(
        {
            "cache": [],
            "hit": False,
            "note": "M1 骨架阶段，缓存逻辑将在 M2 实现",
        },
        ensure_ascii=False,
    )


# M1 内置工具集（函数, schema）
BUILTIN_TOOLS = [(get_cached_data, GET_CACHED_DATA_SCHEMA)]


# ── M3 抓取工具：5 个站点，统一参数模式 ──
def _fetch_schema(name: str, desc: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "检索关键词，可为空"},
                    "limit": {"type": "integer", "description": "返回条数上限，默认 10"},
                },
                "additionalProperties": False,
            },
        },
    }


FETCH_TOOLS: List[Tuple[Callable, dict]] = [
    (fetch_huggingface, _fetch_schema("fetch_huggingface", "抓取 HuggingFace 热门模型（AI 开源模型动态）")),
    (fetch_github_trending, _fetch_schema("fetch_github_trending", "抓取 GitHub Trending 热门开源项目")),
    (fetch_arxiv, _fetch_schema("fetch_arxiv", "抓取 arXiv cs.AI 最新论文")),
    (fetch_qbitai, _fetch_schema("fetch_qbitai", "抓取量子位中文 AI 产业资讯")),
    (fetch_wired, _fetch_schema("fetch_wired", "抓取 WIRED AI 频道国际行业资讯")),
]
