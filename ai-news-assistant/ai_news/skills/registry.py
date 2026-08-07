"""技能注册表：技能的定义、注册、发现（路由）、热插拔。

知识点：技能管理——将「原子工具」编排为可管理、可检索、可复用的「技能」。
技能 = 元信息（名称/描述/关键词/标签）+ 依赖的工具集合（scraper 标识）。
"""
from typing import Any, Dict, List, Optional


class Skill:
    """一个可复用的抓取技能。"""

    def __init__(
        self,
        name: str,
        description: str,
        keywords: List[str],
        tools: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self.description = description
        self.keywords = [k.lower() for k in keywords]
        self.tools = tools or []
        self.tags = tags or []

    def matches(self, text: str) -> int:
        """按关键词对文本打分（0=不相关）。"""
        lowered = text.lower()
        return sum(1 for kw in self.keywords if kw in lowered)

    def __repr__(self) -> str:
        return f"Skill({self.name}, tools={self.tools})"


class SkillRegistry:
    """技能注册表：注册 / 注销（热插拔）/ 发现（关键词路由）/ 查询。"""

    def __init__(self) -> None:
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"技能已存在: {skill.name}")
        self._skills[skill.name] = skill

    def unregister(self, name: str) -> None:
        """注销技能（支持热插拔/升级）。"""
        self._skills.pop(name, None)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        return list(self._skills.values())

    def discover(self, text: str) -> List[Skill]:
        """按相关度（关键词命中数）返回匹配的技能列表。"""
        scored = [(s.matches(text), s) for s in self._skills.values()]
        scored = [(score, s) for score, s in scored if score > 0]
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored]
