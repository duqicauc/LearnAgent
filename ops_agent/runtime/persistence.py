"""持久化：会话快照（messages + state）落盘，支持恢复与审批结果回灌。"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionStore:
    """会话存储：将 Agent 会话快照保存为 JSON 文件，可恢复。

    快照结构：{messages, state, approval_results}。
    approval_results 为审批结果事件列表（approve/reject 后回灌），
    消费（注入模型上下文）后标记 consumed。
    """

    def __init__(self, session_dir: Path, agent_id: str = "default") -> None:
        self.path = Path(session_dir) / f"session_{agent_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        messages: List[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> None:
        """保存会话快照（覆盖写），保留已存在的审批结果事件。"""
        existing = self.load() or {}
        data = {
            "messages": messages,
            "state": state,
            "approval_results": existing.get("approval_results", []),
        }
        self._write(data)

    def load(self) -> Optional[Dict[str, Any]]:
        """加载会话快照；不存在时返回 None。"""
        if not self.path.exists():
            return None
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    # ---- 审批结果回灌 ----

    def append_approval_result(self, result: Dict[str, Any]) -> None:
        """追加一条审批结果事件（approve/reject 之后由审批入口写入）。"""
        data = self.load() or {
            "messages": [],
            "state": {},
            "approval_results": [],
        }
        data.setdefault("approval_results", []).append(result)
        self._write(data)

    def unconsumed_approval_results(self) -> List[Dict[str, Any]]:
        """返回尚未注入模型上下文的审批结果事件。"""
        data = self.load() or {}
        return [
            r
            for r in data.get("approval_results", [])
            if not r.get("consumed")
        ]

    def mark_approval_results_consumed(self, task_ids: List[str]) -> None:
        """将指定任务的审批结果标记为已消费。"""
        data = self.load()
        if not data:
            return
        for r in data.get("approval_results", []):
            if r.get("task_id") in task_ids:
                r["consumed"] = True
        self._write(data)

    # ---- 内部 ----

    def _write(self, data: Dict[str, Any]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
