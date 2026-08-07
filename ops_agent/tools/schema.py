"""Tool Schema 层：工具抽象基类、风险元数据与 LLM function schema 构建。"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class AccessLevel:
    """权限范围：读取 / 写入 / 删除 / 管理。"""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


class RecoveryCost:
    """恢复成本：低 / 中 / 高。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImpactScope:
    """影响范围：单条记录 / 单个服务 / 全局资源。"""

    RECORD = "record"
    SERVICE = "service"
    GLOBAL = "global"


class RiskLevel:
    """风险等级：低 / 中 / 高 / 严重。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Tool(ABC):
    """工具抽象基类。所有业务工具需继承此类并实现 name/description/run。

    授权元数据（子类可覆盖）：
    - permission: 执行此工具所需的最低权限标识
    - approval:   是否需要人工审批（True 时授权结果为 review）
    - forbidden:  是否禁止 Agent 执行（True 时授权结果恒为 forbidden）

    风险元数据（子类可覆盖）：
    - access_level:   权限范围（read/write/delete/admin）
    - state_change:   是否改变文件、数据或外部系统
    - reversible:     是否可撤销
    - recovery_cost:  恢复成本（low/medium/high）
    - impact_scope:   影响范围（record/service/global）
    - sensitive:      是否读取或传输隐私与机密数据
    """

    permission: str = "read"
    approval: bool = False
    forbidden: bool = False

    # 执行上下文：由 ToolRegistry.execute_tool 注入（如当前操作者 user_id）
    execution_user: str = "default"

    access_level: str = AccessLevel.READ
    state_change: bool = False
    reversible: bool = True
    recovery_cost: str = RecoveryCost.LOW
    impact_scope: str = ImpactScope.RECORD
    sensitive: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名，需与 LLM 调用时的 function.name 保持一致。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，提供给 LLM 用于决策何时调用此工具。"""

    @abstractmethod
    def get_parameters(self) -> Dict[str, Any]:
        """返回该工具的 JSON Schema 参数定义，用于注册给 LLM。"""

    @abstractmethod
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行工具逻辑，入参为解析后的参数字典，返回字符串结果。"""

    def risk_level(self) -> str:
        """综合风险元数据派生风险等级。

        critical: 删除权限，或状态变化且不可逆，或全局范围 + 状态变化
        high:     write/admin 权限，或恢复成本为 high
        medium:   只读但涉及敏感数据
        low:      其余纯读、可逆、低恢复成本场景
        """
        if (
            self.access_level == AccessLevel.DELETE
            or (self.state_change and not self.reversible)
            or (self.impact_scope == ImpactScope.GLOBAL and self.state_change)
        ):
            return RiskLevel.CRITICAL
        if (
            self.access_level in (AccessLevel.WRITE, AccessLevel.ADMIN)
            or self.recovery_cost == RecoveryCost.HIGH
        ):
            return RiskLevel.HIGH
        if self.sensitive:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def risk_summary(self) -> str:
        """生成一行风险摘要，追加到 schema description 供模型知情。"""
        parts = [
            f"权限范围:{self.access_level}",
            f"状态变化:{'是' if self.state_change else '否'}",
            f"可逆:{'是' if self.reversible else '否'}",
            f"恢复成本:{self.recovery_cost}",
            f"影响范围:{self.impact_scope}",
            f"敏感数据:{'是' if self.sensitive else '否'}",
            f"风险等级:{self.risk_level()}",
        ]
        summary = "；".join(parts)
        if self.sensitive:
            summary += (
                "。注意：涉及敏感数据，回复中不得回传明文敏感字段"
                "（如手机号、用户 ID），需脱敏展示"
            )
        return summary

    def to_function_schema(self) -> Dict[str, Any]:
        """构建给 LLM 使用的 function 调用 Schema，尾部附加风险摘要。"""
        description = f"{self.description}\n【风险信息】{self.risk_summary()}"
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": self.get_parameters(),
            },
        }
