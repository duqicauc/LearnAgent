import json
from typing import Any, Dict, List

from .schema import Tool


_MOCK_METRICS: List[Dict[str, Any]] = [
    {"metric": "cpu_usage", "service": "order-service", "value": 72.5, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "memory_usage", "service": "order-service", "value": 68.1, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "request_rate", "service": "order-service", "value": 1523.4, "unit": "req/s", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "p99_latency", "service": "order-service", "value": 186.0, "unit": "ms", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "error_rate", "service": "order-service", "value": 4.8, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "cpu_usage", "service": "payment-service", "value": 45.2, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "error_rate", "service": "payment-service", "value": 2.1, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "p99_latency", "service": "payment-service", "value": 312.0, "unit": "ms", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "cpu_usage", "service": "gateway", "value": 88.7, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "request_rate", "service": "gateway", "value": 5421.0, "unit": "req/s", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "memory_usage", "service": "inventory-service", "value": 33.4, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
    {"metric": "error_rate", "service": "inventory-service", "value": 0.3, "unit": "%", "timestamp": "2026-07-31 10:20:00"},
]

_VALID_SERVICES = [
    "order-service",
    "payment-service",
    "gateway",
    "inventory-service",
]
_VALID_METRICS = [
    "cpu_usage",
    "memory_usage",
    "request_rate",
    "p99_latency",
    "error_rate",
]

# 指标的合理范围，用于提示模型不要设置无意义的阈值
_METRIC_RANGES = {
    "cpu_usage": (0, 100),
    "memory_usage": (0, 100),
    "request_rate": (0, 100000),
    "p99_latency": (0, 60000),
    "error_rate": (0, 100),
}


class MetricQueryTool(Tool):
    """指标查询工具。"""

    permission = "metric:read"
    access_level = "read"
    state_change = False
    reversible = True
    recovery_cost = "low"
    impact_scope = "service"
    sensitive = False

    @property
    def name(self) -> str:
        return "query_metrics"

    @property
    def description(self) -> str:
        return (
            "【做什么】查询系统实时指标（CPU/内存/请求率/延迟/错误率），返回当前采样值。"
            "【什么时候用】当用户需要评估服务健康状况、排查性能瓶颈、确认资源水位时使用。"
            "【不能做什么】不能查询历史指标趋势（仅返回最近一次采样快照）；"
            "不能设置告警阈值或触发自动扩容；当用户需要查看日志详情时，不应使用此工具。"
        )

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "按服务名精确过滤。必填场景：用户明确询问某个服务的指标时必须指定。",
                    "enum": _VALID_SERVICES,
                },
                "metric": {
                    "type": "string",
                    "description": "指标名称。各指标含义："
                    "cpu_usage=CPU使用率(%)；memory_usage=内存使用率(%)；"
                    "request_rate=每秒请求数(req/s)；p99_latency=99分位延迟(ms)；"
                    "error_rate=错误率(%)。"
                    "必填场景：用户明确询问某项指标时必须指定。",
                    "enum": _VALID_METRICS,
                },
                "threshold": {
                    "type": "number",
                    "description": "只返回 value >= threshold 的指标项，用于快速筛选异常。"
                    "使用场景：用户问「哪些服务 CPU 超过 80%」时传 80。"
                    "合理范围：cpu_usage/memory_usage/error_rate 为 0-100；"
                    "p99_latency 为 0-60000(ms)；request_rate 为 0-100000(req/s)。"
                    "不能做什么：不要设置负数或超出指标合理范围的值。",
                    "minimum": 0,
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def run(self, parameters: Dict[str, Any]) -> str:
        service = parameters.get("service")
        metric = parameters.get("metric")
        threshold = parameters.get("threshold")

        results: List[Dict[str, Any]] = []
        for item in _MOCK_METRICS:
            if service and item["service"] != service:
                continue
            if metric and item["metric"] != metric:
                continue
            if threshold is not None and item["value"] < threshold:
                continue
            results.append(item)

        return json.dumps(
            {"total": len(results), "metrics": results},
            ensure_ascii=False,
            indent=2,
        )
