import json
from typing import Any, Dict

from .schema import Tool

_VALID_SERVICES = [
    "order-service",
    "payment-service",
    "user-service",
    "gateway",
    "inventory-service",
]


class RestartServiceTool(Tool):
    """重启服务工具：高风险写操作，需要 service:write 权限，且必须审批。"""

    permission = "service:write"
    approval = True

    access_level = "write"
    state_change = True
    reversible = True
    recovery_cost = "medium"
    impact_scope = "service"
    sensitive = False

    @property
    def name(self) -> str:
        return "restart_service"

    @property
    def description(self) -> str:
        return (
            "【做什么】重启指定线上服务，使其重新加载配置并恢复健康状态。"
            "【什么时候用】当服务无响应、资源泄漏或需要使新配置生效时使用。"
            "【不能做什么】不能批量重启多个服务；不能重启非生产环境服务；"
            "该操作需要审批（approval=true），未获得审批不会真实执行。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "要重启的服务名，必须指定且只能是受支持的服务。",
                    "enum": _VALID_SERVICES,
                },
                "reason": {
                    "type": "string",
                    "description": "重启原因。必填场景：申请审批时必须说明原因。",
                    "minLength": 1,
                },
            },
            "required": ["service", "reason"],
            "additionalProperties": False,
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        service = parameters.get("service")
        reason = parameters.get("reason", "")
        return json.dumps(
            {
                "status": "restarted",
                "service": service,
                "reason": reason,
                "timestamp": "2026-07-31 10:30:00",
            },
            ensure_ascii=False,
            indent=2,
        )
