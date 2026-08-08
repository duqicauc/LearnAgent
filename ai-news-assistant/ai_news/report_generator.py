"""HTML 报告生成器：任务 JSON → 交互式单文件 HTML（Jinja2 + Chart.js）。

支持两种模式：
- full：完整报告（卡片 + 图表 + 趋势）
- quick：轻量报告（仅标题/摘要/条目卡片，用于快速浏览）

O1 优化新增：概览指标、本期速览（TLDR）、
三级置信度（报告级质量区 / 总结级自评 / 条目级角标）、默认按时间排序。

归档：维护 data/reports/index.json（历史任务清单）并渲染 archive.html 浏览页。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

from .core.evaluator import Evaluator
from .core.tracing import DATA_DIR

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
OUTPUT_DIR = DATA_DIR / "reports"

# 来源可信度（条目级置信度因子①）
SOURCE_RELIABILITY: Dict[str, float] = {
    "HuggingFace": 1.0,
    "arXiv": 1.0,
    "GitHub Trending": 0.8,
    "量子位": 0.8,
    "WIRED AI": 0.8,
}

# 来源站点主页（数据来源表链接）
SOURCE_LINKS: Dict[str, str] = {
    "HuggingFace": "https://huggingface.co",
    "arXiv": "https://arxiv.org",
    "GitHub Trending": "https://github.com/trending",
    "量子位": "https://www.qbitai.com",
    "WIRED AI": "https://www.wired.com/tag/artificial-intelligence",
}

# 无障碍色板（Viridis 系，色盲友好，明暗主题通用）
VIRIDIS = ["#440154", "#46327e", "#365c8d", "#277f8e", "#1fa187", "#4ac16d"]


def _parse_dt(value: Any) -> Optional[datetime]:
    """解析 published_at（ISO 格式）→ UTC datetime；失败返回 None。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _source_index(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """url → 抓取条目，用于把来源/时间/多源信息合并进报告条目。"""
    return {str(it.get("url")): it for it in items}


def _item_confidence(item: Dict[str, Any]) -> Dict[str, Any]:
    """条目级置信度 = 来源可信度×0.5 + 时效×0.3 + 多源交叉×0.2。

    规则置信度（不依赖 LLM），保证前端始终有值。
    """
    rel = SOURCE_RELIABILITY.get(item.get("source") or "", 0.5)
    dt = _parse_dt(item.get("published_at"))
    if dt is None:
        fresh = 0.7  # 无时间戳视为「近期」
    else:
        age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        fresh = 1.0 if age_days <= 1 else (0.8 if age_days <= 3 else 0.6)
    mentions = int(item.get("mentions") or 1)
    cross = 1.0 if mentions >= 2 else 0.8
    score = round(rel * 0.5 + fresh * 0.3 + cross * 0.2, 2)
    level = "高" if score >= 0.85 else ("中" if score >= 0.6 else "低")
    return {
        "score": score,
        "level": level,
        "detail": {"来源": f"{item.get('source') or '未标注'}（{rel:.1f}）",
                   "时效": "近期" if dt is None else f"{age_days:.1f} 天",
                   "多源提及": f"{mentions} 个来源"},
    }


def _enrich_items_with_source(report: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合并抓取数据（来源/时间/多源/置信度）进报告条目，并按时间降序（近期优先）。"""
    index = _source_index(items)
    now = datetime.now(timezone.utc)
    enriched = dict(report)
    sections = []
    for sec in report.get("sections", []):
        sec_items = []
        for item in sec.get("items", []):
            item = dict(item)
            url = str(item.get("url") or "")
            raw = index.get(url)
            if raw:
                item.setdefault("source", raw.get("source") or "未知")
                item["published_at"] = raw.get("published_at") or ""
                item["is_recent"] = bool(raw.get("is_recent", not item.get("published_at")))
                item["mentions"] = int(raw.get("mentions") or 1)
                item["tags"] = raw.get("tags") or []
            else:
                item["source"] = item.get("source") or "未知"
                item["published_at"] = item.get("published_at") or ""
                item["is_recent"] = True
                item["mentions"] = 1
                item["tags"] = []
            item["impact"] = item.get("impact") or ""
            conf = _item_confidence(item)
            item["confidence_score"] = conf["score"]
            item["confidence_level"] = conf["level"]
            item["confidence_detail"] = conf["detail"]
            sec_items.append(item)
        # 组内按时间降序：无时间戳视为「现在」（近期优先）
        sec_items.sort(
            key=lambda it: _parse_dt(it.get("published_at")) or now,
            reverse=True,
        )
        sections.append({**sec, "items": sec_items})
    enriched["sections"] = sections
    return enriched


def _narrative(kind: str, labels: List[str], values: List[int]) -> tuple:
    """为图表生成叙事性标题 + 一句话结论（标题直接给答案）。

    :return: (title, conclusion)
    """
    if not labels or not values:
        return "暂无数据", "本期无可用数据。"
    top_idx = max(range(len(values)), key=lambda i: values[i])
    top_label, top_val = labels[top_idx], values[top_idx]
    if kind == "source":
        return (
            f"来源分布：{top_label} 贡献最多",
            f"共 {sum(values)} 条信息来自 {len(labels)} 个站点，{top_label} 占 {top_val} 条（{round(top_val / sum(values) * 100)}%）。",
        )
    if kind == "category":
        return (
            f"类别占比：{top_label} 是本期主旋律",
            f"{top_label} 类有 {top_val} 条，是本期最活跃的方向，其次为{'、'.join(labels[1:3])}。",
        )
    if kind == "tag":
        return (
            f"标签频次：{top_label} 出现最多",
            f"「{top_label}」被提及 {top_val} 次，反映本期技术热点集中在 {top_label} 相关方向。",
        )
    # trend
    if len(labels) >= 2:
        first, last = values[0], values[-1]
        if last > first:
            delta = "上升"
        elif last < first:
            delta = "回落"
        else:
            delta = "持平"
        return (
            f"时间趋势：{labels[-1]} 信息量{delta}",
            f"从 {labels[0]} 到 {labels[-1]}，每日条目从 {first} 条变化为 {last} 条，整体{delta}。",
        )
    return (
        f"时间趋势：{labels[-1]} 单日 {values[0]} 条",
        f"本期数据集中在 {labels[-1]}，共 {values[0]} 条。",
    )


def build_chart_data(task_output: Dict[str, Any]) -> Dict[str, Any]:
    """构建 Chart.js 数据：来源分布 / 类别占比 / 标签频次 / 时间趋势 + 叙事标题与结论。"""
    stats = task_output.get("stats", {})
    analysis = task_output.get("analysis", {})

    by_source = stats.get("by_source", {})
    source_labels = list(by_source.keys())
    source_values = list(by_source.values())

    categories = analysis.get("categories", [])
    category_labels = [c.get("name", "其他") for c in categories]
    category_values = [int(c.get("count") or 1) for c in categories]
    if not category_labels:
        category_labels = source_labels
        category_values = source_values

    by_tag = stats.get("by_tag", {})
    top_tags = list(by_tag.items())[:12]
    tag_labels = [k for k, _ in top_tags]
    tag_values = [v for _, v in top_tags]

    src_title, src_concl = _narrative("source", source_labels, source_values)
    cat_title, cat_concl = _narrative("category", category_labels, category_values)
    tag_title, tag_concl = _narrative("tag", tag_labels, tag_values)

    return {
        "source": {
            "labels": source_labels, "values": source_values,
            "title": src_title, "conclusion": src_concl, "colors": VIRIDIS[:max(len(source_labels), 1)],
        },
        "category": {
            "labels": category_labels, "values": category_values,
            "title": cat_title, "conclusion": cat_concl, "colors": VIRIDIS,
        },
        "tag": {
            "labels": tag_labels, "values": tag_values,
            "title": tag_title, "conclusion": tag_concl, "colors": VIRIDIS[:max(len(tag_labels), 1)],
        },
        "trend": build_trend(task_output.get("items", [])),
    }


def build_trend(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """时间趋势：按 published_at 按日聚合条目量（无时间戳条目不计入）。"""
    from collections import Counter
    days: Counter = Counter()
    for it in items:
        dt = _parse_dt(it.get("published_at"))
        if dt is not None:
            days[dt.date().isoformat()] += 1
    labels = sorted(days.keys())
    values = [days[l] for l in labels]
    enabled = len(labels) >= 2  # 单点无趋势意义，隐藏
    if enabled:
        title, conclusion = _narrative("trend", labels, values)
    else:
        title, conclusion = "时间趋势", "本期时间戳不足，无法展示趋势。"
    return {
        "labels": labels,
        "values": values,
        "enabled": enabled,
        "title": title,
        "conclusion": conclusion,
        "colors": VIRIDIS[3],
    }


def build_sources(stats: Dict[str, Any]) -> Dict[str, Any]:
    """数据来源表：每站点条目数/占比/链接 + 去重统计。"""
    by_source = stats.get("by_source", {})
    deduped = int(stats.get("deduped") or 0)
    total = int(stats.get("total") or 0)
    rows = [
        {
            "name": name,
            "count": count,
            "pct": round(count / total * 100) if total else 0,
            "link": SOURCE_LINKS.get(name, ""),
        }
        for name, count in by_source.items()
    ]
    raw_total = deduped + total
    return {
        "rows": rows,
        "total": total,
        "deduped": deduped,
        "dedup_rate": round(deduped / raw_total * 100) if raw_total else 0,
    }


def build_freshness(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """时效统计：平均时效天数、24h 内占比、有发布时间条数。"""
    now = datetime.now(timezone.utc)
    ages: List[float] = []
    fresh_24h = 0
    for it in items:
        dt = _parse_dt(it.get("published_at"))
        if dt is None:
            continue
        age = max(0.0, (now - dt).total_seconds() / 86400.0)
        ages.append(age)
        if age <= 1.0:
            fresh_24h += 1
    total = len(items)
    if not ages:
        return {"dated": 0, "total": total, "avg_days": None, "fresh_24h": 0, "fresh_pct": 0}
    return {
        "dated": len(ages),
        "total": total,
        "avg_days": round(sum(ages) / len(ages), 1),
        "fresh_24h": fresh_24h,
        "fresh_pct": round(fresh_24h / total * 100),
    }


def build_overview(stats: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """本期概览指标：条目总数 / 来源数 / 时效跨度 / 热词 Top3。"""
    dates = [dt for it in items if (dt := _parse_dt(it.get("published_at")))]
    if len(dates) >= 2:
        span_days = (max(dates) - min(dates)).days + 1
        if span_days < 30:
            span = f"{span_days} 天"
        else:
            span = f"约 {round(span_days / 30)} 个月"
    else:
        span = "本期"
    fresh = build_freshness(items)
    by_source = stats.get("by_source", {})
    return {
        "total": stats.get("total", len(items)),
        "sources_count": len(by_source),
        "sources": list(by_source.keys()),
        "span": span,
        "fresh_24h": fresh["fresh_pct"],
        "hot_keywords": stats.get("top_keywords", [])[:3],
    }


def build_quality(task_output: Dict[str, Any]) -> Dict[str, Any]:
    """报告级质量区：Evaluator 综合评分 + 数据新鲜度 + 覆盖度。"""
    scores = Evaluator().evaluate(task_output)
    overall = scores["overall"]
    level = "优" if overall >= 0.85 else ("良" if overall >= 0.7 else "中")
    fresh = build_freshness(task_output.get("items", []))
    if fresh["dated"]:
        line = (
            f"平均时效 {fresh['avg_days']} 天 · 24h 内占比 "
            f"{fresh['fresh_pct']}%（{fresh['dated']}/{fresh['total']} 条有发布时间）"
        )
    else:
        line = "本期条目均无发布时间，已统一标注为「近期」"
    plan = task_output.get("plan") or {}
    planned = plan.get("sites") or []
    done = len(task_output.get("stats", {}).get("by_source", {}))
    coverage_note = f"成功站点 {done}/{len(planned)}" if planned else f"覆盖 {done} 个来源"
    return {
        "score": overall,
        "level": level,
        "line": line,
        "coverage_note": coverage_note,
        "scores": scores,
    }


def build_summary_confidence(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """总结级置信度：LLM 自评 confidence 优先，规则兜底。"""
    conf = analysis.get("confidence")
    if isinstance(conf, (int, float)) and 0 <= conf <= 1:
        return {
            "score": round(float(conf), 2),
            "reason": analysis.get("reason") or "LLM 自评",
            "llm": True,
        }
    base = 0.5
    if analysis.get("categories"):
        base += 0.15
    if analysis.get("trends"):
        base += 0.1
    if analysis.get("tldr"):
        base += 0.1
    if analysis.get("_degraded"):
        base -= 0.2
    return {
        "score": round(min(max(base, 0.0), 1.0), 2),
        "reason": "基于结构与覆盖度的规则估算",
        "llm": False,
    }


def generate_report(
    task_output: Dict[str, Any],
    mode: str = "full",
) -> Path:
    """渲染 HTML 报告并落盘 data/reports/，返回文件路径。"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("report.html")

    items = task_output.get("items", [])
    analysis = task_output.get("analysis", {})
    stats = task_output.get("stats", {})
    report = _enrich_items_with_source(task_output.get("report", {}), items)

    render_ctx: Dict[str, Any] = {
        "report": report,
        "analysis": analysis,
        "stats": stats,
        "charts": build_chart_data(task_output),
        "sources": build_sources(stats),
        "overview": build_overview(stats, items),
        "quality": build_quality(task_output),
        "summary_conf": build_summary_confidence(analysis),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
    }

    html = template.render(**render_ctx)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"ai_news_{ts}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# ── 归档索引与浏览页（数据全量保留 + 长期记忆的结构化清单）──
# 路径在函数内取 OUTPUT_DIR 动态拼接，便于测试重定向目录


def _archive_index() -> Path:
    return OUTPUT_DIR / "index.json"


def _archive_page() -> Path:
    return OUTPUT_DIR / "archive.html"


def _evaluation_score(task_id: Optional[str]) -> Optional[float]:
    """读取 evaluation_<task_id>.json 的综合评分；无评估文件返回 None。"""
    if not task_id:
        return None
    path = OUTPUT_DIR / f"evaluation_{task_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("score", {}).get("overall")
    except (OSError, ValueError):
        return None


def update_archive_index(
    task_output: Dict[str, Any],
    html_path: Optional[Path] = None,
) -> Path:
    """维护归档索引 data/reports/index.json，并刷新 archive.html 浏览页。

    每期任务一条记录：时间 / 标题 / 摘要 / 条目数 / 来源 / HTML / 评估分。
    同 task_id 覆盖（CLI 生成 HTML 后可补写文件名）。返回 index.json 路径。
    """
    index: Dict[str, Any] = {"reports": []}
    index_path = _archive_index()
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {"reports": []}
    record = {
        "task_id": task_output.get("task_id"),
        "created_at": task_output.get("created_at", ""),
        "title": task_output.get("report", {}).get("title", ""),
        "summary": task_output.get("analysis", {}).get("summary", ""),
        "item_count": task_output.get("stats", {}).get("total", 0),
        "sources": sorted(task_output.get("stats", {}).get("by_source", {}).keys()),
        "html": Path(html_path).name if html_path else "",
        "score": _evaluation_score(task_output.get("task_id")),
    }
    index["reports"] = [
        r for r in index.get("reports", []) if r.get("task_id") != record["task_id"]
    ]
    index["reports"].append(record)
    index["reports"].sort(key=lambda r: r.get("created_at", ""), reverse=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    generate_archive()  # 索引更新后同步刷新浏览页
    return index_path


def generate_archive() -> Path:
    """由归档索引渲染 data/reports/archive.html（历史报告浏览页，双击可读）。"""
    index_path = _archive_index()
    if not index_path.exists():
        raise FileNotFoundError("归档索引不存在，请先运行一次任务")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    reports = index.get("reports", [])
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    html = env.get_template("archive.html").render(
        reports=reports,
        total=len(reports),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    page = _archive_page()
    page.write_text(html, encoding="utf-8")
    return page
