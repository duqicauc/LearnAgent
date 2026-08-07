import json
from pathlib import Path
from typing import Any, Dict, List

from .schema import Tool

_LOGS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "logs" / "app_logs.json"

_VALID_SERVICES = [
    "order-service",
    "payment-service",
    "user-service",
    "gateway",
    "inventory-service",
]
_VALID_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]


def _load_logs() -> List[Dict[str, Any]]:
    with open(_LOGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class LogQueryTool(Tool):
    """日志查询工具。"""

    permission = "log:read"
    access_level = "read"
    state_change = False
    reversible = True
    recovery_cost = "low"
    impact_scope = "service"
    sensitive = True  # 日志含手机号、uid 等敏感字段

    @property
    def name(self) -> str:
        return "query_logs"

    @property
    def description(self) -> str:
        return (
            "【做什么】查询线上应用日志，返回匹配的日志条目列表。"
            "【什么时候用】当用户需要排查错误原因、查看服务运行状态、追踪某个请求的完整链路时使用。"
            "【不能做什么】不能修改或删除日志；不能查询历史日志（仅支持当前时段）；"
            "当用户需要查询指标、发布记录或工单时，不应使用此工具。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "按服务名精确过滤。必填场景：排查特定服务的问题时必须指定。",
                    "enum": _VALID_SERVICES,
                },
                "level": {
                    "type": "string",
                    "description": "按日志级别过滤。必填场景：用户明确要求查看 ERROR/WARN 等特定级别时。",
                    "enum": _VALID_LEVELS,
                },
                "keyword": {
                    "type": "string",
                    "description": "在日志 message 字段中进行大小写不敏感的模糊匹配。"
                    "适用场景：用户知道错误关键词（如「超时」「连接池」「502」）但不确定具体服务或级别时。"
                    "不能做什么：不支持正则表达式，只能做简单的子串匹配。",
                    "minLength": 1,
                },
                "trace_id": {
                    "type": "string",
                    "description": "按 trace_id 精确过滤，用于追踪单个请求的完整调用链路。"
                    "格式示例：t-001、t-016。必填场景：已知 trace_id 时必须使用此参数而非 keyword。",
                    "pattern": "^t-\\d+$",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回的日志条数。默认 20，最大 50。避免返回过多条目导致上下文溢出。",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        service = parameters.get("service")
        level = parameters.get("level")
        keyword = parameters.get("keyword")
        trace_id = parameters.get("trace_id")
        limit = min(parameters.get("limit", 20), 50)

        logs = _load_logs()
        results: List[Dict[str, Any]] = []
        for log in logs:
            if service and log["service"] != service:
                continue
            if level and log["level"].upper() != level.upper():
                continue
            if keyword and keyword.lower() not in log["message"].lower():
                continue
            if trace_id and log["trace_id"] != trace_id:
                continue
            results.append(log)
            if len(results) >= limit:
                break

        return json.dumps(
            {"total": len(results), "logs": results},
            ensure_ascii=False,
            indent=2,
        )
