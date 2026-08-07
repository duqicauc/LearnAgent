import json
from pathlib import Path
from typing import Any, Dict, List

from .schema import Tool

_RELEASES_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "releases"
    / "releases.json"
)

_VALID_SERVICES = [
    "order-service",
    "payment-service",
    "user-service",
    "gateway",
    "inventory-service",
    "data-sync-service",
    "promotion-service",
]
_VALID_STATUSES = ["success", "failed", "deploying", "rollback"]
_VALID_ENVS = ["prod", "staging"]


def _load_releases() -> List[Dict[str, Any]]:
    with open(_RELEASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class ReleaseQueryTool(Tool):
    """发布记录查询工具。"""

    permission = "release:read"
    access_level = "read"
    state_change = False
    reversible = True
    recovery_cost = "low"
    impact_scope = "service"
    sensitive = False

    @property
    def name(self) -> str:
        return "query_releases"

    @property
    def description(self) -> str:
        return (
            "【做什么】查询服务发布记录，返回版本号、状态、变更说明、负责人等信息。"
            "【什么时候用】当用户需要了解某次故障是否与最近发布有关、确认某个版本的变更内容、"
            "或检查发布进度时使用。"
            "【不能做什么】不能创建新的发布、不能触发回滚或部署操作；"
            "不能查询发布详情以外的信息（如代码 diff、发布审批流程）。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "按受影响的服务名过滤。必填场景：用户询问某个服务的发布历史时必须指定。",
                    "enum": _VALID_SERVICES,
                },
                "status": {
                    "type": "string",
                    "description": "按发布状态过滤。各状态含义："
                    "success=发布成功；failed=发布失败已终止；"
                    "deploying=正在发布中；rollback=已回滚。"
                    "必填场景：用户明确要查看失败/进行中的发布时必须指定。",
                    "enum": _VALID_STATUSES,
                },
                "env": {
                    "type": "string",
                    "description": "按环境过滤。prod=生产环境；staging=预发环境。"
                    "必填场景：用户明确区分环境时必须指定。默认返回所有环境。",
                    "enum": _VALID_ENVS,
                },
                "author": {
                    "type": "string",
                    "description": "按负责人姓名进行子串匹配（支持模糊查询，如输入「张」可匹配「张工」）。"
                    "不能做什么：不支持拼音或英文模糊搜索，必须输入中文姓名的一部分。",
                    "minLength": 1,
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
        service = parameters.get("service")
        status = parameters.get("status")
        env = parameters.get("env")
        author = parameters.get("author")
        limit = min(parameters.get("limit", 20), 50)

        releases = _load_releases()
        results: List[Dict[str, Any]] = []
        for rel in releases:
            if service and service not in rel.get("affected_services", []):
                continue
            if status and rel["status"].lower() != status.lower():
                continue
            if env and rel["env"] != env:
                continue
            if author and author not in rel["author"]:
                continue
            results.append(rel)
            if len(results) >= limit:
                break

        return json.dumps(
            {"total": len(results), "releases": results},
            ensure_ascii=False,
            indent=2,
        )
