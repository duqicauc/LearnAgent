"""Context：根据当前任务构建本轮模型调用所需的上下文子集。

规则：
1. 始终保留：系统提示词、当前用户问题（锚点及其所在任务内的全部消息）
2. 历史消息按「轮次」筛选：最近 window_size 轮默认保留；
   窗口外仅在与当前问题关键词相关时保留，避免将全部 state 塞入本轮调用
3. 明确标记失效的工具结果（invalidated/stale/obsolete）→ 整轮剔除；
   无明确标记时不做主观失效判断
4. 配对完整性：以「assistant + 其后 tool 结果」为整轮粒度操作，
   保留工具结果必保留对应 assistant tool_calls，不破坏配对关系
5. 重复信息：相邻重复的用户输入只保留最近一次
"""
import json
import re
from typing import Any, Dict, List, Optional, Set


# 工具结果中明确标记失效的字段名（值需为 true/1）
STALE_MARKERS = ("invalidated", "stale", "obsolete")


class ContextBuilder:
    """上下文构建器：从完整消息历史中筛选本轮模型调用所需的消息子集。"""

    def __init__(
        self,
        window_size: int = 6,
        enable_dedup: bool = True,
    ) -> None:
        self.window_size = window_size
        self.enable_dedup = enable_dedup

    def build(
        self,
        messages: List[Dict[str, Any]],
        current_user_input: str,
    ) -> List[Dict[str, Any]]:
        """构建本轮模型调用消息子集。

        current_user_input 为当前用户问题，用于定位锚点与提取相关关键词。
        """
        if not messages:
            return list(messages)

        groups = self._group_rounds(messages)
        anchor = self._anchor_index(groups, current_user_input)
        keywords = self._keywords(current_user_input)

        kept: List[Dict[str, Any]] = []
        for i, group in enumerate(groups):
            keep = self._decide(group, i, anchor, keywords)
            if keep:
                kept.extend(group["messages"])

        return self._dedup(kept)

    # ---- 决策 ----

    def _decide(
        self,
        group: Dict[str, Any],
        index: int,
        anchor: int,
        keywords: Set[str],
    ) -> bool:
        """判断某轮次是否进入本轮上下文。"""
        if group["kind"] == "system":
            return True  # 系统提示词始终保留
        if index >= anchor:
            return True  # 当前用户问题及其所在任务内全部保留
        if self._is_stale(group):
            return False  # 明确标记失效：整轮剔除
        if index >= max(0, anchor - self.window_size):
            return True  # 窗口内历史轮次默认保留
        return self._related(group, keywords)  # 窗口外仅关键词相关时保留

    # ---- 失效检测（仅接受明确标记，不做主观判断） ----

    def _is_stale(self, group: Dict[str, Any]) -> bool:
        return any(
            self._tool_result_stale(msg.get("content", ""))
            for msg in group["messages"]
            if msg.get("role") == "tool"
        )

    @staticmethod
    def _tool_result_stale(content: str) -> bool:
        """检测工具结果是否被明确标记为失效。"""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(data, dict):
            return False
        for key, value in data.items():
            if key.lower() in STALE_MARKERS and value in (True, "true", 1, "1"):
                return True
            if key.lower() == "status" and str(value).lower() in STALE_MARKERS:
                return True
        return False

    # ---- 相关性 ----

    @staticmethod
    def _keywords(text: str) -> Set[str]:
        """从当前问题提取关键词：英文单词 + 中文 2-gram 子串。"""
        words: Set[str] = set()
        for m in re.finditer(r"[A-Za-z_]{2,}", text):
            words.add(m.group(0).lower())
        for m in re.finditer(r"[\u4e00-\u9fa5]{2,}", text):
            seg = m.group(0)
            for i in range(len(seg) - 1):
                words.add(seg[i : i + 2])
        return words

    @staticmethod
    def _related(
        group: Dict[str, Any], keywords: Set[str]
    ) -> bool:
        """轮次文本与当前问题是否有共享关键词。"""
        if not keywords:
            return False
        text = " ".join(
            str(m.get("content") or "") for m in group["messages"]
        ).lower()
        return any(kw in text for kw in keywords)

    # ---- 轮次分组与锚点 ----

    @staticmethod
    def _group_rounds(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """按轮次分组：system/user 各成一组；assistant + 其后 tool 消息为一组。

        整轮粒度保证工具调用与工具结果的配对关系不被破坏。
        """
        groups: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role in ("system", "user"):
                groups.append({"kind": role, "messages": [msg]})
            elif role == "assistant":
                groups.append({"kind": "assistant_turn", "messages": [msg]})
            elif role == "tool":
                if groups and groups[-1]["kind"] == "assistant_turn":
                    groups[-1]["messages"].append(msg)
                else:
                    # 无配对 assistant 的 tool 消息：视为独立轮次一并保留
                    groups.append({"kind": "assistant_turn", "messages": [msg]})
        return groups

    @staticmethod
    def _anchor_index(
        groups: List[Dict[str, Any]], current_user_input: str
    ) -> int:
        """定位当前用户问题锚点：内容匹配的最后一条 user 消息所在组。"""
        target: Optional[int] = None
        for i, group in enumerate(groups):
            if group["kind"] == "user" and group["messages"][0].get(
                "content"
            ) == current_user_input:
                target = i
        if target is None:
            for i, group in enumerate(groups):
                if group["kind"] == "user":
                    target = i
        return target if target is not None else len(groups) - 1

    # ---- 去重 ----

    def _dedup(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """相邻重复的用户输入保留最近一次。"""
        if not self.enable_dedup:
            return messages
        result: List[Dict[str, Any]] = []
        for msg in messages:
            if (
                msg.get("role") == "user"
                and result
                and result[-1].get("role") == "user"
                and result[-1].get("content") == msg.get("content")
            ):
                result[-1] = msg
            else:
                result.append(msg)
        return result
