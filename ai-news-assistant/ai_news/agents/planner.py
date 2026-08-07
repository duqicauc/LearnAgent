"""主编 Agent：二阶段 Agent Loop —— 阶段一强制思考规划，阶段二按计划执行工具。

知识点：二阶段循环 —— 思考与行动分离，阶段一不调用工具（节省工具配额/成本），
只有规划收敛后才在阶段二开放工具权限。
"""
import json
import re
from typing import Any, Dict, Optional

from ..core.llm import LLM
from ..core.tool_registry import ToolRegistry
from ..skills.registry import SkillRegistry
from .base_agent import BaseAgent

ALL_SITES = ["huggingface", "github_trending", "arxiv", "qbitai", "wired"]

SYSTEM_PROMPT = (
    "你是 AI 信息搜索任务的主编（Planner），负责「先规划、后执行」。\n"
    "可用站点：huggingface（热门模型）、github_trending（开源项目）、"
    "arxiv（学术论文）、qbitai（中文资讯）、wired（国际资讯）。\n"
    "第一阶段（思考）：不调用任何工具，仅根据用户指令输出行动计划 JSON：\n"
    '{"sites": ["站点1", "站点2"], "keyword": "检索关键词(可为空)", '
    '"limit": 10, "focus": "本次抓取重点方向说明"}\n'
    "第二阶段（行动）：严格按计划调用抓取工具获取真实数据。\n"
    "请始终用中文回复。"
)


class PlannerAgent(BaseAgent):
    """主编：规划 + 执行（多智能体入口）。"""

    def __init__(
        self,
        llm: LLM,
        registry: ToolRegistry,
        skill_registry: Optional[SkillRegistry] = None,
    ) -> None:
        super().__init__(name="planner", llm=llm, registry=registry, system_prompt=SYSTEM_PROMPT)
        self.skill_registry = skill_registry or SkillRegistry()

    # ── 阶段一：纯思考，产出行动计划 ──
    def plan(self, user_input: str) -> Dict[str, Any]:
        """强制思考阶段：不传 tools + 开启深度思考，收敛出行动计划。"""
        self.tracer.step(self.name, "phase1_think_start", {"phase": 1, "tools_open": False})
        reply = self.chat(user_input, use_tools=False, thinking=True)
        plan = self._parse_plan(reply)

        # 技能发现兜底：计划中未指定站点时，按技能匹配推荐
        if not plan.get("sites"):
            skills = self.skill_registry.discover(user_input)
            if skills:
                plan["sites"] = skills[0].tools
                self.tracer.step(self.name, "skill_discovered", {"skill": skills[0].name})

        plan.setdefault("keyword", "")
        plan.setdefault("limit", 10)
        plan.setdefault("focus", "")
        plan["sites"] = [s for s in plan["sites"] if s in ALL_SITES][:5]
        self.tracer.step(self.name, "plan_ready", {"plan": plan})
        return plan

    # ── 阶段二：按计划执行（开放工具） ──
    def execute(self, plan: Dict[str, Any]) -> str:
        """执行阶段：携带计划开放工具权限，循环调用直至收敛。

        LLM 在工具循环中自主调用抓取工具验证各计划站点（limit=3 小批量，
        控制上下文成本），观察结果后收敛。返回主编视角的站点验证摘要。
        """
        instruction = (
            "请按以下行动计划验证抓取可行性：逐个调用抓取工具（每次 limit=3，"
            "小批量即可），确认每个站点的数据可获取且内容方向符合本次任务，"
            "然后汇总各站点的关键信息概况。不要全量抓取。\n"
            + json.dumps(plan, ensure_ascii=False)
        )
        self.tracer.step(self.name, "phase2_exec_start", {"phase": 2, "tools_open": True})
        reply = self.chat(instruction, use_tools=True)
        self.tracer.step(self.name, "phase2_done", {"reply_len": len(reply)})
        return reply

    @staticmethod
    def _parse_plan(reply: str) -> Dict[str, Any]:
        """从思考回复中提取行动计划 JSON（容忍 markdown 代码块）。"""
        if not reply:
            return {}
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.DOTALL)
        if not m:
            m = re.search(r"(\{.*\})", reply, re.DOTALL)
        if not m:
            return {}
        try:
            plan = json.loads(m.group(1))
            return plan if isinstance(plan, dict) else {}
        except json.JSONDecodeError:
            return {}
