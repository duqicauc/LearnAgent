"""pytest 配置：将项目根目录加入 sys.path，保证 tests/ 下用例可 import ai_news / web。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
