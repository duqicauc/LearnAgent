"""LLM 封装：屏蔽底层 OpenAI 客户端细节，提供 chat + tool_calls 能力。

支持二阶段 Agent Loop 的两种思考模式：
- thinking=False：禁用深度思考，快速响应（工具调用/最终回复）
- thinking=True：开启深度思考，强制纯推理（二阶段循环的阶段一）
"""
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage


class LLM:
    """LLM 封装：从 .env 读取配置，提供带工具能力的对话接口。"""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        load_dotenv()
        self.model = model or os.getenv("LLM_MODEL", "deepseek-v4-flash")
        self.client = OpenAI(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
            base_url=base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
        max_tokens: Optional[int] = None,
    ) -> ChatCompletionMessage:
        """发送消息，返回 Assistant 消息（可能包含 tool_calls）。

        :param messages: 完整对话上下文
        :param tools: 工具 Schema 列表，None 表示不开放工具（纯思考模式）
        :param thinking: 是否开启深度思考
        :param max_tokens: 输出 Token 上限（结构化长输出场景需调大）
        """
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "extra_body": {"thinking": {"type": "enabled" if thinking else "disabled"}},
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message
