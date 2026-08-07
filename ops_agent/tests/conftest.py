"""pytest 配置：将 ops_agent 根目录加入 sys.path，便于导入各层模块。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
