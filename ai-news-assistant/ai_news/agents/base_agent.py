"""Agent 基类：LLM + 工具注册表 + 消息管理 + 循环防护 + trace。

设计要点（知识点：工具调用、ReAct 循环、二阶段 Agent Loop）：
- chat(use_tools=True)   → 工具调用循环：推理 → 行动 → 观察 → 再推理，直到收敛或触发防护
- chat(use_tools=False)  → 纯思考模式（二阶段循环的阶段一）：不开放工具，强制先想清楚
"""
import json
from collections import Counter
from typing import Any, Dict, List, Optional

from ..core.llm import LLM
from ..core.tool_registry import ToolRegistry
from ..core.tracing import Tracer

# 循环防护上限
MAX_ROUNDS = 6              # 最大推理轮数
MAX_TOTAL_TOOL_CALLS = 12   # 工具调用总次数上限
MAX_PER_TOOL_CALLS = 3      # 单工具调用次数上限


class BaseAgent:
    """通用 Agent 基类：持有 LLM + 工具注册表，驱动多轮 tool-calling 对话。"""

    def __init__(
        self,
        name: str,
        llm: LLM,
        registry: Optional[ToolRegistry] = None,
        system_prompt: str = "",
    ) -> None:
        self.name = name
        self.llm = llm
        self.registry = registry or ToolRegistry()
        self.system_prompt = system_prompt
        self.tracer = Tracer.get()
        self.messages: List[Dict[str, Any]] = []
        self.reset()  # 初始化 system prompt 进上下文

    def reset(self) -> None:
        """重置会话上下文（短期记忆清空）。"""
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def chat(
        self,
        user_input: str,
        use_tools: bool = True,
        thinking: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        """处理一轮用户输入，驱动 tool-calling 循环直到收敛或触发防护上限。

        :param use_tools: False 时为纯思考模式（二阶段阶段一，不开放工具）
        :param thinking: 是否开启深度思考
        :param max_tokens: 输出 Token 上限，透传给 LLM
        """
        self.tracer.step(
            self.name, "chat_start",
            {"use_tools": use_tools, "thinking": thinking, "input_len": len(user_input)},
        )
        self.messages.append({"role": "user", "content": user_input})

        tool_schemas = self.registry.function_schemas() if use_tools else None
        tool_call_counter: Counter = Counter()
        total_tool_calls = 0
        rounds = 0

        while rounds < MAX_ROUNDS:
            rounds += 1

            # 触发防护上限：注入提醒并强制模型给出纯文字答复
            stop_reason = self._check_limits(rounds, total_tool_calls, tool_call_counter)
            if stop_reason:
                print(f"\n  [防护] {stop_reason}")
                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"【系统提醒】已达到防护上限：{stop_reason}。"
                            "请基于已获取的所有信息，直接给出最终结论，不要再调用任何工具。"
                        ),
                    }
                )
                final_msg = self.llm.chat(
                    self.messages, thinking=thinking, max_tokens=max_tokens
                )
                reply = final_msg.content or ""
                self.messages.append({"role": "assistant", "content": reply})
                return reply

            # 调用 LLM（首轮之后仍携带 tools，让模型有机会继续调用）
            message = self.llm.chat(
                self.messages, tools=tool_schemas, thinking=thinking, max_tokens=max_tokens
            )

            # 模型直接给出纯文字答复 → 收敛
            if not message.tool_calls:
                reply = message.content or ""
                self.messages.append({"role": "assistant", "content": reply})
                self.tracer.step(self.name, "chat_done", {"rounds": rounds, "tool_calls": total_tool_calls})
                return reply

            # 记录 assistant 的 tool_calls 消息进上下文
            self.messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            # 逐个执行工具调用（单个请求内可并行多个 tool_calls）
            for tc in message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = (
                        json.loads(tc.function.arguments)
                        if tc.function.arguments
                        else {}
                    )
                except json.JSONDecodeError:
                    func_args = {}

                tool_call_counter[func_name] += 1
                total_tool_calls += 1

                print(
                    f"\n  [{self.name} | Round {rounds} | 工具调用 #{total_tool_calls}] "
                    f"{func_name}({func_args})"
                )
                with self.tracer.span(
                    self.name, "tool_call", tool=func_name, args=func_args
                ):
                    tool_result = self.registry.execute(func_name, func_args)
                preview = tool_result[:200] + ("..." if len(tool_result) > 200 else "")
                print(f"  [结果] {preview}")

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": tool_result,
                    }
                )

        # 保底收敛（正常应在 while 内 return）
        print(f"\n  [防护] 已达最大轮数 {MAX_ROUNDS}，强制收敛。")
        self.messages.append(
            {
                "role": "user",
                "content": f"【系统提醒】已达到最大轮数 {MAX_ROUNDS}。请直接给出最终结论。",
            }
        )
        final_msg = self.llm.chat(self.messages, thinking=thinking, max_tokens=max_tokens)
        reply = final_msg.content or ""
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    @staticmethod
    def _check_limits(
        rounds: int,
        total_tool_calls: int,
        tool_call_counter: Counter,
    ) -> Optional[str]:
        """检查是否触发任一上限，返回停止原因；否则返回 None。"""
        if rounds > MAX_ROUNDS:
            return f"已达最大轮数 {MAX_ROUNDS}"
        if total_tool_calls >= MAX_TOTAL_TOOL_CALLS:
            return f"工具调用总次数 {total_tool_calls}/{MAX_TOTAL_TOOL_CALLS} 已达上限"
        for name, count in tool_call_counter.items():
            if count >= MAX_PER_TOOL_CALLS:
                return (
                    f"工具 {name} 已调用 {count}/{MAX_PER_TOOL_CALLS} 次，"
                    f"达到单工具上限（总 {total_tool_calls}/{MAX_TOTAL_TOOL_CALLS}）"
                )
        return None
