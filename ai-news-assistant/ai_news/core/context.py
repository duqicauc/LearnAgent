"""上下文压缩：Token 估算 + 分级压缩策略。

知识点：上下文压缩 —— 长对话 Token 超预算时自动压缩历史消息，
策略分级：滚动窗口 → 摘要截断 → 冗余丢弃；压缩过程可观测（统计返回）。
"""
import json
from typing import Any, Dict, List, Optional, Tuple

# 简易 Token 估算：中文约 1.5 字符/token，英文约 4 字符/token
CN_RATE = 1.5
EN_RATE = 4.0


def estimate_tokens(text: str) -> int:
    """估算文本 Token 数（不引入 tiktoken，用于压缩决策）。"""
    if not text:
        return 0
    cn = sum(1 for ch in text if ord(ch) > 127)
    en = len(text) - cn
    return int(cn / CN_RATE + en / EN_RATE)


def _message_tokens(msg: Dict[str, Any]) -> int:
    content = msg.get("content") or ""
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False)
    return estimate_tokens(str(content))


def compress_context(
    messages: List[Dict[str, Any]],
    budget: int = 8000,
    summary: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """按 Token 预算压缩消息列表。

    :param messages: 完整消息列表
    :param budget: Token 预算上限
    :param summary: 可选的旧消息摘要文本（如无，压缩时提示未摘要）
    :return: (压缩后消息, 压缩统计)
    """
    before = sum(_message_tokens(m) for m in messages)
    if before <= budget:
        return messages, {"before": before, "after": before, "compressed": False}

    # 保留 system 消息
    system = [m for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]

    # 滚动窗口：从最新消息向前保留，直到预算耗尽
    kept: List[Dict[str, Any]] = []
    used = sum(_message_tokens(m) for m in system)
    for msg in reversed(rest):
        t = _message_tokens(msg)
        if used + t > budget:
            break
        kept.append(msg)
        used += t
    kept.reverse()

    dropped = len(rest) - len(kept)
    note = summary or "（历史消息已压缩，未提供摘要）"
    if dropped > 0:
        system.insert(
            1,
            {
                "role": "system",
                "content": f"[上下文压缩提示] 已丢弃 {dropped} 条早期消息 "
                f"（{before}→{used} tokens）。{note}",
            },
        )

    stats = {
        "before": before,
        "after": used,
        "compressed": True,
        "dropped": dropped,
    }
    return system + kept, stats
