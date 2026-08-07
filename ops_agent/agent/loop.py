"""Agent Loop：编排 LLM 调用、工具执行、授权策略、幂等、审计与循环防护。

运行状态统一保存在 AgentState 中（消息历史 / 任务内与累计执行指标 /
工具执行轨迹 / 停止状态），本层不另设游离运行变量。
"""
import json
from typing import Any, Dict, List, Optional

from agent.messages import (
    assistant_message,
    system_message,
    tool_message,
    user_message,
)
from agent.context import ContextBuilder
from agent.state import AgentState, ToolTrace
from agent.stopping import StoppingPolicy
from config.permissions import Identity, permissions_for
from config.settings import Settings
from llm.client import LLMClient
from runtime.audit import AuditRecorder
from runtime.approval import ApprovalManager
from runtime.idempotency import IdempotencyGuard
from runtime.persistence import SessionStore
from runtime.policy import AuthorizationDecision, PolicyEvaluator
from tools.registry import ToolRegistry


OPS_SYSTEM_PROMPT = (
    "你是一个运维智能体（Ops Agent），可以查询应用日志和系统指标，帮助工程师快速定位线上问题。"
    "请根据用户的问题，优先使用可用的工具获取真实数据，再基于数据给出分析结论。"
    "输出要简洁、结论明确；如需调用工具，请直接调用，不要向用户解释工具调用细节。\n"
    "【授权机制】每次工具调用都会先经过授权校验：只有 authorization=allow 的操作才会真实执行。"
    "若工具返回 review（需审批）、reject（当前身份无权限）或 forbidden（该工具被禁止执行），"
    "说明该操作未被真实执行，请如实向用户说明原因，不要虚构执行结果。\n"
    "【敏感数据】工具返回的数据可能包含手机号、用户 ID 等隐私信息，"
    "回复用户时必须脱敏展示（如 138****1234），不得回传完整明文。\n"
    "【长期记忆】你有 save_memory / query_memory 工具，用于维护该用户的长期记忆。"
    "仅当用户明确表达以后还会用到的信息（偏好、约束、稳定事实、决策背景）时才保存，"
    "不要保存临时性、一次性内容，也不要自行推断用户偏好。"
    "当用户提到可能已约定的偏好或历史决策时，先 query_memory 检索再行动。"
    "记忆按用户隔离，不要保存本用户以外的信息。"
)


