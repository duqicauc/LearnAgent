"""Stopping：循环防护策略，避免 Agent 陷入无限工具调用循环。

基于 AgentState 中的「任务内执行指标」（step_*）进行判定，
不另设游离计数变量。
"""
from typing import Optional

from agent.state import AgentState


class StoppingPolicy:
    """循环防护上限：最多轮数 / 总工具调用次数 / 单工具调用次数。"""

    def __init__(
        self,
        max_rounds: int = 6,
        max_total_tool_calls: int = 12,
        max_per_tool_calls: int = 2,
    ) -> None:
        self.max_rounds = max_rounds
        self.max_total_tool_calls = max_total_tool_calls
        self.max_per_tool_calls = max_per_tool_calls

    def check(self, state: AgentState) -> Optional[str]:
        """基于状态中的任务内指标检查是否触发任一上限。

        返回停止原因；未触发时返回 None。
        """
        if state.step_rounds >= self.max_rounds:
            return f"已达最大轮数 {self.max_rounds}"
        if state.step_total_tool_calls >= self.max_total_tool_calls:
            return (
                f"工具调用总次数 {state.step_total_tool_calls}/"
                f"{self.max_total_tool_calls} 已达上限"
            )
        for name, count in state.step_tool_call_counter.items():
            if count >= self.max_per_tool_calls:
                return (
                    f"工具 {name} 已调用 {count}/{self.max_per_tool_calls} 次，"
                    f"达到单工具上限（总 {state.step_total_tool_calls}/"
                    f"{self.max_total_tool_calls}）"
                )
        return None

    @staticmethod
    def force_answer_message(reason: str) -> str:
        """构造触发上限后，要求模型基于已有数据直接作答的提醒。"""
        return (
            f"【系统提醒】已达到防护上限：{reason}。"
            "请基于已获取的所有工具数据，直接给出最终分析结论，不要再调用任何工具。"
        )

    def describe(self) -> str:
        return (
            f"最多 {self.max_rounds} 轮、最多 {self.max_total_tool_calls} 次工具调用、"
            f"单工具最多 {self.max_per_tool_calls} 次"
        )
