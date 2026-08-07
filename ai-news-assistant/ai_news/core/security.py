"""安全防护：Prompt 注入检测、URL 白名单校验、日志脱敏。

知识点：安全防护——Agent 必须对用户输入、抓取到的外部内容保持警惕。
"""
import re
from typing import Optional, Set

from ..scrapers.base import ALLOWED_SITE_DOMAINS

# ── Prompt 注入检测模式（中英文常见注入句式） ──
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts?|rules)",
    r"disregard\s+(your\s+)?(instructions|rules)",
    r"忽略(之前|以上|你)?(的)?(所有)?(指令|规则|提示)",
    r"请(假装|扮演).{0,20}(管理员|开发|不受限|越狱)",
    r"jailbreak|do\s+anything\s+now",
    r"输出.{0,10}(你的|系统).{0,10}(system\s*prompt|提示词)",
]

# 日志/输出脱敏：隐藏 sk- 开头密钥
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
SECRET_PATTERN_CN = re.compile(r"(api[_-]?key|token)\s*[:=]\s*[\w\-]{8,}", re.IGNORECASE)


def detect_prompt_injection(text: str) -> Optional[str]:
    """检测文本中的 Prompt 注入模式，命中返回匹配模式，否则返回 None。"""
    if not text:
        return None
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def validate_url(url: str, allowed_domains: Optional[Set[str]] = None) -> bool:
    """URL 白名单校验：仅允许抓取器声明过的站点域名。"""
    domains = allowed_domains or set(ALLOWED_SITE_DOMAINS.values())
    return any(domain in url for domain in domains)


def mask_secret(text: str) -> str:
    """脱敏：将文本中的 API Key 类内容替换为掩码。"""
    if not text:
        return text
    text = SECRET_PATTERN.sub("sk-***", text)
    return SECRET_PATTERN_CN.sub(r"\1=***", text)
