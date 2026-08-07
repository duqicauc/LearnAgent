"""工具注册表：注册、Schema 导出、执行、查询。

工具是 Agent 的「原子能力」——每个工具 = 一个函数 + 一份 JSON Schema。
技能（skills/）则是对多个工具的编排封装（见 M3）。
"""
import json
from typing import Any, Callable, Dict, List

ToolFunc = Callable[..., Any]


class ToolRegistry:
    """工具注册表：维护 工具名 → (函数, JSON Schema) 的映射。"""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolFunc] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register(self, func: ToolFunc, schema: Dict[str, Any]) -> None:
        """注册一个工具。schema 为 OpenAI function-calling 格式。"""
        name = schema["function"]["name"]
        if name in self._tools:
            raise ValueError(f"工具已存在: {name}")
        self._tools[name] = func
        self._schemas[name] = schema

    def unregister(self, name: str) -> None:
        """注销工具（支持技能热插拔）。"""
        self._tools.pop(name, None)
        self._schemas.pop(name, None)

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def function_schemas(self) -> List[Dict[str, Any]]:
        """导出全部工具的 JSON Schema，供 LLM function-calling 使用。"""
        return list(self._schemas.values())

    def execute(self, name: str, args: Dict[str, Any]) -> str:
        """执行工具，返回 JSON 字符串结果（保证类型一致，便于回灌给 LLM）。"""
        if name not in self._tools:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        try:
            result = self._tools[name](**args)
        except Exception as exc:  # noqa: BLE001 - 工具异常需转 JSON 回灌
            return json.dumps(
                {"error": f"工具执行失败: {type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)
