"""工具注册表：负责工具注册、查询、schema 导出与无授权执行通道。

授权判定（Policy Layer）在 runtime.policy 中实现，本层不包含授权逻辑。
"""
import json
from typing import Any, Dict, List

from .schema import Tool


class ToolRegistry:
    """工具注册表：注册 / 查询 / 导出 function schema / 执行工具。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具 {tool.name} 已注册")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get_tool(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def function_schemas(self) -> List[Dict[str, Any]]:
        """返回所有工具的 function schema，用于透传给 LLM。"""
        return [tool.to_function_schema() for tool in self._tools.values()]

    @staticmethod
    def _normalize(parameters: Any) -> Dict[str, Any]:
        if parameters is None:
            return {}
        if isinstance(parameters, dict):
            return parameters
        return {"input": parameters}

    def execute_tool(
        self, name: str, parameters: Any, user: str = "default"
    ) -> str:
        """统一执行通道：查工具 + 注入执行上下文 + 参数归一化 + 异常兜底。"""
        try:
            tool = self.get_tool(name)
            tool.execution_user = user
            normalized = self._normalize(parameters)
            return tool.run(normalized)
        except Exception as e:
            return json.dumps(
                {"error": f"工具 {name} 执行失败: {str(e)}"},
                ensure_ascii=False,
            )
