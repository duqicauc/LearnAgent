"""长期记忆测试：sqlite 存储、user_id 隔离、冲突版本化、过期、工具接入。"""
import json

from runtime.memory import MemoryManager, MemoryStatus
from tools import (
    QueryMemoryTool,
    SaveMemoryTool,
    ToolRegistry,
)


class TestMemoryManager:
    def _manager(self, tmp_path):
        return MemoryManager(tmp_path / "memory.db")

    def test_save_full_fields(self, tmp_path):
        mgr = self._manager(tmp_path)
        r = mgr.save(
            user_id="张工",
            content="生产库禁止 drop 操作",
            type="constraint",
            summary="生产环境禁删",
            scope="prod",
            confidence="high",
            valid_until="2030-12-31",
            topic="db-safety",
        )
        assert r.status == MemoryStatus.ACTIVE
        assert r.version == 1
        assert r.content == "生产库禁止 drop 操作"
        assert r.type == "constraint"
        assert r.scope == "prod"
        assert r.confidence == "high"
        assert r.valid_until == "2030-12-31"
        # 重新加载数据库可查
        mgr2 = MemoryManager(tmp_path / "memory.db")
        got = mgr2.get("张工", r.id)
        assert got is not None and got.content == r.content

    def test_user_id_isolation(self, tmp_path):
        mgr = self._manager(tmp_path)
        mgr.save(user_id="张工", content="偏好英文缩写")
        mgr.save(user_id="李工", content="偏好中文全称")
        zhang = mgr.query("张工")
        li = mgr.query("李工")
        assert len(zhang) == 1 and zhang[0].content == "偏好英文缩写"
        assert len(li) == 1 and li[0].content == "偏好中文全称"
        # 张工查不到李工的记忆
        assert mgr.query("张工", keyword="中文") == []

    def test_conflict_marks_old_superseded_and_new_version(self, tmp_path):
        mgr = self._manager(tmp_path)
        v1 = mgr.save(
            user_id="张工", content="每天 10 点发布",
            type="preference", topic="release-time",
        )
        v2 = mgr.save(
            user_id="张工", content="发布改到每天 16 点",
            type="preference", topic="release-time",
        )
        # 新版本生效
        assert v2.version == 2
        assert v2.status == MemoryStatus.ACTIVE
        # 旧版本标记过时
        old = mgr.get("张工", v1.id)
        assert old.status == MemoryStatus.SUPERSEDED
        # 查询只返回新版本
        active = mgr.query("张工")
        assert [r.content for r in active] == ["发布改到每天 16 点"]
        assert "16 点" in active[0].content

    def test_same_content_is_idempotent(self, tmp_path):
        mgr = self._manager(tmp_path)
        mgr.save(user_id="张工", content="偏好英文缩写", topic="lang")
        again = mgr.save(user_id="张工", content="偏好英文缩写", topic="lang")
        assert again.version == 1  # 不刷版本
        all_records = mgr.list_all("张工")
        assert len(all_records) == 1

    def test_different_topics_do_not_conflict(self, tmp_path):
        mgr = self._manager(tmp_path)
        mgr.save(user_id="张工", content="偏好英文缩写", topic="lang")
        mgr.save(user_id="张工", content="窗口期不允许重启", topic="restart-policy")
        active = mgr.query("张工")
        assert len(active) == 2  # 两个主题共存

    def test_expired_memory_excluded_from_query(self, tmp_path):
        from datetime import datetime, timedelta

        mgr = self._manager(tmp_path)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        mgr.save(
            user_id="张工", content="临时工单约定",
            type="fact", valid_until=yesterday, topic="tmp",
        )
        mgr.save(
            user_id="张工", content="长期偏好",
            type="preference", topic="lang",
        )
        active = mgr.query("张工")
        assert [r.content for r in active] == ["长期偏好"]
        # 过期记录状态已标记
        all_records = mgr.list_all("张工")
        assert any(
            r.status == MemoryStatus.EXPIRED for r in all_records
        )

    def test_query_filters(self, tmp_path):
        mgr = self._manager(tmp_path)
        mgr.save(user_id="张工", content="gateway 每周末发版", type="preference", scope="gateway")
        mgr.save(user_id="张工", content="order-service 是核心服务", type="fact", scope="order-service")
        assert len(mgr.query("张工", keyword="gateway")) == 1
        assert len(mgr.query("张工", type="fact")) == 1
        assert len(mgr.query("张工", scope="order-service")) == 1
        assert mgr.query("张工", keyword="不存在的关键词") == []


class TestMemoryTools:
    def _registry(self, tmp_path):
        mgr = MemoryManager(tmp_path / "memory.db")
        registry = ToolRegistry()
        registry.register(SaveMemoryTool(mgr))
        registry.register(QueryMemoryTool(mgr))
        return registry, mgr

    def test_save_memory_tool_via_registry(self, tmp_path):
        registry, mgr = self._registry(tmp_path)
        result = json.loads(
            registry.execute_tool(
                "save_memory",
                {"type": "preference", "content": "以后都用英文缩写回复",
                 "summary": "英文缩写偏好", "confidence": "high"},
                user="张工",
            )
        )
        assert result["memory_id"] is not None
        assert result["user_id"] == "张工"
        assert result["version"] == 1
        # 已写入 sqlite
        assert len(mgr.query("张工")) == 1

    def test_query_memory_tool_isolated_by_user(self, tmp_path):
        registry, _ = self._registry(tmp_path)
        registry.execute_tool(
            "save_memory", {"type": "preference", "content": "用英文缩写"},
            user="张工",
        )
        got = json.loads(
            registry.execute_tool("query_memory", {"keyword": "英文"}, user="张工")
        )
        assert got["total"] == 1
        # 其他用户检索不到
        got2 = json.loads(
            registry.execute_tool("query_memory", {"keyword": "英文"}, user="李工")
        )
        assert got2["total"] == 0

    def test_save_conflict_upgrades_version_via_tool(self, tmp_path):
        registry, _ = self._registry(tmp_path)
        r1 = json.loads(registry.execute_tool(
            "save_memory",
            {"type": "preference", "content": "每天 10 点发布", "topic": "release-time"},
            user="张工",
        ))
        r2 = json.loads(registry.execute_tool(
            "save_memory",
            {"type": "preference", "content": "每天 16 点发布", "topic": "release-time"},
            user="张工",
        ))
        assert r1["version"] == 1
        assert r2["version"] == 2
        got = json.loads(
            registry.execute_tool("query_memory", {}, user="张工")
        )
        assert got["total"] == 1
        assert got["memories"][0]["version"] == 2
