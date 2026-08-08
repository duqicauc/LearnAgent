"""Scraper 纯函数离线单测（不依赖网络，用固定样例验证解析逻辑）。

运行方式：
    python tests/test_scraper_parsers.py   # 直接运行全部用例
    pytest tests/                          # 或从项目根跑 pytest
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根入 path

from ai_news.scrapers.github_trending_scraper import _title_tags as gh_tags
from ai_news.scrapers.qbitai_scraper import _title_tags as qbitai_tags
from ai_news.scrapers.qbitai_scraper import _url_date
from ai_news.scrapers.wired_scraper import _title_tags as wired_tags


def test_wired_title_tags():
    """命中：从英文标题提取关键词标签，最多 3 个。"""
    tags = wired_tags("Anthropic's Claude 3.5 makes big leap in coding")
    assert "Anthropic" in tags
    assert "Claude" in tags
    assert len(tags) <= 3


def test_qbitai_title_tags():
    """命中：中文标题中的英文实体被提取为标签，最多 4 个。"""
    tags = qbitai_tags("GPT-5 发布，OpenAI 新模型登场，行业震动")
    assert "GPT-5" in tags
    assert len(tags) <= 4


def test_qbitai_url_date_current_month():
    """命中：本月 URL 近似为今天（首页均为近期发布）。"""
    now = datetime.now()
    out = _url_date(f"https://www.qbitai.com/{now.year}/{now.month:02d}/463297.html")
    assert out.startswith(f"{now.year}-{now.month:02d}")


def test_qbitai_url_date_past_month():
    """命中：历史月份取该月 1 日（保守口径）。"""
    assert _url_date("https://www.qbitai.com/2025/11/100.html") == "2025-11-01T00:00:00"


def test_qbitai_url_date_invalid():
    """越界：无年月结构 / 非法月份 返回空串。"""
    assert _url_date("https://www.qbitai.com/abc.html") == ""
    assert _url_date("https://www.qbitai.com/2026/13/1.html") == ""
    assert _url_date("") == ""


def test_github_title_tags():
    """命中：仓库名 owner/name → 提取前 2 段，不产生 github/trending 死标签。"""
    tags = gh_tags("openai/gpt-oss")
    assert "openai" in tags and "gpt-oss" in tags
    assert "github" not in tags and "trending" not in tags
    assert len(tags) <= 2


# ── 入口 ──

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
