"""评估评测：任务质量评分（完整性/覆盖面/时效性）+ 指标汇总。

知识点：评估评测 —— 每次任务产出 evaluation 记录，
量化 Agent 输出质量，为后续改进提供依据。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .tracing import DATA_DIR

EVAL_DIR = DATA_DIR / "reports"


class Evaluator:
    """任务评估器：规则指标 + 可选 LLM 质量评分。"""

    def __init__(self, llm: Optional[Any] = None) -> None:
        self.llm = llm  # 可选：LLM 质量评分

    def evaluate(self, task_output: Dict[str, Any]) -> Dict[str, float]:
        """对一次任务的产出做多维度评分（0-1 区间）。"""
        report = task_output.get("report", {})
        analysis = task_output.get("analysis", {})
        stats = task_output.get("stats", {})

        # 完整性：报告结构是否齐全
        sections = report.get("sections", [])
        completeness = 0.0
        if report.get("title"):
            completeness += 0.4
        if report.get("summary"):
            completeness += 0.3
        if sections:
            completeness += 0.3 * min(1.0, len(sections) / 3.0)

        # 覆盖面：来源站点数与条目量
        by_source = stats.get("by_source", {})
        source_score = min(1.0, len(by_source) / 5.0)
        item_score = min(1.0, (stats.get("total") or 0) / 20.0)
        coverage = source_score * 0.6 + item_score * 0.4

        # 分析深度：分析字段是否非空
        depth = 0.0
        if analysis.get("summary"):
            depth += 0.3
        if analysis.get("categories"):
            depth += 0.3
        if analysis.get("trends"):
            depth += 0.2
        if analysis.get("tldr") or analysis.get("highlights"):
            depth += 0.2  # 重点速览（tldr 已替代 highlights）
        if analysis.get("_degraded"):
            depth *= 0.5  # 降级输出减半

        overall = round(completeness * 0.4 + coverage * 0.3 + depth * 0.3, 3)
        return {
            "completeness": round(completeness, 3),
            "coverage": round(coverage, 3),
            "depth": round(depth, 3),
            "overall": overall,
        }

    def run_and_save(self, task_output: Dict[str, Any]) -> Dict[str, float]:
        """评估并落盘 data/reports/evaluation_<task_id>.json。"""
        score = self.evaluate(task_output)
        record = {
            "task_id": task_output.get("task_id"),
            "evaluated_at": datetime.now().isoformat(timespec="seconds"),
            "score": score,
        }
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        path = EVAL_DIR / f"evaluation_{task_output.get('task_id')}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        score["evaluation_file"] = str(path)
        return score
