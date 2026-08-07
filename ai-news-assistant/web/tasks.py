"""后台任务管理：单任务锁 + 状态机 + stdout 日志实时捕获。

产品化：Web 请求不阻塞于任务执行（单次任务 40s+），
提交后立即返回 task_id，前端轮询状态与日志。
"""
import contextlib
import io
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class _LogCapture(io.TextIOBase):
    """把 print 输出实时转发到任务日志缓冲（线程安全）。"""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def write(self, s: str) -> int:
        self._sink(s)
        return len(s)

    def flush(self) -> None:
        pass


class TaskManager:
    """单任务管理器：同时只运行一个任务（单用户产品）。"""

    def __init__(self, run_fn: Callable[[str], Dict[str, Any]]) -> None:
        self._run_fn = run_fn
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._current: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def submit(self, query: str) -> Optional[str]:
        """提交任务；已有运行中任务时返回 None。"""
        query = query.strip()
        if not query:
            return None
        with self._lock:
            if self._current is not None:
                return None
            task_id = uuid.uuid4().hex[:8]
            self._tasks[task_id] = {
                "task_id": task_id,
                "query": query,
                "status": STATUS_RUNNING,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "log": [],
                "result": None,
                "error": None,
            }
            self._current = task_id
        threading.Thread(target=self._worker, args=(task_id, query), daemon=True).start()
        return task_id

    def _worker(self, task_id: str, query: str) -> None:
        record = self._tasks[task_id]

        def _sink(line: str) -> None:
            with self._lock:
                record["log"].append(line)

        try:
            with contextlib.redirect_stdout(_LogCapture(_sink)):
                result = self._run_fn(query)
            with self._lock:
                record["status"] = STATUS_DONE
                record["result"] = result
        except Exception as exc:  # noqa: BLE001 - 任务级兜底
            with self._lock:
                record["status"] = STATUS_FAILED
                record["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self._current = None

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        """任务快照（供 API 返回；日志截断为尾部 2000 字符）。"""
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            return {
                "task_id": record["task_id"],
                "query": record["query"],
                "status": record["status"],
                "created_at": record["created_at"],
                "log_tail": "".join(record["log"])[-2000:],
                "result": record["result"],
                "error": record["error"],
            }
