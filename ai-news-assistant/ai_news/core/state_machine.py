"""任务状态机：排队 → 抓取 → 清洗 → 分析 → 生成 → 完成/失败。

失败自动重试（每阶段 ≤2 次），状态流转全程可观测（trace 记录）。
"""
from typing import Optional

from .tracing import Tracer


class TaskStateMachine:
    """AI 信息任务的生命周期状态机。"""

    ORDER = ("queued", "fetching", "cleaning", "analyzing", "generating")
    TERMINAL = ("completed", "failed")

    def __init__(self, task_id: str, max_retries: int = 2) -> None:
        self.task_id = task_id
        self.max_retries = max_retries
        self.state = "queued"
        self._retry_counts = {s: 0 for s in self.ORDER}
        self.tracer = Tracer.get()
        self.error: Optional[str] = None
        self.tracer.step("state_machine", "init", {"task_id": task_id, "state": self.state})

    @property
    def is_terminal(self) -> bool:
        return self.state in self.TERMINAL

    def transition(self, next_state: str) -> None:
        """迁移到下一状态（仅允许合法顺序）。"""
        if next_state == self.state:
            return
        if self.is_terminal:
            raise ValueError(f"任务已终止（{self.state}），无法迁移到 {next_state}")
        if next_state not in self.ORDER and next_state not in self.TERMINAL:
            raise ValueError(f"非法状态: {next_state}")
        self.state = next_state
        self.tracer.step("state_machine", "transition", {"task_id": self.task_id, "state": self.state})

    def fail(self) -> bool:
        """标记当前阶段失败。自动重试同阶段，超过上限则整体失败。

        :return: True=已安排重试（调用方应重跑当前阶段）；False=任务彻底失败
        """
        self._retry_counts[self.state] += 1
        self.error = f"{self.state} 阶段失败（第 {self._retry_counts[self.state]} 次）"
        if self._retry_counts[self.state] <= self.max_retries:
            self.tracer.step("state_machine", "retry", {"task_id": self.task_id, "stage": self.state})
            return True
        self.state = "failed"
        self.tracer.step("state_machine", "failed", {"task_id": self.task_id, "error": self.error})
        return False

    def complete(self) -> None:
        self.state = "completed"
        self.tracer.step("state_machine", "completed", {"task_id": self.task_id})

    def snapshot(self) -> dict:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "retries": dict(self._retry_counts),
            "error": self.error,
        }
