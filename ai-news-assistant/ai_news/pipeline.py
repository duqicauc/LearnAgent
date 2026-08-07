"""五阶段数据管道：采集 → 清洗 → 去重 → 标准化 → 聚合。

- clean:    过滤空字段、截断超长文本
- dedup:    指纹去重（URL + 标题哈希），多源相同信息自动合并
- normalize: 统一 Item 字段结构
- aggregate: 统计汇总（条目数、来源分布、热词）
"""
import hashlib
import re
from collections import Counter
from typing import Any, Dict, List, Optional

# Item 标准结构
ITEM_KEYS = ("title", "url", "source", "published_at", "summary", "tags")
MAX_SUMMARY_LEN = 300

# 停用词：无信息量的标签/热词（ai、cn 等），统一过滤覆盖所有来源
STOP_WORDS = {
    "a", "an", "the", "of", "to", "and", "or", "for", "with", "in", "on", "at",
    "by", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "from", "about", "into", "over", "under", "after", "before",
    "as", "but", "not", "no", "up", "down", "out", "off", "than", "then", "now",
    "ai", "ml", "cn", "api", "app", "apps", "industry", "github", "trending",
    # 标题中常见的弱信息词（英文媒体标题首词）
    "can", "could", "will", "would", "should", "says", "said", "say", "how",
    "why", "what", "when", "where", "who", "which", "get", "got", "make",
    "made", "use", "using", "new", "best", "top", "most", "more", "all",
    "don", "won", "let", "just", "one", "two",
}


def _keep_tag(tag: str) -> bool:
    """标签可用性：过短、纯数字/符号、停用词均剔除。"""
    t = tag.strip()
    if len(t) < 2:
        return False
    if re.fullmatch(r"[\d\W_]+", t):
        return False
    return t.lower() not in STOP_WORDS


def normalize(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """标准化单条 Item：补齐缺失字段、限制摘要长度。"""
    norm: Dict[str, Any] = {k: item.get(k) for k in ITEM_KEYS}
    norm.setdefault("title", "").strip()
    norm["url"] = (item.get("url") or "").strip()
    norm["source"] = (item.get("source") or "").strip()
    norm["published_at"] = (item.get("published_at") or "").strip()
    norm["summary"] = (item.get("summary") or "").strip()[:MAX_SUMMARY_LEN]
    raw_tags = item.get("tags") or []
    norm["tags"] = [str(t).strip() for t in raw_tags if _keep_tag(str(t))][:8]
    # 时间兜底：无发布时间的条目标记为「近期」，供前端/置信度计算使用
    norm["is_recent"] = not bool(norm["published_at"])
    return norm


def clean(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """清洗：剔除缺 title/url 的脏数据。"""
    cleaned = []
    for it in items:
        norm = normalize(it)
        if norm and norm["title"] and norm["url"]:
            cleaned.append(norm)
    return cleaned


def _fingerprint(item: Dict[str, Any]) -> str:
    """指纹 = hash(url) 或 hash(title)，用于去重。"""
    basis = (item["url"] or item["title"]).lower()
    return hashlib.md5(basis.encode("utf-8")).hexdigest()


def dedup(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 URL/标题指纹去重，保留首次出现，并统计多源提及。

    保留条目附加字段：
    - mentions: 该信息被几个来源提及（≥2 视为多源交叉验证）
    - sources:  提及该信息的来源名列表
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for it in items:
        fp = _fingerprint(it)
        if fp in seen:
            seen[fp].setdefault("sources", set()).add(it.get("source") or "unknown")
        else:
            kept = dict(it)
            kept["mentions"] = 1
            kept["sources"] = {it.get("source") or "unknown"}
            seen[fp] = kept
    result = []
    for it in seen.values():
        it["mentions"] = len(it["sources"])
        it["sources"] = sorted(it["sources"])
        result.append(it)
    return result


def _extract_keywords(title: str, tags: List[str]) -> List[str]:
    """简单热词提取：标题英文词（含模型名/公司名）+ 标签，均过滤停用词。

    中文标题词不纳入：无分词器时简单正则只能切出整句或截断词，
    而中文标题里的有效实体（GPT、Claude 等）通常已是英文词。
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9.\-]*", title)
    # 复用标签过滤：剔除停用词、单字符（如 's）、纯数字、超长串（如 GitHub 全名仓库）
    kept = [w for w in words if _keep_tag(w) and len(w) <= 24][:6]
    kept += [t for t in tags if _keep_tag(t)]
    return kept


def aggregate(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """聚合统计：总条目、来源分布、标签分布、热词 Top。"""
    source_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    keyword_counter: Counter = Counter()
    for it in items:
        source_counter[it["source"] or "unknown"] += 1
        tag_counter.update(it["tags"])
        keyword_counter.update(_extract_keywords(it["title"], it["tags"]))
    return {
        "total": len(items),
        "by_source": dict(source_counter),
        "by_tag": dict(tag_counter.most_common(20)),
        "top_keywords": [w for w, _ in keyword_counter.most_common(15)],
    }


def run_pipeline(
    raw_by_source: Dict[str, List[Dict[str, Any]]],
    dedup_enabled: bool = True,
) -> Dict[str, Any]:
    """编排五阶段管道，返回 {items, stats}。

    :param raw_by_source: {source_name: [raw_item, ...]}
    """
    # ① 采集（调用方已完成）→ ② 清洗 → ④ 标准化（在 clean 内）
    all_items: List[Dict[str, Any]] = []
    for source, items in raw_by_source.items():
        for it in items:
            it.setdefault("source", source)
        all_items.extend(clean(items))

    # ③ 去重
    before = len(all_items)
    if dedup_enabled:
        all_items = dedup(all_items)

    # ⑤ 聚合
    stats = aggregate(all_items)
    stats["deduped"] = before - len(all_items)

    return {"items": all_items, "stats": stats}
