import json
from typing import Any, Dict

from .schema import Tool


class DropDatabaseTool(Tool):
    """删除数据库工具：危险操作，禁止 Agent 执行。"""

    forbidden = True

    access_level = "delete"
    state_change = True
    reversible = False
    recovery_cost = "high"
    impact_scope = "global"
    sensitive = True  # 数据库可能包含隐私数据

    @property
    def name(self) -> str:
        return "drop_database"

    @property
    def description(self) -> str:
        return (
            "【做什么】删除指定数据库（危险操作）。"
            "【什么时候用】任何情况下都不应使用，仅用于演示授权拒绝。"
            "【不能做什么】该工具已被标记为禁止执行（forbidden=true），"
            "调用会直接返回 forbidden 拒绝，不会真实执行删除。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "要删除的数据库名称。",
                },
                "confirm": {
                    "type": "string",
                    "description": "确认词，必须输入 YES 表示确认删除。",
                    "enum": ["YES"],
                },
            },
            "required": ["database", "confirm"],
            "additionalProperties": False,
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        # 正常情况下不会被执行（forbidden 会在授权阶段拦截），此实现仅作兜底。
        return json.dumps({"status": "dropped"}, ensure_ascii=False)
