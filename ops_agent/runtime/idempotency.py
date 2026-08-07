"""幂等执行：相同（工具, 规范化参数）的重复调用直接返回首次结果。

防止 Agent Loop 因循环/重试对同一操作反复执行产生副作用。
"""
import json
from typing import Any, Callable, Dict, Tuple


class IdempotencyGuard:
    """幂等守卫：按调用 key 缓存结果，重复调用命中缓存不重复执行。"""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._cache: Dict[str, str] = {}

    def _key(self, name: str, args: Dict[str, Any], user: str = "default") -> str:
        canonical = json.dumps(
            args, sort_keys=True, ensure_ascii=False, default=str
        )
        return f"{user}:{name}:{canonical}"

    def execute(
        self,
        name: str,
        args: Dict[str, Any],
        fn: Callable[[], str],
        user: str = "default",
    ) -> Tuple[str, bool]:
        """执行（或重放）一次调用。

        返回 (result, replayed)：replayed=True 表示命中幂等缓存，未真实执行。
        幂等 key 包含 user，避免不同用户之间的调用互相重放。
        """
        if not self.enabled:
            return fn(), False
        key = self._key(name, args, user)
        if key in self._cache:
            return self._cache[key], True
        result = fn()
        self._cache[key] = result
        return result, False

    def clear(self) -> None:
        self._cache.clear()
