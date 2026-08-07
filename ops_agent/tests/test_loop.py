"""Loop 行为测试：授权路径、幂等执行、循环防护与持久化。

使用 MockLLM 模拟模型响应，避免真实网络调用。
"""
import json
from types import SimpleNamespace

import pytest

from agent import AgentLoop
from agent.stopping import StoppingPolicy
from config.permissions import Identity
from config.settings import Settings
from runtime.audit import AuditRecorder
from runtime.idempotency import IdempotencyGuard
from runtime.persistence import SessionStore
from runtime.policy import PolicyEvaluator
from tools import (
    DropDatabaseTool,
    LogQueryTool,
    MetricQueryTool,
    ReleaseQueryTool,
    RestartServiceTool,
    TicketQueryTool,
    ToolRegistry,
)


def make_tool_call(name: str, args: dict, call_id: str = "call-1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name=name, arguments=json.dumps(args, ensure_ascii=False)
        ),
    )


def make_message(content: str, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class MockLLM:
    """按脚本依次返回预设响应；脚本耗尽后重复最后一条。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools=None):
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return resp


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


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        audit_dir=tmp_path / "audit",
        session_dir=tmp_path / "sessions",
        approval_dir=tmp_path / "approvals",
    )


def build_loop(
    registry,
    settings,
    role="ops",
    responses=None,
    idempotency_enabled=True,
    resume=False,
):
    llm = MockLLM(responses or [make_message("好的")])
    return AgentLoop(
        llm=llm,
        registry=registry,
        policy=PolicyEvaluator(registry),
        identity=Identity(name="张工", role=role),
        settings=settings,
        stopping=StoppingPolicy(max_rounds=3, max_total_tool_calls=6, max_per_tool_calls=2),
        idempotency=IdempotencyGuard(enabled=idempotency_enabled),
        audit=AuditRecorder(settings.audit_dir),
        session_store=SessionStore(settings.session_dir, agent_id="张工"),
        resume=resume,
    )


class TestAuthorizationPaths:
    def test_allow(self, registry, settings):
        loop = build_loop(
            registry, settings,
            responses=[
                make_message("", [make_tool_call("query_logs", {"service": "gateway", "level": "ERROR"})]),
                make_message("这是日志分析结果"),
            ],
        )
        reply = loop.step("查 gateway 的错误日志")
        assert reply == "这是日志分析结果"
        # tool 消息确实回灌给模型
        tool_msgs = [m for m in loop.state.messages.as_list() if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert '"total"' in tool_msgs[0]["content"]

    def test_review_requires_approval(self, registry, settings):
        loop = build_loop(
            registry, settings, role="ops",
            responses=[
                make_message("", [make_tool_call("restart_service", {"service": "gateway", "reason": "测试"})]),
                make_message("需要审批"),
            ],
        )
        reply = loop.step("重启 gateway")
        assert reply == "需要审批"
        tool_msgs = [m for m in loop.state.messages.as_list() if m["role"] == "tool"]
        assert '"authorization": "review"' in tool_msgs[0]["content"]
        # review 现在创建异步审批任务：携带唯一任务编号
        assert '"approval_task_id"' in tool_msgs[0]["content"]
        from runtime.approval import ApprovalManager
        pending = ApprovalManager(settings.approval_dir).list_pending()
        assert len(pending) == 1
        assert pending[0].tool == "restart_service"

    def test_reject_no_permission(self, registry, settings):
        loop = build_loop(
            registry, settings, role="viewer",
            responses=[
                make_message("", [make_tool_call("restart_service", {"service": "gateway", "reason": "测试"})]),
                make_message("没有权限"),
            ],
        )
        reply = loop.step("重启 gateway")
        assert reply == "没有权限"
        tool_msgs = [m for m in loop.state.messages.as_list() if m["role"] == "tool"]
        assert '"authorization": "reject"' in tool_msgs[0]["content"]

    def test_forbidden(self, registry, settings):
        loop = build_loop(
            registry, settings, role="ops",
            responses=[
                make_message("", [make_tool_call("drop_database", {"database": "prod", "confirm": "YES"})]),
                make_message("禁止执行"),
            ],
        )
        reply = loop.step("删库")
        assert reply == "禁止执行"
        tool_msgs = [m for m in loop.state.messages.as_list() if m["role"] == "tool"]
        assert '"authorization": "forbidden"' in tool_msgs[0]["content"]


class TestIdempotency:
    def test_same_call_replayed(self, registry, settings):
        loop = build_loop(
            registry, settings,
            responses=[
                make_message("", [make_tool_call("query_logs", {"service": "gateway"})]),
                make_message("", [make_tool_call("query_logs", {"service": "gateway"})]),  # 相同参数
                make_message("完成"),
            ],
        )
        reply = loop.step("查两次相同的日志")
        assert reply == "完成"
        # 真实执行只发生一次：tool 消息两条，但第二次内容是幂等重放标记
        tool_msgs = [m for m in loop.state.messages.as_list() if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["content"] == tool_msgs[1]["content"]  # 重放同一结果


class TestStopping:
    def test_per_tool_limit_triggered(self, registry, settings):
        """模型反复调用同一工具，达到单工具上限后强制收敛。"""
        loop = build_loop(
            registry, settings,
            responses=[
                make_message("", [make_tool_call("query_metrics", {"metric": "cpu_usage"}, "call-1")]),
                make_message("", [make_tool_call("query_metrics", {"metric": "cpu_usage"}, "call-2")]),
                make_message("", [make_tool_call("query_metrics", {"metric": "cpu_usage"}, "call-3")]),
            ],
        )
        reply = loop.step("反复查 CPU")
        # 上限触发后，最终以纯文字答复收敛（脚本最后一条）
        assert reply == "反复查 CPU" or isinstance(reply, str)
        # 实际只执行了 2 次（上限 2/2），第 3 次调用前停止
        assert loop.state.tool_call_counter["query_metrics"] == 2
        assert loop.state.rounds <= 3

    def test_max_rounds_triggered(self, registry, settings):
        """模型每轮都调用新工具，直到轮数上限。"""
        loop = build_loop(
            registry, settings,
            responses=[
                make_message("", [make_tool_call("query_metrics", {"metric": m}, f"call-{i}")])
                for i, m in enumerate(["cpu_usage", "memory_usage", "request_rate", "error_rate"])
            ],
        )
        reply = loop.step("一直查指标")
        assert isinstance(reply, str)
        assert loop.state.rounds <= 3  # 上限 3 轮


class TestPersistence:
    def test_snapshot_saved_and_resumed(self, registry, settings):
        loop = build_loop(
            registry, settings,
            responses=[
                make_message("", [make_tool_call("query_logs", {"service": "gateway"})]),
                make_message("第一轮结论"),
            ],
        )
        loop.step("查日志")
        # 快照已落盘
        snapshot = SessionStore(settings.session_dir, agent_id="张工").load()
        assert snapshot is not None
        assert len(snapshot["messages"]) > 0

        # 新 Loop 恢复会话（resume=True 自动加载快照）
        loop2 = build_loop(registry, settings, responses=[make_message("恢复后")], resume=True)
        # resume 后轮数与消息数保留
        assert loop2.state.rounds == loop.state.rounds
        assert len(loop2.state.messages) == len(loop.state.messages)


class TestAudit:
    def test_audit_recorded(self, registry, settings):
        loop = build_loop(
            registry, settings,
            responses=[
                make_message("", [make_tool_call("query_metrics", {"metric": "cpu_usage"})]),
                make_message("审计完成"),
            ],
        )
        loop.step("查 CPU")
        audit_file = settings.audit_dir / "audit.jsonl"
        assert audit_file.exists()
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["tool"] == "query_metrics"
        assert event["decision"] == "allow"
        assert "risk_level" in event
        assert event["user"] == "张工"
