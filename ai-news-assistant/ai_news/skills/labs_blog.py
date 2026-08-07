"""技能：官方实验室快讯 —— OpenAI / DeepMind / Meta AI / Anthropic 等官方动态。

M2 阶段官方博客站点尚未接入，该技能暂映射到已有抓取能力，
后续增量接入官方博客 Scraper 后补充 tools 即可（热插拔）。"""
from .registry import Skill

labs_blog_skill = Skill(
    name="labs_blog",
    description="官方实验室快讯：OpenAI、Google DeepMind、Meta AI、Anthropic、NVIDIA 官方发布",
    keywords=["官方", "博客", "openai", "deepmind", "anthropic", "meta ai", "nvidia", "发布", "公告"],
    tools=["arxiv"],  # 过渡映射：官方发布常伴随论文/技术报告
    tags=["官方", "动态"],
)
