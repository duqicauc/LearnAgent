"""审计：将每次工具调用记录（时间、身份、参数、决策、结果摘要）写入审计日志。"""
import json
import time
from pathlib import Path
from typing import Any, Dict


class AuditRecorder:
    """审计记录器：追加式写入 JSONL 审计日志。"""

    def __init__(self, audit_dir: Path) -> None:
        self.path = Path(audit_dir) / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: Dict[str, Any]) -> None:
        """记录一次事件。"""
        event.setdefault("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
