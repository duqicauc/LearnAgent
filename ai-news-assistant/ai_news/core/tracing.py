"""全链路 trace 日志：记录每个 Agent 的决策、工具调用、耗时、Token 消耗。

输出为结构化 JSONL 文件（data/logs/trace_<session>.jsonl），
每条记录含时间戳、步骤号、Agent 名、动作、详情、耗时。
"""
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

# 运行时数据根目录：ai-news-assistant/data
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LOG_DIR = DATA_DIR / "logs"


class Tracer:
    """全链路 trace 管理器（单例）。"""

    _instance: Optional["Tracer"] = None

    def __init__(self, log_dir: Path = LOG_DIR) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid.uuid4().hex[:8]
        self.file = self.log_dir / f"trace_{self.session_id}.jsonl"
        self.step_count = 0

    @classmethod
    def get(cls) -> "Tracer":
        """获取全局单例（每个进程一个会话）。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def step(
        self,
        agent: str,
        action: str,
        detail: Any = None,
        cost_ms: Optional[float] = None,
        **extra: Any,
    ) -> None:
        """记录一条 trace 日志。"""
        self.step_count += 1
        record: Dict[str, Any] = {
            "ts": round(time.time(), 3),
            "step": self.step_count,
            "session": self.session_id,
            "agent": agent,
            "action": action,
        }
        if detail is not None:
            record["detail"] = detail
        if cost_ms is not None:
            record["cost_ms"] = round(cost_ms, 1)
        record.update(extra)

        with open(self.file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @contextmanager
    def span(self, agent: str, action: str, **extra: Any) -> Iterator[None]:
        """记录一段代码执行的耗时（trace span）。"""
        start = time.monotonic()
        try:
            yield
        finally:
            cost_ms = (time.monotonic() - start) * 1000
            self.step(agent, action, cost_ms=cost_ms, **extra)
