"""模型客户端：屏蔽底层 OpenAI SDK 细节，仅负责模型调用。

本层不包含权限判定、工具执行与 Agent Loop 逻辑。
"""
from typing import Any, Dict, List, Optional

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

from config.settings import Settings


class LLMClient:
    """LLM 客户端：提供 chat + tool_calls 能力。"""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.model
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatCompletionMessage:
        """发送消息，返回 Assistant 消息（可能包含 tool_calls）。"""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message
