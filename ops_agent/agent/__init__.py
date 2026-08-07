"""Agent 层：消息、状态、循环防护、上下文管理与主循环。"""
from .messages import MessageStore, assistant_message, system_message, tool_message, user_message
from .state import AgentState, ToolTrace
from .stopping import StoppingPolicy
from .context import ContextBuilder
from .loop import AgentLoop, OPS_SYSTEM_PROMPT

__all__ = [
    "MessageStore",
    "assistant_message",
    "system_message",
    "tool_message",
    "user_message",
    "AgentState",
    "ToolTrace",
    "StoppingPolicy",
    "ContextBuilder",
    "AgentLoop",
    "OPS_SYSTEM_PROMPT",
]
