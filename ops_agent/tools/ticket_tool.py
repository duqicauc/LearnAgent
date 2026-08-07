import json
from pathlib import Path
from typing import Any, Dict, List

from .schema import Tool

_TICKETS_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "tickets"
    / "tickets.json"
)

_VALID_SEVERITIES = ["P0", "P1", "P2", "P3"]
_VALID_STATUSES = ["open", "in_progress", "closed"]
_VALID_TAGS = [
    "数据库",
    "支付",
    "回滚",
    "库存",
    "发布失败",
    "退款",
    "短信",
    "状态机",
    "连接池",
    "第三方依赖",
]


def _load_tickets() -> List[Dict[str, Any]]:
    with open(_TICKETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TicketQueryTool(Tool):
    """工单查询工具。"""

    permission = "ticket:read"
    access_level = "read"
    state_change = False
    reversible = True
    recovery_cost = "low"
    impact_scope = "service"
    sensitive = True  # 工单描述含手机号、订单号等敏感字段

    @property
    def name(self) -> str:
        return "query_tickets"

    @property
    def description(self) -> str:
        return (
            "【做什么】查询运维工单，返回标题、严重级别、状态、负责人、描述、评论等信息。"
            "【什么时候用】当用户需要了解某个故障是否已有人处理、查看工单处理进展、"
            "或统计某个负责人名下的工单时使用。"
            "【不能做什么】不能创建或更新工单；不能添加评论或指派负责人；"
            "当用户需要查看技术细节（如日志、指标）时，不应使用此工具。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "description": "按严重级别过滤。各级别含义："
                    "P0=紧急（可能影响大面积用户，需立即处理）；"
                    "P1=高（核心功能受损）；"
                    "P2=中（非核心功能异常）；"
                    "P3=低（轻微问题或建议）。"
                    "必填场景：用户明确要查看某个级别的工单时必须指定。",
                    "enum": _VALID_SEVERITIES,
                },
                "status": {
                    "type": "string",
                    "description": "按工单状态过滤。各状态含义："
                    "open=待处理；in_progress=处理中；closed=已关闭。"
                    "必填场景：用户只关心未关闭的工单时必须指定为 open 或 in_progress。",
                    "enum": _VALID_STATUSES,
                },
                "assignee": {
                    "type": "string",
                    "description": "按负责人姓名进行子串匹配（支持模糊查询）。"
                    "必填场景：用户要查看某个人名下的工单时必须指定。",
                    "minLength": 1,
                },
                "keyword": {
                    "type": "string",
                    "description": "在工单标题和描述中进行大小写不敏感的模糊匹配。"
                    "适用场景：用户知道问题关键词但不确定工单编号或负责人时。"
                    "不能做什么：不支持正则表达式，只能做简单的子串匹配。",
                    "minLength": 1,
                },
                "tag": {
                    "type": "string",
                    "description": "按标签精确过滤。标签是工单的主题分类，一个工单可能有多个标签。"
                    "适用场景：用户想按主题（如「数据库」「支付」「回滚」）批量查看工单时。",
                    "enum": _VALID_TAGS,
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回的条数。默认 20，最大 50。",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        severity = parameters.get("severity")
        status = parameters.get("status")
        assignee = parameters.get("assignee")
        keyword = parameters.get("keyword")
        tag = parameters.get("tag")
        limit = min(parameters.get("limit", 20), 50)

        tickets = _load_tickets()
        results: List[Dict[str, Any]] = []
        for t in tickets:
            if severity and t["severity"] != severity:
                continue
            if status and t["status"].lower() != status.lower():
                continue
            if assignee and assignee not in t["assignee"]:
                continue
            if keyword:
                haystack = (t["title"] + " " + t.get("description", "")).lower()
                if keyword.lower() not in haystack:
                    continue
            if tag and tag not in t.get("tags", []):
                continue
            results.append(t)
            if len(results) >= limit:
                break

        return json.dumps(
            {"total": len(results), "tickets": results},
            ensure_ascii=False,
            indent=2,
        )
