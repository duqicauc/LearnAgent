"""工具层单测：各工具的 run 行为、过滤逻辑、风险等级与 Schema 完整性。"""
import json

import pytest

from tools import (
    DropDatabaseTool,
    LogQueryTool,
    MetricQueryTool,
    ReleaseQueryTool,
    RestartServiceTool,
    RiskLevel,
    TicketQueryTool,
    ToolRegistry,
)


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    for tool in [
        LogQueryTool(),
        MetricQueryTool(),
        ReleaseQueryTool(),
        TicketQueryTool(),
        RestartServiceTool(),
        DropDatabaseTool(),
    ]:
        r.register(tool)
    return r


class TestQueryTools:
    def test_log_keyword_filter(self, registry):
        result = json.loads(
            registry.execute_tool("query_logs", {"keyword": "连接超时"})
        )
        assert result["total"] >= 2
        assert all("超时" in log["message"] for log in result["logs"])

    def test_log_service_and_level(self, registry):
        result = json.loads(
            registry.execute_tool(
                "query_logs", {"service": "order-service", "level": "ERROR"}
            )
        )
        assert result["total"] == 3
        assert all(
            log["service"] == "order-service" and log["level"] == "ERROR"
            for log in result["logs"]
        )

    def test_metrics_threshold(self, registry):
        result = json.loads(
            registry.execute_tool(
                "query_metrics", {"metric": "cpu_usage", "threshold": 80}
            )
        )
        assert result["total"] == 1
        assert result["metrics"][0]["service"] == "gateway"

    def test_releases_status(self, registry):
        result = json.loads(
            registry.execute_tool("query_releases", {"status": "failed"})
        )
        assert result["total"] == 1
        assert result["releases"][0]["version"] == "gateway v4.0.0"

    def test_tickets_severity(self, registry):
        result = json.loads(
            registry.execute_tool("query_tickets", {"severity": "P1"})
        )
        assert result["total"] >= 2
        assert all(t["severity"] == "P1" for t in result["tickets"])


class TestRiskLevel:
    @pytest.mark.parametrize(
        "tool,expected",
        [
            (LogQueryTool(), RiskLevel.MEDIUM),       # 只读但含敏感数据
            (MetricQueryTool(), RiskLevel.LOW),
            (ReleaseQueryTool(), RiskLevel.LOW),
            (TicketQueryTool(), RiskLevel.MEDIUM),    # 只读但含敏感数据
            (RestartServiceTool(), RiskLevel.HIGH),   # write 权限
            (DropDatabaseTool(), RiskLevel.CRITICAL),  # delete + 不可逆 + 全局
        ],
    )
    def test_risk_level(self, tool, expected):
        assert tool.risk_level() == expected


class TestSchemaContract:
    """Schema 是接口契约：description / properties / required / enum 四类信息。"""

    def test_schema_has_contract_fields(self, registry):
        for tool in registry.list_tools():
            schema = tool.to_function_schema()
            func = schema["function"]
            params = func["parameters"]

            # 1. description：含风险信息
            assert "【风险信息】" in func["description"], tool.name
            # 2. properties：参数名称与类型
            assert isinstance(params["properties"], dict), tool.name
            assert all(
                "type" in p for p in params["properties"].values()
            ), tool.name
            # 3. required：缺失哪些参数就不能用
            assert "required" in params, tool.name
            assert all(
                r in params["properties"] for r in params["required"]
            ), tool.name
            # 4. additionalProperties：收紧到合法取值
            assert params.get("additionalProperties") is False, tool.name

    def test_enum_constrained_params(self, registry):
        """所有枚举参数都应带 enum 约束。"""
        enum_expected = {
            "query_logs": {"service", "level"},
            "query_metrics": {"service", "metric"},
            "query_releases": {"service", "status", "env"},
            "query_tickets": {"severity", "status", "tag"},
            "restart_service": {"service"},
            "drop_database": {"confirm"},
        }
        for tool in registry.list_tools():
            props = tool.to_function_schema()["function"]["parameters"]["properties"]
            for param in enum_expected.get(tool.name, set()):
                assert "enum" in props[param], f"{tool.name}.{param}"
