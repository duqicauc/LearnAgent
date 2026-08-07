"""LLM 层：纯模型调用，不含权限判定、工具执行与对话循环。"""
from .client import LLMClient

__all__ = ["LLMClient"]
