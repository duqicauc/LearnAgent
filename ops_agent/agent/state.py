"""State：Agent 任务运行状态的统一模型。

一次 Agent 任务（用户输入 → 最终答复）运行中需要持续维护的信息：

1. 消息历史 messages          —— 模型上下文的唯一事实来源，跨任务持续
2. 任务内执行指标 step_*      —— 循环防护判定依据，每次任务重置
3. 会话累计指标 *（跨任务）    —— 持久化、统计与展示
4. 工具执行轨迹 tool_traces   —— 每次调用的完整记录，审计数据源
5. 停止状态 stop_reason       —— 最近一次循环防护停止原因，每次任务重置

AgentLoop 应统一通过本类读取/更新运行状态，不另设游离变量。
"""
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Counter as CounterType, Dict, List, Optional

from agent.messages import MessageStore


@dataclass
class ToolTrace:
    """一次工具调用的完整执行轨迹。"""

    round: int
    tool: str
    arguments: Dict[str, Any]
    decision: str
    risk_level: str
    replayed: bool
    result: str
    result_preview: str
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S")
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_audit_event(self, user: str, role: str) -> Dict[str, Any]:
        """转换为审计事件，供 AuditRecorder 记录。"""
        return {
            "user": user,
            "role": role,
            "tool": self.tool,
            "arguments": self.arguments,
            "decision": self.decision,
            "risk_level": self.risk_level,
            "replayed": self.replayed,
            "result_preview": self.result_preview,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolTrace":
        return cls(**data)


@dataclass
class AgentState:
    """Agent 运行状态：消息历史 + 执行指标 + 工具轨迹 + 停止状态。"""

    # ① 消息历史（跨任务持续）
    messages: MessageStore = field(default_factory=MessageStore)

    # ② 任务内执行指标（每次任务重置，供循环防护判定）
    step_rounds: int = 0
    step_total_tool_calls: int = 0
    step_tool_call_counter: CounterType[str] = field(default_factory=Counter)

    # ③ 会话累计执行指标（跨任务持续）
    rounds: int = 0
    total_tool_calls: int = 0
    tool_call_counter: CounterType[str] = field(default_factory=Counter)

    # ⑤ 停止状态（每次任务重置）
    stop_reason: Optional[str] = None

    # ④ 工具执行轨迹（跨任务持续）
    tool_traces: List[ToolTrace] = field(default_factory=list)

    # ---- 状态更新方法：AgentLoop 统一经由 state 读写 ----

    def begin_task(self) -> None:
        """开始一次任务（step）：重置任务内计数与停止状态。"""
        self.step_rounds = 0
        self.step_total_tool_calls = 0
        self.step_tool_call_counter.clear()
        self.stop_reason = None

    def record_round(self) -> None:
        """记录一轮 LLM 循环（任务内 + 会话累计）。"""
        self.step_rounds += 1
        self.rounds += 1

    def record_tool_call(self, name: str, trace: ToolTrace) -> None:
        """记录一次工具调用（任务内 + 会话累计），并追加执行轨迹。"""
        self.step_total_tool_calls += 1
        self.step_tool_call_counter[name] += 1
        self.total_tool_calls += 1
        self.tool_call_counter[name] += 1
        self.tool_traces.append(trace)

    def stop(self, reason: str) -> None:
        """标记本次任务因循环防护而停止。"""
        self.stop_reason = reason

    def latest_trace(self) -> Optional[ToolTrace]:
        """最近一次工具调用轨迹；无调用时返回 None。"""
        return self.tool_traces[-1] if self.tool_traces else None

    # ---- 持久化 ----

    def snapshot(self) -> Dict[str, Any]:
        """序列化为可持久化的字典（messages + 会话累计指标 + 轨迹 + 停止状态）。"""
        return {
            "messages": self.messages.as_list(),
            "rounds": self.rounds,
            "total_tool_calls": self.total_tool_calls,
            "tool_call_counter": dict(self.tool_call_counter),
            "tool_traces": [t.to_dict() for t in self.tool_traces],
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_snapshot(cls, data: Dict[str, Any]) -> "AgentState":
        state = cls(
            rounds=data.get("rounds", 0),
            total_tool_calls=data.get("total_tool_calls", 0),
            tool_call_counter=Counter(data.get("tool_call_counter", {})),
            tool_traces=[
                ToolTrace.from_dict(t) for t in data.get("tool_traces", [])
            ],
            stop_reason=data.get("stop_reason"),
        )
        state.messages.reset(data.get("messages", []))
        return state

    def reset(self) -> None:
        """清空全部运行状态。"""
        self.messages.reset()
        self.begin_task()
        self.rounds = 0
        self.total_tool_calls = 0
        self.tool_call_counter.clear()
        self.tool_traces.clear()
