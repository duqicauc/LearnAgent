"""Policy Layer：权限与审批判定。

只负责「判定」，不执行真实工具：
- authorize()       返回决策（allow/review/reject/forbidden）
- denial_result()   构造非 allow 时回灌给模型的授权结果 JSON
真实执行由 Agent Loop 经幂等层调用 ToolRegistry。
"""
import json
from typing import Any, Dict, Set, Tuple

from tools.registry import ToolRegistry
from tools.schema import RiskLevel


class AuthorizationDecision:
    """授权判定结果。只有 ALLOW 才允许执行真实函数。"""

    ALLOW = "allow"        # 允许执行
    REVIEW = "review"      # 需要审批，暂不执行
    REJECT = "reject"      # 当前身份无所需权限，拒绝
    FORBIDDEN = "forbidden"  # 工具被标记为禁止执行


class PolicyEvaluator:
    """授权策略评估器：基于工具元数据与当前身份权限做决策。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def authorize(self, name: str, user_permissions: Set[str]) -> str:
        """授权判定，返回 AuthorizationDecision 中的一种。

        判定优先级：
        forbidden（禁止执行）> reject（无权限）> review（显式审批或高风险自动升级）> allow。
        高风险自动升级：risk_level 为 high/critical 时强制进入 review，即使未显式设置 approval。
        """
        tool = self.registry.get_tool(name)
        if tool.forbidden:
            return AuthorizationDecision.FORBIDDEN
        if tool.permission not in user_permissions:
            return AuthorizationDecision.REJECT
        if tool.approval or tool.risk_level() in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        ):
            return AuthorizationDecision.REVIEW
        return AuthorizationDecision.ALLOW

    def denial_result(self, name: str, decision: str) -> str:
        """构造非 allow 时回灌给模型的授权结果 JSON。"""
        tool = self.registry.get_tool(name)
        messages = {
            AuthorizationDecision.FORBIDDEN: (
                f"工具 {name} 已被标记为禁止执行（forbidden=true），Agent 不得调用，未执行真实函数。"
            ),
            AuthorizationDecision.REJECT: (
                f"当前身份缺少执行 {name} 所需的权限，操作被拒绝（reject），未执行真实函数。"
            ),
            AuthorizationDecision.REVIEW: (
                f"操作 {name} 需要审批（approval=true 或风险等级为 {tool.risk_level()}），"
                "已进入 review 待审批状态，未执行真实函数。"
            ),
        }
        return json.dumps(
            {
                "authorization": decision,
                "tool": name,
                "risk_level": tool.risk_level(),
                "executed": False,
                "message": messages.get(decision, f"操作 {name} 未获授权，未执行。"),
            },
            ensure_ascii=False,
            indent=2,
        )

    def evaluate(
        self,
        name: str,
        parameters: Any,
        user_permissions: Set[str],
    ) -> Tuple[str, str]:
        """判定并返回 (decision, result) 的便捷入口。

        decision 为 allow 时 result 为真实执行结果；否则为授权拒绝 JSON。
        用于不依赖幂等层的简单场景。
        """
        decision = self.authorize(name, user_permissions)
        if decision != AuthorizationDecision.ALLOW:
            return decision, self.denial_result(name, decision)
        return decision, self.registry.execute_tool(name, parameters)
