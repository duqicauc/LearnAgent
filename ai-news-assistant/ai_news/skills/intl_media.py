"""技能：国际行业动态 —— WIRED AI 频道。"""
from .registry import Skill

intl_media_skill = Skill(
    name="intl_media",
    description="国际 AI 行业动态：WIRED 等英文科技媒体",
    keywords=["国际", "海外", "wired", "英文", "行业", "global", "venture", "startup"],
    tools=["wired"],
    tags=["国际", "媒体"],
)
