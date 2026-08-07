"""程序入口：装配各层（config → llm → tools → runtime → agent）。

支持三种运行模式：
- 交互式 Agent：默认（--role / --resume）
- 审批入口：--list-approvals / --approve TASK_ID / --reject TASK_ID [--reason]
"""
import argparse

from agent import AgentLoop
from config.permissions import Identity
from config.settings import Settings
from llm.client import LLMClient
from runtime.approval import ApprovalError, ApprovalManager
from runtime.audit import AuditRecorder
from runtime.idempotency import IdempotencyGuard
from runtime.memory import MemoryManager
from runtime.persistence import SessionStore
from runtime.policy import PolicyEvaluator
from tools import (
    DropDatabaseTool,
    LogQueryTool,
    MetricQueryTool,
    QueryMemoryTool,
    ReleaseQueryTool,
    RestartServiceTool,
    SaveMemoryTool,
    TicketQueryTool,
    ToolRegistry,
)


def register_all_tools() -> ToolRegistry:
    settings = Settings.load()
    memory = MemoryManager(settings.memory_db)
    registry = ToolRegistry()
    registry.register(LogQueryTool())
    registry.register(MetricQueryTool())
    registry.register(ReleaseQueryTool())
    registry.register(TicketQueryTool())
    registry.register(RestartServiceTool())
    registry.register(DropDatabaseTool())
    registry.register(SaveMemoryTool(memory))
    registry.register(QueryMemoryTool(memory))
    return registry


def build_agent(
    identity: Identity = Identity(name="张工", role="ops"),
    resume: bool = False,
) -> AgentLoop:
    settings = Settings.load()

    registry = register_all_tools()
    policy = PolicyEvaluator(registry)
    llm = LLMClient(settings)

    return AgentLoop(
        llm=llm,
        registry=registry,
        policy=policy,
        identity=identity,
        settings=settings,
        idempotency=IdempotencyGuard(),
        audit=AuditRecorder(settings.audit_dir),
        session_store=SessionStore(settings.session_dir, agent_id=identity.name),
        approval=ApprovalManager(settings.approval_dir),
        resume=resume,
    )


def _print_task(task) -> None:
    status_icon = {"pending": "🕐", "approved": "✅", "rejected": "🚫"}.get(
        task.status, "❓"
    )
    print(
        f"  {status_icon} [{task.status}] {task.task_id} "
        f"{task.tool}({task.arguments}) by {task.user}({task.role}) "
        f"@ {task.created_at}"
    )
    if task.decision:
        extra = f"replayed={task.replayed}"
        if task.reason:
            extra += f", reason={task.reason}"
        print(f"       └ 决定: {task.decision} @ {task.decided_at}（{extra}）")
    if task.result:
        print(f"       └ 结果: {task.result[:200]}")


def run_approval_entry(args) -> None:
    """独立审批入口：根据唯一任务编号处理人工审批。"""
    settings = Settings.load()
    registry = register_all_tools()
    manager = ApprovalManager(settings.approval_dir)

    if args.list_approvals:
        tasks = manager.list_all()
        if not tasks:
            print("暂无审批任务。")
            return
        print(f"审批任务（共 {len(tasks)} 条）：")
        for task in tasks:
            _print_task(task)
        pending = manager.list_pending()
        if pending:
            print(
                f"\n待审批 {len(pending)} 条。处理："
                f"python main.py --approve <TASK_ID> 或 --reject <TASK_ID> --reason '...'"
            )
        return

    if args.approve:
        try:
            task = manager.approve(
                args.approve,
                # 批准后只执行之前保存的那一个动作（人工已授权，不再走授权校验）
                lambda tool, tool_args: registry.execute_tool(tool, tool_args),
            )
        except ApprovalError as e:
            print(f"审批失败：{e}")
            return
        print("审批结果：")
        _print_task(task)
        # 将审批结果回灌到关联会话，供 --continue / --resume 注入模型上下文
        SessionStore(settings.session_dir, agent_id=task.session_id or task.user).append_approval_result(
            {
                "task_id": task.task_id,
                "tool": task.tool,
                "arguments": task.arguments,
                "decision": "approve",
                "result": task.result,
                "consumed": False,
            }
        )
        print(
            f"\n已批准并执行动作 {task.tool}，结果已回灌到会话。"
            f"可用 --continue 自动续写原任务。"
        )
        return

    if args.reject:
        try:
            task = manager.reject(args.reject, reason=args.reason)
        except ApprovalError as e:
            print(f"审批失败：{e}")
            return
        print("审批结果：")
        _print_task(task)
        # 拒绝结果回灌到关联会话
        SessionStore(settings.session_dir, agent_id=task.session_id or task.user).append_approval_result(
            {
                "task_id": task.task_id,
                "tool": task.tool,
                "arguments": task.arguments,
                "decision": "reject",
                "reason": task.reason,
                "consumed": False,
            }
        )
        print(f"\n已拒绝动作 {task.tool}，未执行，结果已回灌到会话。")
        return


