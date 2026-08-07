"""技能：论文追踪 —— arXiv cs.AI 最新论文。"""
from .registry import Skill

papers_skill = Skill(
    name="papers",
    description="学术论文追踪：arXiv cs.AI / cs.LG / cs.CL 最新论文",
    keywords=["论文", "paper", "arxiv", "学术", "研究", "科研", "文献", "benchmark"],
    tools=["arxiv"],
    tags=["论文", "学术"],
)
