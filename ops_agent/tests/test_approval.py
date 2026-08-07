"""异步授权（审批）测试：任务创建、幂等 approve、reject、持久化与 Loop 暂停集成。"""
import json
from types import SimpleNamespace

import pytest

from agent import AgentLoop
from agent.stopping import StoppingPolicy
from config.permissions import Identity
from config.settings import Settings
from runtime.approval import (
    ApprovalError,
    ApprovalManager,
    ApprovalStatus,
)
from runtime.audit import AuditRecorder
from runtime.idempotency import IdempotencyGuard
from runtime.persistence import SessionStore
from runtime.policy import PolicyEvaluator
from tools import LogQueryTool, RestartServiceTool, ToolRegistry


def make_tool_call(name, args, call_id="call-1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name=name, arguments=json.dumps(args, ensure_ascii=False)
        ),
    )


def make_message(content, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class MockLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools=None):
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return resp


class TestApprovalManager:
    def test_create_task_saves_action(self, tmp_path):
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.create(
            "restart_service",
            {"service": "gateway", "reason": "连接异常"},
            Identity(name="张工", role="ops"),
        )
        assert task.status == ApprovalStatus.PENDING
        assert task.task_id.startswith("APP-")
        assert task.tool == "restart_service"
        assert task.arguments == {"service": "gateway", "reason": "连接异常"}
        assert task.user == "张工"

    def test_approve_executes_saved_action_once(self, tmp_path):
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.create(
            "restart_service",
            {"service": "gateway"},
            Identity(name="张工", role="ops"),
        )
        executed = []

        def executor(tool, args):
            executed.append((tool, args))
            return "restarted"

        approved = manager.approve(task.task_id, executor)
        # 只执行保存的那一个动作
        assert executed == [("restart_service", {"service": "gateway"})]
        assert approved.result == "restarted"
        assert approved.status == ApprovalStatus.APPROVED

    def test_duplicate_approve_executes_only_once(self, tmp_path):
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.create(
            "restart_service",
            {"service": "gateway"},
            Identity(name="张工", role="ops"),
        )
        executed = []

        def executor(tool, args):
            executed.append((tool, args))
            return "restarted"

        manager.approve(task.task_id, executor)
        second = manager.approve(task.task_id, executor)
        # 重复 approve：不再执行，直接返回首次结果
        assert len(executed) == 1
        assert second.replayed is True
        assert second.result == "restarted"

    def test_reject_no_execution_and_records_reason(self, tmp_path):
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.create(
            "drop_database",
            {"database": "prod"},
            Identity(name="张工", role="ops"),
        )
        executed = []

        def executor(tool, args):
            executed.append(tool)
            return "dropped"

        rejected = manager.reject(task.task_id, reason="人工确认风险过高")
        assert rejected.status == ApprovalStatus.REJECTED
        assert rejected.reason == "人工确认风险过高"
        assert executed == []  # 不执行
        # 已拒绝的任务不能 approve
        with pytest.raises(ApprovalError):
            manager.approve(task.task_id, executor)

    def test_unknown_task_raises(self, tmp_path):
        manager = ApprovalManager(tmp_path / "approvals")
        with pytest.raises(ApprovalError):
            manager.approve("APP-NOT-EXIST", lambda t, a: "x")

    def test_persistence_across_reload(self, tmp_path):
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.create(
            "restart_service",
            {"service": "gateway"},
            Identity(name="张工", role="ops"),
        )
        # 重新加载（模拟程序退出后恢复）
        manager2 = ApprovalManager(tmp_path / "approvals")
        loaded = manager2.get(task.task_id)
        assert loaded is not None
        assert loaded.status == ApprovalStatus.PENDING
        assert loaded.arguments == {"service": "gateway"}
        # approve 后再次重新加载，状态与结果仍在
        manager2.approve(task.task_id, lambda t, a: "restarted")
        manager3 = ApprovalManager(tmp_path / "approvals")
        final = manager3.get(task.task_id)
        assert final.status == ApprovalStatus.APPROVED
        assert final.result == "restarted"