def run_memory_entry(args) -> None:
    """记忆管理入口：查看 / 检索某用户的长期记忆。"""
    settings = Settings.load()
    memory = MemoryManager(settings.memory_db)
    user = args.role if args.role in ("ops", "viewer", "guest") else "ops"
    identity = Identity(name="张工", role=user)

    if args.memory_list:
        records = memory.list_all(identity.name)
        if not records:
            print(f"{identity.name} 暂无记忆。")
            return
        print(f"{identity.name} 的记忆（共 {len(records)} 条）：")
        for r in records:
            mark = {
                "active": "✅", "superseded": "↩️", "expired": "⌛",
            }.get(r.status, "❓")
            print(
                f"  {mark} [{r.status}] v{r.version} #{r.id} "
                f"{r.type}/{r.topic} conf={r.confidence} scope={r.scope or '-'}"
            )
            print(f"      内容: {r.content}")
            if r.summary:
                print(f"      总结: {r.summary}")
            if r.valid_until:
                print(f"      有效期至: {r.valid_until}")
        return

    if args.memory_search:
        records = memory.query(identity.name, keyword=args.memory_search)
        if not records:
            print(f"未找到与「{args.memory_search}」相关的生效记忆。")
            return
        print(f"检索「{args.memory_search}」命中 {len(records)} 条生效记忆：")
        for r in records:
            print(f"  ✅ v{r.version} #{r.id} [{r.type}] {r.content}")
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ops Agent")
    parser.add_argument("--role", default="ops", choices=["ops", "viewer", "guest"],
                        help="当前身份角色（ops=运维工程师 / viewer=只读访客 / guest=访客）")
    parser.add_argument("--resume", action="store_true", help="从持久化快照恢复会话")
    parser.add_argument("--list-approvals", action="store_true",
                        help="列出全部审批任务")
    parser.add_argument("--approve", metavar="TASK_ID",
                        help="批准指定审批任务并执行保存的动作")
    parser.add_argument("--reject", metavar="TASK_ID",
                        help="拒绝指定审批任务（不执行）")
    parser.add_argument("--reason", default="", help="拒绝原因（配合 --reject）")
    parser.add_argument("--continue", dest="continue_run", action="store_true",
                        help="恢复暂停会话并自动续写原任务（需先审批）")
    parser.add_argument("--memory-list", action="store_true",
                        help="列出当前身份的全部长期记忆")
    parser.add_argument("--memory-search", metavar="KEYWORD",
                        help="按关键词检索当前身份的生效记忆")
    args = parser.parse_args()

    if args.list_approvals or args.approve or args.reject:
        run_approval_entry(args)
    elif args.memory_list or args.memory_search:
        run_memory_entry(args)
    elif args.continue_run:
        agent = build_agent(
            identity=Identity(name="张工", role=args.role), resume=True
        )
        print("\n=== 继续原任务 ===")
        reply = agent.step(
            "审批已处理完毕，请结合审批结果通知与已有数据继续完成原任务，给出最终结论。"
        )
        print(f"\nAI: {reply}")
    else:
        agent = build_agent(
            identity=Identity(name="张工", role=args.role), resume=args.resume
        )
        agent.run_interactive()
