"""分析 Agent：对多源抓取结果做 AI 分析（摘要、分类、趋势、热词、重点）。

知识点：结构化输出 —— 要求 LLM 严格按 JSON 结构返回分析结果。
"""
import json
import re
from typing import Any, Dict, List, Optional

from ..core.llm import LLM
from ..core.tool_registry import ToolRegistry
from .base_agent import BaseAgent

SYSTEM_PROMPT = (
    "你是 AI 前沿信息分析专家。你会收到多站点抓取的 AI 信息（JSON），"
    "请综合分析并输出 JSON（不要输出 JSON 以外的内容）：\n"
    "{\n"
    '  "summary": "总体摘要（150 字内）",\n'
    '  "confidence": 0~1 的数字（对本次分析结论的置信度自评），\n'
    '  "reason": "置信度的一句话依据",\n'
    '  "tldr": [{"point": "一句话要点", "why": "为什么值得关注", "title": "对应条目标题(来自输入，用于定位)"}],\n'
    '  "categories": [{"name": "分类名", "insight": "该分类解读", "count": 数量}],\n'
    '  "trends": ["趋势 1", "趋势 2"],\n'
    '  "hot_keywords": ["热词 1", "热词 2"]\n'
    "}\n"
    "要求：tldr 5 条（每条务必给出 why 价值点评）、categories 2-4 个、trends 2-4 条、hot_keywords 3-8 个。用中文。"
)


class AnalyzerAgent(BaseAgent):
    """分析：输入 Item 列表 + 聚合统计，输出结构化分析结果。"""

    def __init__(self, llm: LLM, registry: Optional[ToolRegistry] = None) -> None:
        super().__init__(
            name="analyzer", llm=llm, registry=registry or ToolRegistry(),
            system_prompt=SYSTEM_PROMPT,
        )

    def analyze(
        self,
        items: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """运行分析，返回结构化 JSON；解析失败时降级为统计摘要。"""
        self.tracer.step("analyzer", "analyze_start", {"item_count": len(items)})
        prompt = (
            "请分析以下 AI 前沿信息（JSON 输入）：\n"
            + json.dumps({"stats": stats, "items": items}, ensure_ascii=False, default=str)
        )
        reply = self.chat(prompt, use_tools=False, max_tokens=4096)
        analysis = self._parse_json(reply)
        if not analysis:
            # 降级：无 AI 分析时用管道统计兜底
            analysis = {
                "summary": f"共收集 {len(items)} 条信息，来源分布：{stats.get('by_source', {})}",
                "confidence": 0.6,
                "reason": "AI 分析失败，降级为统计摘要",
                "tldr": [],
                "categories": [],
                "trends": [],
                "hot_keywords": stats.get("top_keywords", [])[:8],
                "_degraded": True,
            }
        self.tracer.step("analyzer", "analyze_done", {"keys": list(analysis.keys())})
        return analysis

    @staticmethod
    def _parse_json(reply: str) -> Optional[Dict[str, Any]]:
        """提取回复中的 JSON 对象。"""
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.DOTALL)
        if not m:
            m = re.search(r"(\{.*\})", reply, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
