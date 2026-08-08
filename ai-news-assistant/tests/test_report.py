"""O4 验收脚本：报告渲染单测（Jinja2 渲染 / 图表数据 / 字段容错）。

运行方式：
    python tests/test_report.py   # 直接运行全部用例
    pytest tests/                 # 或从项目根跑 pytest

说明：所有用例把 report_generator.OUTPUT_DIR 指向临时目录，
不会触碰真实报告数据目录。
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根入 path

import ai_news.report_generator as rg

NOW = datetime.now(timezone.utc)


def sample_task_output(task_id: str = "aa001122", with_tldr: bool = True) -> dict:
    """构造一份结构完整的任务输出（与 main.py 落盘格式一致）。"""
    items = [
        {
            "title": f"模型发布第{i}篇",
            "url": f"https://example.com/a/{i}",
            "source": "HuggingFace" if i % 2 == 0 else "量子位",
            "published_at": (NOW - timedelta(hours=i * 5)).isoformat(),
            "tags": ["大模型"] if i % 2 == 0 else ["开源"],
            "mentions": 2 if i < 3 else 1,
            "summary": f"第{i}条摘要",
        }
        for i in range(8)
    ]
    analysis = {
        "summary": "本期聚焦大模型发布与开源动态。",
        "categories": [
            {"name": "大模型", "count": 5},
            {"name": "开源", "count": 3},
        ],
        "trends": ["多模态模型加速落地"],
        "confidence": 0.85,
        "reason": "覆盖多来源且结构完整",
    }
    if with_tldr:
        analysis["tldr"] = [
            {"point": "某大厂发布新一代模型", "why": "带动行业技术路线迁移", "title": "新一代模型"},
        ]
    return {
        "task_id": task_id,
        "created_at": NOW.isoformat(timespec="seconds"),
        "stats": {
            "total": len(items),
            "deduped": 2,
            "by_source": {"HuggingFace": 4, "量子位": 4},
            "by_tag": {"大模型": 4, "开源": 4},
            "top_keywords": ["模型", "开源", "多模态"],
        },
        "items": items,
        "analysis": analysis,
        "report": {
            "title": "AI 前沿动态测试报告",
            "summary": "测试摘要",
            "sections": [
                {"heading": "模型发布", "items": [
                    {"title": "模型发布第0篇", "url": "https://example.com/a/0", "note": "解读0", "impact": "值得关注"},
                    {"title": "模型发布第1篇", "url": "https://example.com/a/1", "note": "解读1", "impact": "行业风向"},
                ]},
                {"heading": "产业资讯", "items": [
                    {"title": "模型发布第2篇", "url": "https://example.com/a/2", "note": "解读2", "impact": "落地案例"},
                ]},
            ],
        },
    }


def _tmp_output_dir():
    """返回指向临时目录的 (临时路径, 恢复函数)。"""
    tmp = Path(tempfile.mkdtemp(prefix="an_report_test_"))
    original = rg.OUTPUT_DIR
    rg.OUTPUT_DIR = tmp

    def restore() -> None:
        rg.OUTPUT_DIR = original

    return tmp, original, restore


# ───────────────────────── 用例 ─────────────────────────

def test_chart_data():
    """build_chart_data：来源/类别/标签/趋势四图 + 叙事标题与结论。"""
    charts = rg.build_chart_data(sample_task_output())
    assert charts["source"]["labels"] == ["HuggingFace", "量子位"]
    assert charts["source"]["values"] == [4, 4]
    assert "贡献最多" in charts["source"]["title"]
    assert charts["source"]["conclusion"]
    assert charts["category"]["labels"] == ["大模型", "开源"]
    assert charts["tag"]["labels"] == ["大模型", "开源"]
    trend = charts["trend"]
    assert trend["enabled"] is True
    assert len(trend["labels"]) == len(trend["values"])


def test_item_confidence():
    """条目级置信度：来源×0.5+时效×0.3+多源×0.2，等级映射正确。"""
    conf = rg._item_confidence({
        "source": "HuggingFace", "published_at": (NOW - timedelta(hours=2)).isoformat(), "mentions": 3,
    })
    assert conf["score"] >= 0.85 and conf["level"] == "高"
    conf_low = rg._item_confidence({
        "source": "未知站点",
        "published_at": (NOW - timedelta(days=10)).isoformat(),
        "mentions": 1,
    })
    assert conf_low["level"] == "低"
    assert "未知站点" in conf_low["detail"]["来源"]


def test_generate_report_full():
    """完整模式渲染：文件生成、关键区块与交互元素存在。"""
    tmp, original, restore = _tmp_output_dir()
    try:
        out = rg.generate_report(sample_task_output(), mode="full")
        assert out.exists()
        html = out.read_text(encoding="utf-8")
        assert "AI 前沿动态测试报告" in html
        assert "本期速览（TLDR）" in html
        assert "置信度" in html and "conf-" in html
        assert "chartData" in html            # Chart.js 数据注入
        assert "@media print" in html          # 打印样式
        assert "no-chart" in html              # 图表降级逻辑
        assert 'aria-label="搜索条目"' in html
        assert 'role="tablist"' in html
        assert "热门 Top" not in html          # Top 榜已移除
        assert "跨期对比" not in html          # 跨期对比已移除
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def test_generate_report_minimal_tolerant():
    """字段缺失容错：无 tldr / 无 sections / 无 items 时仍能渲染。"""
    tmp, original, restore = _tmp_output_dir()
    try:
        minimal = {
            "task_id": "cc005566",
            "created_at": NOW.isoformat(timespec="seconds"),
            "stats": {"total": 0, "by_source": {}, "by_tag": {}},
            "analysis": {"summary": "空数据"},
            "report": {"title": "空报告", "summary": "无数据", "sections": []},
        }
        out = rg.generate_report(minimal, mode="quick")
        assert out.exists()
        html = out.read_text(encoding="utf-8")
        assert "空报告" in html
        assert "暂无条目数据" in html
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def test_generate_report_quick():
    """快速模式：正常渲染且不含独立趋势区块前提满足。"""
    tmp, original, restore = _tmp_output_dir()
    try:
        out = rg.generate_report(sample_task_output(), mode="quick")
        assert out.exists()
        html = out.read_text(encoding="utf-8")
        assert "AI 前沿动态测试报告" in html
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_sources_and_overview():
    """来源表与概览指标数据正确。"""
    task = sample_task_output()
    sources = rg.build_sources(task["stats"])
    assert len(sources["rows"]) == 2
    assert sources["total"] == 8 and sources["deduped"] == 2
    ov = rg.build_overview(task["stats"], task["items"])
    assert ov["total"] == 8 and ov["sources_count"] == 2
    assert ov["hot_keywords"] == ["模型", "开源", "多模态"]


def test_archive_index():
    """归档索引：新增记录、同 task_id 覆盖、archive.html 生成（数据全量保留）。"""
    tmp, original, restore = _tmp_output_dir()
    try:
        task = sample_task_output(task_id="aa001122")
        idx = rg.update_archive_index(task, html_path=Path("ai_news_test.html"))
        assert idx.exists()
        data = json.loads(idx.read_text(encoding="utf-8"))
        assert len(data["reports"]) == 1
        assert data["reports"][0]["html"] == "ai_news_test.html"
        assert data["reports"][0]["title"] == "AI 前沿动态测试报告"
        assert data["reports"][0]["item_count"] == 8

        # 同 task_id 覆盖：CLI 生成 HTML 后补写文件名
        rg.update_archive_index(
            sample_task_output(task_id="aa001122"), html_path=Path("ai_news_v2.html")
        )
        data = json.loads(idx.read_text(encoding="utf-8"))
        assert len(data["reports"]) == 1
        assert data["reports"][0]["html"] == "ai_news_v2.html"

        # 不同 task_id 追加
        rg.update_archive_index(sample_task_output(task_id="bb003344"))
        data = json.loads(idx.read_text(encoding="utf-8"))
        assert len(data["reports"]) == 2

        page = rg.generate_archive()
        assert page.exists()
        html = page.read_text(encoding="utf-8")
        assert "报告归档" in html and "aa001122" in html and "bb003344" in html
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────── 入口 ─────────────────────────

def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n共 {len(tests)} 个用例，通过 {len(tests) - failed}，失败 {failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
