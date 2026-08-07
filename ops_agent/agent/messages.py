"""Messages：会话消息的构建与存储。"""
from typing import Any, Dict, List, Optional


def system_message(content: str) -> Dict[str, Any]:
    return {"role": "system", "content": content}


def user_message(content: str) -> Dict[str, Any]:
    return {"role": "user", "content": content}


def assistant_message(
    content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def tool_message(
    tool_call_id: str,
    name: str,
    content: str,
) -> Dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content,
    }


class MessageStore:
    """消息存储：维护会话上下文消息列表，提供追加与只读访问。"""

    def __init__(self, initial: Optional[List[Dict[str, Any]]] = None) -> None:
        self._messages: List[Dict[str, Any]] = list(initial or [])

    def append(self, message: Dict[str, Any]) -> None:
        self._messages.append(message)

    def extend(self, messages: List[Dict[str, Any]]) -> None:
        self._messages.extend(messages)

    def as_list(self) -> List[Dict[str, Any]]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def reset(self, initial: Optional[List[Dict[str, Any]]] = None) -> None:
        self._messages = list(initial or [])
