"""权限策略配置：角色 → 权限集合的映射，与身份定义。"""
from dataclasses import dataclass
from typing import Dict, Set


@dataclass(frozen=True)
class Identity:
    """当前操作者身份。"""

    name: str
    role: str


# 角色 → 权限集合
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    # 运维工程师：只读全量 + 服务操作权限（重启仍需审批）+ 长期记忆读写
    "ops": {
        "log:read",
        "metric:read",
        "release:read",
        "ticket:read",
        "service:write",
        "memory:read",
        "memory:write",
    },
    # 只读访客：仅日志与指标查看 + 记忆只读
    "viewer": {"log:read", "metric:read", "memory:read"},
    # 访客：无任何权限
    "guest": set(),
}


def permissions_for(identity: Identity) -> Set[str]:
    """返回某身份对应的权限集合。"""
    return set(ROLE_PERMISSIONS.get(identity.role, set()))