class AgentLoop:
    """Agent 主循环：一次 step 内驱动多轮 tool-calling，直到纯文字答复或触发停止条件。"""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        policy: PolicyEvaluator,
        identity: Identity,
        *,
        system_prompt: Optional[str] = None,
        settings: Optional[Settings] = None,
        stopping: Optional[StoppingPolicy] = None,
        idempotency: Optional[IdempotencyGuard] = None,
        audit: Optional[AuditRecorder] = None,
        session_store: Optional[SessionStore] = None,
        approval: Optional[ApprovalManager] = None,
        context_builder: Optional[ContextBuilder] = None,
        resume: bool = False,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.policy = policy
        self.identity = identity
        self.system_prompt = system_prompt or OPS_SYSTEM_PROMPT

        self.settings = settings or Settings.load()
        self.stopping = stopping or StoppingPolicy()
        self.idempotency = idempotency or IdempotencyGuard()
        self.audit = audit or AuditRecorder(self.settings.audit_dir)
        self.session_store = session_store or SessionStore(
            self.settings.session_dir, agent_id=identity.name
        )
        # 异步授权：审批任务管理（暂停 → 人工审批 → 恢复）
        self.approval = approval or ApprovalManager(self.settings.approval_dir)
        # 上下文管理：构建本轮模型调用所需的消息子集
        self.context_builder = context_builder or ContextBuilder()

        # 统一运行状态：消息历史 + 执行指标 + 工具轨迹 + 停止状态
        self.state = AgentState()
        self.state.messages.append(system_message(self.system_prompt))

        if resume:
            self._resume()

    def _resume(self) -> None:
        """从持久化快照恢复会话（messages + state + 工具轨迹）。

        快照文件结构为 {messages, state, approval_results}：messages 为消息历史，
        state 为 AgentState.snapshot()，approval_results 为审批结果事件。
        恢复时将未消费的审批结果注入模型上下文（通知 Agent 审批决定）。
        """
        snapshot = self.session_store.load()
        if not snapshot:
            return
        messages = snapshot.get("messages", [])
        if messages:
            self.state = AgentState.from_snapshot(snapshot.get("state", {}))
            self.state.messages.reset(messages)
            print(
                f"[♻️ 恢复会话] 已加载 {len(messages)} 条消息，"
                f"轮数 {self.state.rounds}，工具调用 {self.state.total_tool_calls} 次，"
                f"工具轨迹 {len(self.state.tool_traces)} 条"
            )
            self._inject_approval_results()

    def _inject_approval_results(self) -> None:
        """将审批入口回灌的审批结果注入上下文并标记已消费。"""
        results = self.session_store.unconsumed_approval_results()
        if not results:
            return
        for r in results:
            notice = self._format_approval_result(r)
            self.state.messages.append(user_message(notice))
            print(
                f"  [📨 审批结果] {r.get('task_id')} -> "
                f"{r.get('decision')}（{r.get('tool')}）"
            )
        self.session_store.mark_approval_results_consumed(
            [r.get("task_id") for r in results]
        )
        self._persist()  # 保存注入后的最新状态

    @staticmethod
    def _format_approval_result(result: Dict[str, Any]) -> str:
        """格式化审批结果通知，注入为 user 消息。"""
        tool = result.get("tool", "?")
        arguments = result.get("arguments", {})
        if result.get("decision") == "approve":
            return (
                f"【审批结果通知】你此前发起的操作 {tool}({arguments}) "
                f"已获人工批准并执行，执行结果：{result.get('result')}。"
                "请结合此结果与已有数据继续推进原任务。"
            )
        return (
            f"【审批结果通知】你此前发起的操作 {tool}({arguments}) "
            f"已被人工拒绝（原因：{result.get('reason')}），未执行。"
            "请基于已有数据给出结论或替代建议，不要假设该操作已执行。"
        )

    def reset(self) -> None:
        self.state.reset()
        self.state.messages.append(system_message(self.system_prompt))
        self.idempotency.clear()

    def _persist(self) -> None:
        self.session_store.save(
            self.state.messages.as_list(), self.state.snapshot()
        )

    def step(self, user_input: str) -> str:
        """处理一轮用户输入，驱动多轮 tool-calling 直到收敛或触发停止条件。

        循环防护按「单次任务（step）内」独立计数：begin_task 时重置任务内指标，
        避免上一个请求的调用次数拦截本请求；幂等缓存仍全局生效。
        """
        self.state.begin_task()
        self.state.messages.append(user_message(user_input))

        tool_schemas = self.registry.function_schemas()

        while True:
            # 循环防护：基于状态中的任务内指标判定
            stop_reason = self.stopping.check(self.state)
            if stop_reason:
                self.state.stop(stop_reason)
                print(f"\n  [⛔ 循环防护] {self.state.stop_reason}")
                self.state.messages.append(
                    user_message(self.stopping.force_answer_message(stop_reason))
                )
                final_msg = self.llm.chat(
                    self.context_builder.build(
                        self.state.messages.as_list(), user_input
                    )
                )
                reply = final_msg.content or ""
                self.state.messages.append(assistant_message(reply))
                self._persist()
                return reply

            self.state.record_round()

            # 第 1 步：调用 LLM（本轮上下文由 ContextBuilder 构建）
            message = self.llm.chat(
                self.context_builder.build(
                    self.state.messages.as_list(), user_input
                ),
                tools=tool_schemas,
            )

            # 如果模型直接给出纯文字答复
            if not message.tool_calls:
                reply = message.content or ""
                self.state.messages.append(assistant_message(reply))
                self._persist()
                return reply

            # 第 2 步：把 assistant 的 tool_calls 消息放进上下文
            self.state.messages.append(
                assistant_message(
                    message.content,
                    tool_calls=[
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                )
            )

            # 第 3 步：逐个执行工具调用（单个请求里可并行多个 tool_calls）
            paused = False          # 本轮是否因审批暂停
            paused_tasks: List[str] = []
            for tc in message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = (
                        json.loads(tc.function.arguments)
                        if tc.function.arguments
                        else {}
                    )
                except json.JSONDecodeError:
                    func_args = {}

                print(
                    f"\n  [🔧 Round {self.state.rounds}｜工具调用 "
                    f"#{self.state.total_tool_calls + 1}] {func_name}({func_args})"
                )

                # 授权判定
                decision = self.policy.authorize(
                    func_name, self.identity_permissions
                )
                if decision == AuthorizationDecision.REVIEW:
                    # 异步授权：创建审批任务（保存动作与身份），本轮暂停结束
                    task = self.approval.create(
                        func_name, func_args, self.identity
                    )
                    paused = True
                    paused_tasks.append(task.task_id)
                    print(
                        f"  [⏸️ 待审批] 已创建审批任务 {task.task_id}，"
                        f"本轮运行暂停，可稍后通过审批入口处理"
                    )
                    tool_result = json.dumps(
                        {
                            "authorization": "review",
                            "approval_task_id": task.task_id,
                            "tool": func_name,
                            "arguments": func_args,
                            "message": (
                                f"该操作需要人工审批，已创建审批任务 "
                                f"{task.task_id}，本轮运行已暂停。"
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    replayed = False
                    # 结束本次运行：不再执行本批剩余工具调用
                    self.state.messages.append(
                        tool_message(tc.id, func_name, tool_result)
                    )
                    break
                if decision != AuthorizationDecision.ALLOW:
                    tool_result = self.policy.denial_result(func_name, decision)
                    replayed = False
                else:
                    # 幂等执行：相同调用重放缓存，不重复执行真实函数
                    tool_result, replayed = self.idempotency.execute(
                        func_name,
                        func_args,
                        lambda: self.registry.execute_tool(
                            func_name, func_args, user=self.identity.name
                        ),
                        user=self.identity.name,
                    )

                risk_level = self.registry.get_tool(func_name).risk_level()
                print(
                    f"  [🔐 授权结果] {func_name} -> {decision}"
                    f"（风险等级:{risk_level}）"
                )
                if replayed:
                    print(
                        "  [♻️ 幂等命中] 相同调用已执行过，重放缓存结果，未重复执行"
                    )

                preview = (
                    tool_result[:200]
                    + ("..." if len(tool_result) > 200 else "")
                )
                print(f"  [📦 工具结果] {preview}")

                # 记录执行轨迹（统一写入 state）
                trace = ToolTrace(
                    round=self.state.rounds,
                    tool=func_name,
                    arguments=func_args,
                    decision=decision,
                    risk_level=risk_level,
                    replayed=replayed,
                    result=tool_result,
                    result_preview=preview,
                )
                self.state.record_tool_call(func_name, trace)

                # 审计：从执行轨迹生成
                self.audit.record(
                    trace.to_audit_event(
                        user=self.identity.name, role=self.identity.role
                    )
                )

                # 作为 tool 消息回灌给模型
                self.state.messages.append(
                    tool_message(tc.id, func_name, tool_result)
                )

            if paused:
                # 审批暂停收尾：保存检查点后结束本轮运行
                self.state.stop(
                    f"待审批任务 {','.join(paused_tasks)}，本轮运行暂停"
                )
                print(f"\n  [⏸️ 审批暂停] {self.state.stop_reason}")
                self.audit.record(
                    {
                        "user": self.identity.name,
                        "role": self.identity.role,
                        "event": "approval_created",
                        "tasks": paused_tasks,
                        "stop_reason": self.state.stop_reason,
                    }
                )
                self.state.messages.append(
                    user_message(
                        f"【系统提醒】本轮有操作需要人工审批，已创建审批任务："
                        f"{', '.join(paused_tasks)}，本轮运行已暂停。"
                        "请基于已获取的数据向用户说明：这些操作已进入审批流程，"
                        "需通过审批入口按任务编号处理，本轮不再执行任何工具，"
                        "也不要虚构执行结果。"
                    )
                )
                final_msg = self.llm.chat(
                    self.context_builder.build(
                        self.state.messages.as_list(), user_input
                    )
                )
                reply = final_msg.content or ""
                self.state.messages.append(assistant_message(reply))
                self._persist()  # 暂停检查点：保存最新状态，退出后仍可恢复
                return reply

            self._persist()

    @property
    def identity_permissions(self) -> set:
        return permissions_for(self.identity)

    def run_interactive(self) -> None:
        print("=== Ops Agent 已启动（输入 'exit' / 'quit' 退出，'reset' 重置上下文）===")
        print(f"    循环防护：{self.stopping.describe()}")
        print(
            f"    当前身份：{self.identity.name}（角色:{self.identity.role}，"
            f"权限：{sorted(self.identity_permissions)}）"
        )
        print(
            f"    治理能力：授权策略 / 幂等执行 / 审计({self.audit.path}) / 会话持久化"
        )
        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("再见！")
                break
            if user_input.lower() == "reset":
                self.reset()
                print("上下文已重置。")
                continue

            reply = self.step(user_input)
            print(f"\nAI: {reply}")
