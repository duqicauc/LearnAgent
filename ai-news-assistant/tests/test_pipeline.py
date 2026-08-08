"""管道单测：标签/热词过滤（停用词）、clean 兜底、去重多源统计。

运行方式：
    python tests/test_pipeline.py   # 直接运行全部用例
    pytest tests/                   # 或从项目根跑 pytest
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根入 path

from ai_news.pipeline import (
    STOP_WORDS,
    _extract_keywords,
    _keep_tag,
    clean,
    dedup,
    run_pipeline,
)


class TestKeepTag:
    def test_keeps_meaningful_tags(self):
        assert _keep_tag("transformers") is True
        assert _keep_tag("GPT-5.6") is True
        assert _keep_tag("大模型") is True

    def test_drops_stopwords(self):
        assert _keep_tag("ai") is False
        assert _keep_tag("AI") is False
        assert _keep_tag("cn") is False
        assert _keep_tag("the") is False

    def test_drops_too_short_or_numeric(self):
        assert _keep_tag("a") is False
        assert _keep_tag("12") is False
        assert _keep_tag("2026") is False


class TestExtractKeywords:
    def test_title_english_words_and_tags(self):
        kw = _extract_keywords("GPT-5.6今起大降价", ["GPT-5.6"])
        assert "GPT-5.6" in kw  # 标题英文词
        assert "今起大降价" not in kw  # 中文整句不纳入

    def test_stopword_and_long_repo_filtered(self):
        kw = _extract_keywords("DavidAU/Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF", [])
        assert all(len(w) <= 24 for w in kw)
        assert "The" not in kw and "the" not in kw
        assert all(w.lower() not in STOP_WORDS for w in kw)


class TestCleanAndPipeline:
    def _raw(self):
        return [
            {"title": "文章一", "url": "https://a.com/1", "tags": ["ai", "cn", "GPT"]},
            {"title": "文章二", "url": "https://a.com/2", "tags": ["transformers"]},
            {"title": "", "url": "https://a.com/3", "tags": []},  # 缺标题被剔除
        ]

    def test_clean_filters_stopword_tags(self):
        items = clean(self._raw())
        assert len(items) == 2
        tags = [t for it in items for t in it["tags"]]
        assert "ai" not in tags and "cn" not in tags
        assert "GPT" in tags and "transformers" in tags

    def test_aggregate_no_stopwords(self):
        raw = {"源A": self._raw()[:2], "源B": self._raw()[:2]}
        stats = run_pipeline(raw)["stats"]
        assert "ai" not in stats["by_tag"]
        assert "cn" not in stats["by_tag"]
        assert "transformers" in stats["by_tag"]
        assert not any(w.lower() in STOP_WORDS for w in stats["top_keywords"])

    def test_dedup_mentions(self):
        items = [
            {"title": "同一事件", "url": "https://x.com/1", "source": "A"},
            {"title": "同一事件", "url": "https://x.com/1", "source": "B"},
        ]
        result = dedup(items)
        assert len(result) == 1
        assert result[0]["mentions"] == 2
        assert result[0]["sources"] == ["A", "B"]


def main() -> None:
    tests = []
    for k, v in sorted(globals().items()):
        if isinstance(v, type) and k.startswith("Test"):
            for name in sorted(dir(v)):
                if name.startswith("test_"):
                    tests.append((f"{k}.{name}", getattr(v(), name)))
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  [PASS] {label}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {label}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {label}: {type(exc).__name__}: {exc}")
    print(f"\n共 {len(tests)} 个用例，通过 {len(tests) - failed}，失败 {failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
