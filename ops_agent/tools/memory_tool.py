"""长期记忆工具：save_memory（保存）/ query_memory（检索）。

记忆按 user_id 隔离（由 ToolRegistry 注入 execution_user）。
只保存用户明确表达、以后还可能使用的信息；冲突由 MemoryManager 自动版本化。
"""
from typing import Any, Dict

from runtime.memory import MemoryManager

from .schema import AccessLevel, ImpactScope, RiskLevel, RecoveryCost, Tool


class SaveMemoryTool(Tool):
    """保存一条长期记忆。

    只保存用户明确表达、以后还可能使用的信息（偏好、约束、事实、决策背景）。
    同一主题内容变化时自动把旧版本标为过时并写入新版本。
    """

    name = "save_memory"
    permission = "memory:write"
    approval = False

    access_level = AccessLevel.WRITE
    state_change = True
    reversible = True
    recovery_cost = RecoveryCost.LOW
    impact_scope = ImpactScope.RECORD
    sensitive = True

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    def risk_level(self) -> str:
        # 覆盖：写入内部记忆库，可逆、低恢复成本，无需人工审批
        return RiskLevel.LOW

    @property
    def description(self) -> str:
        return (
            "【做什么】将一条长期记忆保存到该用户的记忆库，返回记忆编号与版本。"
            "【什么时候用】仅当用户明确表达了以后还会用到的信息时使用，例如："
            "固定偏好（“以后都用中文缩写回复”）、长期约束（“生产库禁止 drop”）、"
            "稳定的环境事实（“线上域名是 xxx”）、决策背景。"
            "【不能做什么】不得保存临时性、一次性对话内容；不得保存已执行完毕"
            "无需回顾的操作细节；不得自行推断或猜测用户偏好（没有明确表达不保存）；"
            "查询既有记忆请用 query_memory。同一主题内容变化时，系统会自动将旧版本"
            "标记为过时并写入新版本，无需重复保存。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["preference", "constraint", "fact", "decision", "other"],
                    "description": "记忆类型：偏好 / 约束 / 稳定事实 / 决策背景 / 其他",
                },
                "content": {
                    "type": "string",
                    "minLength": 2,
                    "description": "记忆内容，需完整准确表达用户明确给出的信息",
                },
                "summary": {
                    "type": "string",
                    "description": "一句话总结（如“用户偏好英文缩写回复”），便于快速检索",
                },
                "scope": {
                    "type": "string",
                    "description": "适用范围，如 global / 某服务 / 某类任务；留空表示全局",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "可信度：用户明确且坚定=high，提及一次=medium，推断=low",
                },
                "valid_until": {
                    "type": "string",
                    "description": "有效截止时间（YYYY-MM-DD），留空表示长期有效",
                },
                "topic": {
                    "type": "string",
                    "description": "主题键（如 deploy-window），同一主题内容更新时旧版本自动过时",
                },
            },
            "required": ["content"],
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        import json

        try:
            record = self._memory.save(
                user_id=self.execution_user,
                content=parameters.get("content"),
                type=parameters.get("type", "fact"),
                summary=parameters.get("summary", ""),
                scope=parameters.get("scope", ""),
                confidence=parameters.get("confidence", "medium"),
                valid_until=parameters.get("valid_until"),
                topic=parameters.get("topic", "general"),
            )
            return json.dumps(
                {
                    "memory_id": record.id,
                    "user_id": record.user_id,
                    "type": record.type,
                    "topic": record.topic,
                    "content": record.content,
                    "summary": record.summary,
                    "version": record.version,
                    "status": record.status,
                    "note": (
                        "记忆已保存。若本主题此前已有内容不同且生效的记忆，"
                        "旧版本已自动标记为过时（superseded）。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        except ValueError as e:
            return json.dumps(
                {"error": str(e)}, ensure_ascii=False, indent=2
            )


class QueryMemoryTool(Tool):
    """检索某用户当前生效的长期记忆。"""

    name = "query_memory"
    permission = "memory:read"
    approval = False

    access_level = AccessLevel.READ
    state_change = False
    reversible = True
    recovery_cost = RecoveryCost.LOW
    impact_scope = ImpactScope.RECORD
    sensitive = True  # 记忆可能包含隐私信息，回复需脱敏

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    @property
    def description(self) -> str:
        return (
            "【做什么】按关键词 / 类型 / 适用范围检索该用户的长期记忆，"
            "返回当前仍生效的记忆列表。"
            "【什么时候用】当用户提到自己的偏好、历史约定、历史决策时，"
            "或不确定某事项是否已被用户约定过时，先查询记忆再行动。"
            "【不能做什么】不能修改或删除记忆；只返回生效中的记忆"
            "（过时/过期版本不会出现）；没有匹配时如实返回空结果。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "minLength": 1,
                    "description": "检索关键词，匹配记忆内容 / 总结 / 主题",
                },
                "type": {
                    "type": "string",
                    "enum": ["preference", "constraint", "fact", "decision", "other"],
                    "description": "按记忆类型过滤",
                },
                "scope": {
                    "type": "string",
                    "description": "按适用范围过滤",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                    "description": "最多返回条数",
                },
            },
            "required": [],
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        import json

        records = self._memory.query(
            user_id=self.execution_user,
            keyword=parameters.get("keyword"),
            type=parameters.get("type"),
            scope=parameters.get("scope"),
            limit=parameters.get("limit", 20),
        )
        return json.dumps(
            {
                "total": len(records),
                "memories": [r.to_dict() for r in records],
            },
            ensure_ascii=False,
            indent=2,
        )
