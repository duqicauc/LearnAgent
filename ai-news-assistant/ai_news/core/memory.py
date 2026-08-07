"""三级记忆管理：工作记忆 / 会话记忆 / 长期记忆。

知识点：记忆管理 ——
- 工作记忆（working）：单任务内的临时状态（如当前计划），任务结束即清空
- 会话记忆（session）：进程内跨任务的关键信息（对话摘要）
- 长期记忆（long_term）：跨会话持久化（用户偏好 + 历史任务要点，JSON 落盘）

操作原语：write / retrieve / update / forget
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .tracing import DATA_DIR

MEMORY_DIR = DATA_DIR / "memory"
LONG_TERM_FILE = MEMORY_DIR / "long_term.json"


class Memory:
    """三级记忆管理器。"""

    LEVELS = ("working", "session", "long_term")

    def __init__(self, memory_dir: Path = MEMORY_DIR) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.long_term_file = self.memory_dir / "long_term.json"

        # 工作记忆：单任务临时状态
        self.working: Dict[str, Any] = {}
        # 会话记忆：进程内跨任务要点
        self.session: List[Dict[str, Any]] = []
        # 长期记忆：跨会话持久化
        self.long_term: Dict[str, Any] = {"preferences": {}, "history": []}
        self._load()

    # ── 持久化 ──
    def _load(self) -> None:
        if self.long_term_file.exists():
            try:
                with open(self.long_term_file, "r", encoding="utf-8") as f:
                    self.long_term = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.long_term = {"preferences": {}, "history": []}

    def _save(self) -> None:
        with open(self.long_term_file, "w", encoding="utf-8") as f:
            json.dump(self.long_term, f, ensure_ascii=False, indent=2)

    # ── 操作原语 ──
    def write(self, level: str, key: str, value: Any) -> None:
        """写入一条记忆。working/session 按 key 覆盖，long_term 按 key 存储。"""
        if level == "working":
            self.working[key] = value
        elif level == "session":
            for item in self.session:
                if item.get("key") == key:
                    item["value"] = value
                    return
            self.session.append({"key": key, "value": value, "ts": time.time()})
        elif level == "long_term":
            self.long_term[key] = value
            self._save()

    def retrieve(self, level: str, key: Optional[str] = None) -> Any:
        """读取记忆；key 为空返回该层全部内容。"""
        if level == "working":
            return self.working.get(key) if key else self.working
        if level == "session":
            if key is None:
                return self.session
            for item in self.session:
                if item.get("key") == key:
                    return item["value"]
            return None
        if level == "long_term":
            return self.long_term.get(key) if key else self.long_term
        return None

    def update(self, level: str, key: str, value: Any) -> None:
        """更新记忆（与 write 等价，语义区分：强调增量修改）。"""
        self.write(level, key, value)

    def forget(self, level: str, key: Optional[str] = None) -> None:
        """遗忘：清空指定 key 或整个层级。"""
        if level == "working":
            self.working = {} if key is None else {k: v for k, v in self.working.items() if k != key}
        elif level == "session":
            self.session = (
                [] if key is None
                else [i for i in self.session if i.get("key") != key]
            )
        elif level == "long_term":
            if key is None:
                self.long_term = {"preferences": {}, "history": []}
            else:
                self.long_term.pop(key, None)
            self._save()

    # ── 高层封装 ──
    def remember_task(self, record: Dict[str, Any]) -> None:
        """任务完成后把要点写入长期记忆（历史 + 最近一次）。"""
        self.long_term.setdefault("history", []).append(
            {
                "task_id": record.get("task_id"),
                "ts": record.get("created_at"),
                "user_input": record.get("user_input"),
                "title": record.get("report", {}).get("title"),
                "summary": record.get("analysis", {}).get("summary"),
                "topics": record.get("stats", {}).get("top_keywords", [])[:8],
            }
        )
        # 只保留最近 50 条历史
        self.long_term["history"] = self.long_term["history"][-50:]
        self.long_term["latest"] = record
        self._save()

    def history_documents(self) -> List[Dict[str, str]]:
        """导出历史要点为 RAG 索引文档。"""
        docs = []
        for item in self.long_term.get("history", []):
            text = " ".join(
                filter(None, [item.get("title"), item.get("summary"), " ".join(item.get("topics") or [])])
            )
            if text:
                docs.append({"id": item.get("task_id", ""), "text": text, "meta": item})
        return docs
