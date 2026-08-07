"""技能：开源模型动态 —— HuggingFace 热门模型 + GitHub Trending 开源项目。"""
from .registry import Skill

open_source_skill = Skill(
    name="open_source",
    description="开源模型与项目动态：HuggingFace 热门模型、GitHub Trending 开源项目",
    keywords=["huggingface", "hf", "模型", "开源", "github", "trending", "权重", "gguf", "权重文件"],
    tools=["huggingface", "github_trending"],
    tags=["开源", "模型"],
)
