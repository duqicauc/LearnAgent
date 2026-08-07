"""异步授权（审批）：创建审批任务、人工 approve/reject、幂等执行与持久化。

- create():      需要审批（review）时，保存本次执行的动作（工具 + 参数）+ 身份，分配唯一任务编号
- approve(id):   批准后只执行之前保存的那一个动作；
                  同一任务重复 approve 幂等——只执行一次，后续直接返回已有结果
- reject(id):    拒绝时不执行，并记录人工拒绝的原因
- 每次创建 / 审批 / 拒绝后立即持久化，程序退出后可恢复
"""
import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config.permissions import Identity


class ApprovalError(Exception):
    """审批任务异常（任务不存在 / 状态不允许操作等）。"""


class ApprovalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalTask:
    """一次待审批动作。approve 后只执行本任务保存的那一个动作。"""

    task_id: str
    tool: str
    arguments: Dict[str, Any]
    user: str
    role: str
    session_id: Optional[str] = None  # 关联的 Agent 会话（恢复后回灌审批结果）
    status: str = ApprovalStatus.PENDING
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S")
    )
    decided_at: Optional[str] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    result: Optional[str] = None
    replayed: bool = False  # True 表示重复提交审批，未再次执行

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalTask":
        return cls(**data)


class ApprovalManager:
    """审批管理器：任务生命周期（pending → approved/rejected）与持久化。"""

    def __init__(self, approval_dir: Path) -> None:
        self.path = Path(approval_dir) / "approvals.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, ApprovalTask] = {}
        self._load()

    # ---- 任务创建 ----

    def create(
        self,
        tool: str,
        arguments: Dict[str, Any],
        identity: Identity,
        session_id: Optional[str] = None,
    ) -> ApprovalTask:
        """为一次需要审批的动作创建任务，返回唯一任务编号。"""
        task = ApprovalTask(
            task_id=self._gen_id(),
            tool=tool,
            arguments=arguments,
            user=identity.name,
            role=identity.role,
            session_id=session_id or identity.name,
        )
        self._tasks[task.task_id] = task
        self.save()
        return task

    # ---- 查询 ----

    def get(self, task_id: str) -> Optional[ApprovalTask]:
        return self._tasks.get(task_id)

    def list_pending(self) -> List[ApprovalTask]:
        return [
            t for t in self._tasks.values()
            if t.status == ApprovalStatus.PENDING
        ]

    def list_all(self) -> List[ApprovalTask]:
        return list(self._tasks.values())

    # ---- 人工审批 ----

    def approve(
        self,
        task_id: str,
        executor: Callable[[str, Dict[str, Any]], str],
    ) -> ApprovalTask:
        """批准任务：只执行该任务保存的那一个动作。

        幂等：已 approved 的任务重复 approve 不会再次执行，
        直接返回首次执行的结果（replayed=True）。
        """
        task = self._require(task_id)
        if task.status == ApprovalStatus.APPROVED:
            # 重复提交 approve：不再执行
            task.replayed = True
            self.save()
            return task
        if task.status == ApprovalStatus.REJECTED:
            raise ApprovalError(
                f"任务 {task_id} 已被人工拒绝（reason: {task.reason}），不能批准执行"
            )

        task.status = ApprovalStatus.APPROVED
        task.decision = "approve"
        task.decided_at = time.strftime("%Y-%m-%d %H:%M:%S")
        # 只执行保存的那一个动作
        task.result = executor(task.tool, task.arguments)
        self.save()
        return task

    def reject(self, task_id: str, reason: str = "") -> ApprovalTask:
        """拒绝任务：不执行，记录人工拒绝结果。"""
        task = self._require(task_id)
        if task.status == ApprovalStatus.REJECTED:
            # 重复提交 reject：幂等
            task.replayed = True
            self.save()
            return task
        if task.status == ApprovalStatus.APPROVED:
            raise ApprovalError(f"任务 {task_id} 已批准执行，不能拒绝")

        task.status = ApprovalStatus.REJECTED
        task.decision = "reject"
        task.decided_at = time.strftime("%Y-%m-%d %H:%M:%S")
        task.reason = reason or "未提供原因"
        self.save()
        return task

    # ---- 持久化 ----

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    task_id: task.to_dict()
                    for task_id, task in self._tasks.items()
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._tasks = {
            task_id: ApprovalTask.from_dict(task)
            for task_id, task in data.items()
        }

    # ---- 内部 ----

    def _require(self, task_id: str) -> ApprovalTask:
        task = self.get(task_id)
        if task is None:
            raise ApprovalError(f"审批任务不存在: {task_id}")
        return task

    @staticmethod
    def _gen_id() -> str:
        ts = time.strftime("%Y%m%d%H%M%S")
        rand = f"{random.randint(0, 9999):04d}"
        return f"APP-{ts}-{rand}"