class TestLoopApprovalPause:
    def _build_loop(self, tmp_path, responses, role="ops"):
        registry = ToolRegistry()
        registry.register(LogQueryTool())
        registry.register(RestartServiceTool())
        llm = MockLLM(responses)
        settings = Settings(
            audit_dir=tmp_path / "audit",
            session_dir=tmp_path / "sessions",
            approval_dir=tmp_path / "approvals",
        )
        return AgentLoop(
            llm=llm,
            registry=registry,
            policy=PolicyEvaluator(registry),
            identity=Identity(name="张工", role=role),
            settings=settings,
            stopping=StoppingPolicy(max_rounds=3, max_total_tool_calls=6, max_per_tool_calls=2),
            idempotency=IdempotencyGuard(),
            audit=AuditRecorder(settings.audit_dir),
            session_store=SessionStore(settings.session_dir, agent_id="张工"),
            approval=ApprovalManager(settings.approval_dir),
        )

    def test_review_creates_task_and_pauses(self, tmp_path):
        tc = make_tool_call(
            "restart_service", {"service": "gateway", "reason": "支付异常"}
        )
        loop = self._build_loop(
            tmp_path,
            [
                make_message("", [tc]),
                make_message("已创建审批任务，本轮暂停"),
            ],
        )
        reply = loop.step("重启 gateway")
        assert reply == "已创建审批任务，本轮暂停"
        # 审批任务已创建（工具 + 参数 + 身份）
        manager = ApprovalManager(tmp_path / "approvals")
        pending = manager.list_pending()
        assert len(pending) == 1
        assert pending[0].tool == "restart_service"
        assert pending[0].arguments["service"] == "gateway"
        # 暂停检查点：会话快照已保存
        snap = SessionStore(tmp_path / "sessions", agent_id="张工").load()
        assert snap is not None
        # 停止状态也持久化（暂停原因）
        assert "待审批任务" in snap["state"]["stop_reason"]
        # 停止原因记录了暂停
        assert "待审批任务" in loop.state.stop_reason
        # 审批任务编号已回灌给模型（tool 消息中）
        tool_msgs = [
            m for m in loop.state.messages.as_list() if m["role"] == "tool"
        ]
        assert pending[0].task_id in tool_msgs[0]["content"]

    def test_approve_after_pause_runs_saved_action(self, tmp_path):
        tc = make_tool_call(
            "restart_service", {"service": "gateway", "reason": "支付异常"}
        )
        loop = self._build_loop(
            tmp_path,
            [
                make_message("", [tc]),
                make_message("已暂停"),
            ],
        )
        loop.step("重启 gateway")
        # 模拟独立审批入口：按任务编号 approve
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.list_pending()[0]
        executed = []

        def executor(tool, args):
            executed.append((tool, args))
            return json.dumps({"status": "restarted"})

        approved = manager.approve(task.task_id, executor)
        assert executed == [
            ("restart_service", {"service": "gateway", "reason": "支付异常"})
        ]
        assert approved.result == '{"status": "restarted"}'
        # 再次 approve 不重复执行
        manager.approve(task.task_id, executor)
        assert len(executed) == 1

    def test_reject_after_pause_does_not_execute(self, tmp_path):
        tc = make_tool_call("restart_service", {"service": "gateway", "reason": "测试"})
        loop = self._build_loop(tmp_path, [make_message("", [tc]), make_message("已暂停")])
        loop.step("重启 gateway")
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.list_pending()[0]
        executed = []

        def executor(tool, args):
            executed.append(tool)
            return "restarted"

        rejected = manager.reject(task.task_id, reason="审批人不同意")
        assert executed == []
        assert rejected.status == ApprovalStatus.REJECTED
        # 拒绝结果已持久化，重新加载可见
        manager2 = ApprovalManager(tmp_path / "approvals")
        assert manager2.get(task.task_id).reason == "审批人不同意"


