"""报告 Agent：按 JSON Schema 产出报告大纲（结构化输出 + schema 校验 + 失败重试）。

知识点：结构化输出 —— LLM 输出经 schema 校验，非法 JSON 自动重试（≤2 次）。
"""
import json
import re
from typing import Any, Dict, List, Optional

from ..core.llm import LLM
from ..core.tool_registry import ToolRegistry
from .base_agent import BaseAgent

REPORT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["title", "summary", "sections"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["heading", "items"],
                "properties": {
                    "heading": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["title", "url", "note"],
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "note": {"type": "string"},
                                "impact": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "你是 AI 信息报告编辑。根据分析结果生成 HTML 报告的 JSON 大纲（只输出 JSON）：\n"
    "{\n"
    '  "title": "报告标题",\n'
    '  "summary": "报告摘要（100 字内）",\n'
    '  "sections": [{"heading": "章节标题", "items": '
    '[{"title": "条目标题", "url": "来源链接", "note": "一句话解读", '
    '"impact": "为什么值得关注（一句价值点评）"}]}]\n'
    "}\n"
    "要求：sections 2-4 个，每个 3-8 条；url 必须来自给出的真实链接；"
    "每条务必给出 impact（价值点评，不要复述 note）。用中文。"
)


class ReporterAgent(BaseAgent):
    """报告：LLM 生成大纲 → schema 校验 → 失败重试。"""

    MAX_ATTEMPTS = 3

    def __init__(self, llm: LLM, registry: Optional[ToolRegistry] = None) -> None:
        super().__init__(
            name="reporter", llm=llm, registry=registry or ToolRegistry(),
            system_prompt=SYSTEM_PROMPT,
        )

    def build_report(
        self,
        analysis: Dict[str, Any],
        items: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成报告大纲；校验失败自动重试，超限抛异常。"""
        self.tracer.step("reporter", "report_start", {"item_count": len(items)})
        prompt = (
            "请基于以下分析与条目生成报告大纲：\n"
            + json.dumps(
                {"analysis": analysis, "stats": stats, "items": items},
                ensure_ascii=False, default=str,
            )
        )
        self.messages.append({"role": "user", "content": prompt})

        for attempt in range(self.MAX_ATTEMPTS):
            reply = self.chat("请生成报告大纲 JSON。", use_tools=False, max_tokens=4096)
            report = self._parse_json(reply)
            if report:
                errors = self._validate(report)
                if not errors:
                    self.tracer.step("reporter", "report_done", {"sections": len(report.get("sections", []))})
                    return report
                self.messages.append(
                    {"role": "user", "content": f"JSON 校验失败：{errors}。请修正后重新输出完整 JSON。"}
                )
            else:
                self.messages.append(
                    {"role": "user", "content": "未解析到合法 JSON，请只输出 JSON 大纲。"}
                )

        raise ValueError("报告 JSON 校验连续失败（已重试多次）")

    @staticmethod
    def _parse_json(reply: str) -> Optional[Dict[str, Any]]:
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

    @staticmethod
    def _validate(report: Dict[str, Any]) -> List[str]:
        """轻量 schema 校验，返回错误列表（空=通过）。"""
        errors: List[str] = []
        if not isinstance(report.get("title"), str) or not report["title"].strip():
            errors.append("缺少 title")
        if not isinstance(report.get("summary"), str):
            errors.append("缺少 summary")
        sections = report.get("sections")
        if not isinstance(sections, list) or not sections:
            errors.append("sections 必须是非空数组")
        else:
            for sec in sections:
                if not isinstance(sec.get("heading"), str) or not isinstance(sec.get("items"), list):
                    errors.append(f"sections 元素缺 heading/items: {sec}")
        return errors
