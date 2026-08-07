"""技能：中文产业资讯 —— 量子位（国内 AI 媒体）。"""
from .registry import Skill

cn_media_skill = Skill(
    name="cn_media",
    description="中文 AI 产业资讯：量子位等国内媒体动态",
    keywords=["中文", "国内", "资讯", "量子位", "产业", "融资", "发布", "新闻"],
    tools=["qbitai"],
    tags=["中文", "产业"],
)