class TestApprovalResultInjection:
    """审批结果回灌 → 恢复会话时注入模型上下文。"""

    def _build_loop(self, tmp_path, responses, resume=False):
        registry = ToolRegistry()
        registry.register(LogQueryTool())
        registry.register(RestartServiceTool())
        llm = MockLLM(responses)
        settings = Settings(
            audit_dir=tmp_path / "audit",
            session_dir=tmp_path / "sessions",
            approval_dir=tmp_path / "approvals",
        )
        return AgentLoop(
            llm=llm,
            registry=registry,
            policy=PolicyEvaluator(registry),
            identity=Identity(name="张工", role="ops"),
            settings=settings,
            stopping=StoppingPolicy(max_rounds=3, max_total_tool_calls=6, max_per_tool_calls=2),
            idempotency=IdempotencyGuard(),
            audit=AuditRecorder(settings.audit_dir),
            session_store=SessionStore(settings.session_dir, agent_id="张工"),
            approval=ApprovalManager(settings.approval_dir),
            resume=resume,
        )

    def test_session_store_approval_result_lifecycle(self, tmp_path):
        store = SessionStore(tmp_path / "sessions", agent_id="张工")
        store.append_approval_result(
            {"task_id": "APP-1", "tool": "restart_service",
             "decision": "approve", "result": "restarted", "consumed": False}
        )
        store.append_approval_result(
            {"task_id": "APP-2", "tool": "restart_service",
             "decision": "reject", "reason": "禁止", "consumed": False}
        )
        assert len(store.unconsumed_approval_results()) == 2
        store.mark_approval_results_consumed(["APP-1"])
        assert len(store.unconsumed_approval_results()) == 1
        # 保存快照时审批结果事件被保留
        store.save([{"role": "user", "content": "hi"}], {"rounds": 0})
        assert len(store.load()["approval_results"]) == 2

    def test_resume_injects_approve_result(self, tmp_path):
        # 1. 暂停会话（创建审批任务）
        tc = make_tool_call("restart_service", {"service": "gateway", "reason": "测试"})
        loop = self._build_loop(
            tmp_path,
            [make_message("", [tc]), make_message("已暂停")],
        )
        loop.step("重启 gateway")

        # 2. 模拟审批入口：approve 并回灌结果
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.list_pending()[0]
        manager.approve(task.task_id, lambda t, a: "restarted")
        store = SessionStore(tmp_path / "sessions", agent_id="张工")
        store.append_approval_result(
            {
                "task_id": task.task_id,
                "tool": task.tool,
                "arguments": task.arguments,
                "decision": "approve",
                "result": "restarted",
                "consumed": False,
            }
        )

        # 3. 恢复会话：审批结果注入上下文
        loop2 = self._build_loop(tmp_path, [make_message("续写完成")], resume=True)
        contents = [
            m.get("content", "")
            for m in loop2.state.messages.as_list()
            if m.get("role") == "user"
        ]
        notice = [c for c in contents if "审批结果通知" in c]
        assert len(notice) == 1
        assert "已获人工批准并执行" in notice[0]
        assert "restarted" in notice[0]
        # 注入后标记已消费
        assert len(store.unconsumed_approval_results()) == 0

    def test_resume_injects_reject_result(self, tmp_path):
        tc = make_tool_call("restart_service", {"service": "gateway", "reason": "测试"})
        loop = self._build_loop(
            tmp_path,
            [make_message("", [tc]), make_message("已暂停")],
        )
        loop.step("重启 gateway")
        manager = ApprovalManager(tmp_path / "approvals")
        task = manager.list_pending()[0]
        manager.reject(task.task_id, reason="窗口期禁止")
        store = SessionStore(tmp_path / "sessions", agent_id="张工")
        store.append_approval_result(
            {
                "task_id": task.task_id,
                "tool": task.tool,
                "arguments": task.arguments,
                "decision": "reject",
                "reason": "窗口期禁止",
                "consumed": False,
            }
        )
        loop2 = self._build_loop(tmp_path, [make_message("好的")], resume=True)
        contents = [
            m.get("content", "")
            for m in loop2.state.messages.as_list()
            if m.get("role") == "user"
        ]
        notice = [c for c in contents if "审批结果通知" in c]
        assert len(notice) == 1
        assert "已被人工拒绝" in notice[0]
        assert "窗口期禁止" in notice[0]
        # 审批结果不得重复注入（再次 resume 不重复）
        loop3 = self._build_loop(tmp_path, [make_message("好的")], resume=True)
        contents3 = [
            m.get("content", "")
            for m in loop3.state.messages.as_list()
            if m.get("role") == "user"
        ]
        assert sum(1 for c in contents3 if "审批结果通知" in c) == 1
