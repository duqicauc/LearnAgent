import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_APP_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """模型、密钥与运行时数据目录配置。"""

    model: str = "deepseek-v4-flash"
    api_key: Optional[str] = None
    base_url: str = "https://api.deepseek.com"
    data_dir: Path = _APP_ROOT / "var"
    audit_dir: Path = _APP_ROOT / "var" / "audit"
    session_dir: Path = _APP_ROOT / "var" / "sessions"
    approval_dir: Path = _APP_ROOT / "var" / "approvals"
    memory_db: Path = _APP_ROOT / "var" / "memory" / "memories.db"

    @classmethod
    def load(cls, env_path: Optional[str] = None) -> "Settings":
        """从 .env 加载模型与密钥配置。"""
        load_dotenv(env_path)
        return cls(
            model=os.getenv("LLM_MODEL", "deepseek-v4-flash"),
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        )
