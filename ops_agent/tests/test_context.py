"""Context 管理单测：构建本轮模型调用所需消息子集的各项规则。"""
import json

import pytest

from agent.context import ContextBuilder


def u(content):
    return {"role": "user", "content": content}


def a(content=None, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def tc(call_id, name, args):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def t(call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


SYSTEM = {"role": "system", "content": "你是运维智能体"}


class TestAlwaysKept:
    def test_system_and_current_user_always_kept(self):
        cb = ContextBuilder(window_size=2)
        messages = [
            SYSTEM,
            u("查网关日志"),
            a("网关日志结果", [tc("c1", "query_logs", {"service": "gateway"})]),
            t("c1", "query_logs", '{"total": 1}'),
            u("现在查订单错误"),
        ]
        built = cb.build(messages, "现在查订单错误")
        roles = [m["role"] for m in built]
        assert roles.count("system") == 1
        assert built[-1] == messages[-1]  # 当前问题在末尾
        assert built[0]["role"] == "system"


class TestWindow:
    def test_old_unrelated_rounds_removed(self):
        cb = ContextBuilder(window_size=2)
        messages = [
            SYSTEM,
            u("查发票接口超时"),
            a("旧结果"),
            u("查网关日志"),
            a("网关结果"),
            u("查订单错误"),
        ]
        built = cb.build(messages, "查订单错误")
        contents = [m["content"] for m in built]
        # 窗口=2：当前问题 + 最近 2 轮（查网关日志那轮），最早一轮被剔除
        assert "查发票接口超时" not in contents
        assert "查网关日志" in contents
        assert built[-1] == messages[-1]


class TestKeywordRelevance:
    def test_old_round_kept_when_keyword_related(self):
        cb = ContextBuilder(window_size=1)
        messages = [
            SYSTEM,
            u("昨天查过订单超时的问题"),
            a("订单相关旧结论"),
            u("查发票问题"),
            a("发票结论"),
            u("继续查订单错误"),
        ]
        built = cb.build(messages, "继续查订单错误")
        contents = [m["content"] for m in built]
        # 最早轮次含「订单」关键词，虽超出窗口仍保留
        assert "昨天查过订单超时的问题" in contents


class TestStaleRemoval:
    def _messages_with_stale(self):
        return [
            SYSTEM,
            u("查网关日志"),
            a("", [tc("c1", "query_logs", {"service": "gateway"})]),
            t("c1", "query_logs", '{"total": 1, "logs": []}'),
            u("查当前部署状态"),
            a("", [tc("c2", "query_releases", {"service": "gateway"})]),
            t(
                "c2",
                "query_releases",
                json.dumps(
                    {"releases": [], "invalidated": True, "reason": "已被新发布覆盖"}
                ),
            ),
            u("现在到底什么情况"),
        ]

    def test_stale_round_removed_with_pairing(self):
        cb = ContextBuilder(window_size=10)
        built = cb.build(self._messages_with_stale(), "现在到底什么情况")
        contents = [m["content"] for m in built]
        # 失效轮次整轮剔除：tool 消息不在，配对的 assistant tool_calls 也不在
        assert '"invalidated": true' not in "\n".join(contents)
        assert "c2" not in [str(c) for c in contents]
        # 正常轮次（c1）保留且配对完整
        assert "c1" in str(built)

    def test_valid_round_pairing_integrity(self):
        cb = ContextBuilder(window_size=10)
        messages = [
            SYSTEM,
            u("查网关日志"),
            a("", [tc("c1", "query_logs", {"service": "gateway"})]),
            t("c1", "query_logs", '{"total": 1}'),
            u("查指标"),
            a("", [tc("c2", "query_metrics", {"metric": "cpu_usage"})]),
            t("c2", "query_metrics", '{"value": 88}'),
            u("现在分析"),
        ]
        built = cb.build(messages, "现在分析")
        # 保留的每个 tool 消息，其配对 assistant（含 tool_calls id）必须同时存在
        assistant_tc_ids = {
            c["id"]
            for m in built
            if m["role"] == "assistant"
            for c in (m.get("tool_calls") or [])
        }
        tool_ids = {m["tool_call_id"] for m in built if m["role"] == "tool"}
        assert tool_ids == assistant_tc_ids


class TestDedup:
    def test_adjacent_duplicate_user_keeps_latest(self):
        cb = ContextBuilder()
        messages = [
            SYSTEM,
            u("查网关"),
            u("查网关"),  # 相邻重复
            a("网关结果"),
            u("现在分析"),
        ]
        built = cb.build(messages, "现在分析")
        user_contents = [m["content"] for m in built if m["role"] == "user"]
        # 重复的 user 只保留最新一条（content 相同，条数 1 即可）
        assert user_contents.count("查网关") == 1


class TestLoopIntegration:
    """通过 AgentLoop 验证上下文管理确实生效于模型调用。"""

    def test_mock_llm_receives_pruned_context(self, tmp_path):
        from types import SimpleNamespace

        from agent import AgentLoop
        from agent.stopping import StoppingPolicy
        from config.permissions import Identity
        from config.settings import Settings
        from runtime.audit import AuditRecorder
        from runtime.idempotency import IdempotencyGuard
        from runtime.persistence import SessionStore
        from runtime.policy import PolicyEvaluator
        from tools import LogQueryTool, MetricQueryTool, ToolRegistry

        registry = ToolRegistry()
        registry.register(LogQueryTool())
        registry.register(MetricQueryTool())

        received = []

        class CapturingLLM:
            def chat(self, messages, tools=None):
                received.append(list(messages))
                return SimpleNamespace(content="好的", tool_calls=None)

        loop = AgentLoop(
            llm=CapturingLLM(),
            registry=registry,
            policy=PolicyEvaluator(registry),
            identity=Identity(name="张工", role="ops"),
            settings=Settings(
                audit_dir=tmp_path / "audit",
                session_dir=tmp_path / "sessions",
            ),
            stopping=StoppingPolicy(max_rounds=3, max_total_tool_calls=6, max_per_tool_calls=2),
            idempotency=IdempotencyGuard(),
            audit=AuditRecorder(tmp_path / "audit"),
            session_store=SessionStore(tmp_path / "sessions", agent_id="张工"),
            context_builder=ContextBuilder(window_size=2),
        )
        # 先跑三个无关任务，再跑当前任务（窗口=2，最早的无关任务应被截断）
        loop.step("查发票接口问题")
        loop.step("查库存水位")
        loop.step("查订单状态")
        loop.step("查网关错误")
        # 最后一次模型调用收到的上下文不应包含最早无关历史轮次
        last_context = received[-1]
        contents = [m.get("content") for m in last_context]
        assert "查发票接口问题" not in contents
        assert "查网关错误" in contents
        assert any(m.get("role") == "system" for m in last_context)
