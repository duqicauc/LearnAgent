"""CLI 入口：AI 信息搜索助手（多智能体版）。

运行方式：
    python -m ai_news.main

流程：用户指令 → 安全检测 → 主编二阶段规划 → 并行抓取 → 数据管道
      → AI 分析 → 报告大纲 → 状态机全程可观测
"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .agents.analyzer import AnalyzerAgent
from .agents.fetcher import FetcherAgent
from .agents.planner import PlannerAgent
from .agents.reporter import ReporterAgent
from .core.context import compress_context, estimate_tokens
from .core.evaluator import Evaluator
from .core.llm import LLM
from .core.memory import Memory
from .core.rag import SimpleRAG
from .core.security import detect_prompt_injection, mask_secret
from .core.state_machine import TaskStateMachine
from .core.tool_registry import ToolRegistry
from .core.tracing import DATA_DIR, Tracer
from .pipeline import run_pipeline
from .report_generator import update_archive_index
from .skills.cn_media import cn_media_skill
from .skills.intl_media import intl_media_skill
from .skills.labs_blog import labs_blog_skill
from .skills.open_source import open_source_skill
from .skills.papers import papers_skill
from .skills.registry import SkillRegistry
from .tools.schemas import BUILTIN_TOOLS, FETCH_TOOLS

load_dotenv()

REPORTS_DIR = DATA_DIR / "reports"


def build_skill_registry() -> SkillRegistry:
    """注册全部技能（热插拔入口）。"""
    registry = SkillRegistry()
    for skill in (open_source_skill, papers_skill, labs_blog_skill, cn_media_skill, intl_media_skill):
        registry.register(skill)
    return registry


def build_registry() -> ToolRegistry:
    """注册全部工具：占位工具 + 5 个抓取工具。"""
    registry = ToolRegistry()
    for func, schema in BUILTIN_TOOLS + FETCH_TOOLS:
        registry.register(func, schema)
    return registry


def run_task(
    user_input: str,
    memory: Optional[Memory] = None,
    evaluator: Optional[Evaluator] = None,
) -> dict:
    """执行一次完整任务，返回结果摘要（供 CLI 展示与测试调用）。"""
    tracer = Tracer.get()

    # ── 安全检测 ──
    injection = detect_prompt_injection(user_input)
    if injection:
        print(f"  [安全] 检测到 Prompt 注入模式：{injection}，已拦截。")
        tracer.step("security", "prompt_injection_blocked", {"pattern": injection})
        return {"status": "blocked"}

    task_id = uuid.uuid4().hex[:8]
    sm = TaskStateMachine(task_id)
    started = time.monotonic()
    if memory is not None:
        memory.forget("working")  # 短期记忆：新任务开始前清空上一任务的工作状态

    try:
        # ── 主编：阶段一（纯思考规划）──
        print("  [主编] 阶段一：思考规划中...")
        planner = PlannerAgent(LLM(), build_registry(), build_skill_registry())
        plan = planner.plan(user_input)
        if memory is not None:
            memory.write("working", "plan", plan)
        print(f"  [计划] {json.dumps(plan, ensure_ascii=False)}")
        if not plan.get("sites"):
            print("  [主编] 未解析到站点计划，任务中止。")
            return {"status": "no_plan", "plan": plan}

        # ── 主编：阶段二（开放工具循环，验证计划）──
        print("  [主编] 阶段二：工具循环验证计划中...")
        verify_summary = planner.execute(plan)
        print(f"  [主编] 站点验证: {mask_secret(verify_summary)[:150]}")
        sm.transition("fetching")

        # ── 抓取 Agent：并行调度 ──
        print(f"  [抓取] 并行抓取 {len(plan['sites'])} 个站点...")
        fetcher = FetcherAgent()
        raw_by_source = fetcher.fetch(plan["sites"], plan.get("keyword") or None, plan.get("limit", 10))
        sm.transition("cleaning")

        # ── 数据管道 ──
        result = run_pipeline(raw_by_source)
        items, stats = result["items"], result["stats"]
        if memory is not None:
            memory.write("working", "stats", stats)
        print(f"  [管道] 总条目 {stats['total']} | 去重 {stats['deduped']} | 来源 {stats['by_source']}")
        if not items:
            print("  [管道] 无有效数据，任务中止。")
            return {"status": "empty", "stats": stats}
        sm.transition("analyzing")

        # ── 分析 Agent ──
        print("  [分析] AI 综合分析中...")
        analyzer = AnalyzerAgent(LLM())
        analysis = analyzer.analyze(items, stats)
        print(f"  [分析] 摘要: {mask_secret(str(analysis.get('summary', '')))[:120]}")

        # ── 报告 Agent ──
        sm.transition("generating")
        print("  [报告] 生成报告大纲...")
        reporter = ReporterAgent(LLM())
        report = reporter.build_report(analysis, items, stats)
        print(f"  [报告] 标题: {report.get('title', '')}")

        sm.transition("completed")
        sm.complete()

        # ── 落盘（数据全量保留：原始抓取 raw + 处理结果 items）──
        output = {
            "task_id": task_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "user_input": mask_secret(user_input),
            "plan": plan,
            "stats": stats,
            "items": items,          # 抓取条目（报告渲染需来源/时间/多源信息）
            "raw": raw_by_source,    # 原始抓取数据（去重/清理前的完整内容）
            "analysis": analysis,
            "report": report,
        }
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = REPORTS_DIR / f"task_{task_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        update_archive_index(output)  # 归档索引（长期记忆的结构化清单）

        elapsed = time.monotonic() - started
        print(f"  [完成] 耗时 {elapsed:.1f}s | 报告已保存: {out_path}")

        # ── M4：长期记忆 + 会话记忆 + 评估评分 ──
        if memory is not None:
            memory.remember_task(output)  # 长期记忆（history ≤ 50 条）
            memory.write("session", f"task_{task_id}", {  # 会话记忆（进程内跨任务）
                "title": report.get("title", ""),
                "summary": analysis.get("summary", ""),
                "items": stats.get("total", 0),
            })
        if evaluator is not None:
            score = evaluator.run_and_save(output)
            print(
                f"  [评估] 完整性 {score['completeness']} | 覆盖面 {score['coverage']} "
                f"| 深度 {score['depth']} | 综合 {score['overall']}"
            )

        tracer.step("main", "task_completed", {"task_id": task_id, "cost_sec": round(elapsed, 1)})
        return {"status": "ok", "task_id": task_id, "report": report, "out_path": str(out_path)}

    except Exception as exc:  # noqa: BLE001 - 任务级兜底
        sm.fail()
        print(f"  [错误] {type(exc).__name__}: {exc}")
        tracer.step("main", "task_failed", {"task_id": task_id, "error": str(exc)})
        return {"status": "error", "error": str(exc)}


HELP_TEXT = """可用命令：
  exit / quit    退出
  reset          重置（清空工作记忆）
  trace          显示 trace 日志路径
  /recall <问题>  通过历史记忆回答（RAG 检索）
  /history       显示历史任务要点
  /memory        显示记忆统计
  /forget        清空长期记忆
  help           显示本帮助
其他输入将触发一次完整的 AI 信息搜索任务（示例：
  「抓取本周最新的开源 AI 模型动态」
  「看看最近有哪些值得关注的 AI 论文」）"""


def handle_recall(question: str, rag: SimpleRAG, memory: Memory, llm: LLM) -> str:
    """RAG 召回历史要点，交由 LLM 回答跨会话问题。"""
    context = rag.build_context(question)
    if not context:
        return "记忆中没有与问题相关的历史报告要点。"
    print(f"  [RAG] 召回 {len(rag.retrieve(question))} 段历史要点")
    messages = [
        {"role": "system", "content": "你是 AI 信息搜索助手。仅基于给定的历史报告要点回答用户问题，要点不足时如实说明。"},
        {"role": "user", "content": f"历史要点：\n{context}\n\n问题：{question}"},
    ]
    reply = llm.chat(messages, max_tokens=1024)
    return reply.content or "（无回复）"


def main() -> None:
    tracer = Tracer.get()
    # M4：记忆 + RAG 索引 + 评估器
    memory = Memory()
    rag = SimpleRAG()
    rag.index(memory.history_documents())
    evaluator = Evaluator()
    llm = LLM()

    print("=== AI 信息搜索助手（多智能体版 + M4 记忆/RAG/评估）===")
    print(HELP_TEXT)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        cmd = user_input.lower()
        if cmd in ("exit", "quit"):
            print("再见！")
            break
        if cmd == "reset":
            memory.forget("working")
            print("工作记忆已重置。")
            continue
        if cmd == "trace":
            print(f"trace 日志: {tracer.file}")
            continue
        if cmd == "help":
            print(HELP_TEXT)
            continue
        if cmd.startswith("/recall "):
            print(f"\n--- RAG 召回 ---")
            print(f"\nAI: {handle_recall(user_input[len('/recall '):].strip(), rag, memory, llm)}")
            continue
        if cmd == "/history":
            history = memory.long_term.get("history", [])
            print(f"\n历史任务 {len(history)} 条：")
            for h in history[-10:]:
                print(f"  - [{h.get('ts')}] {h.get('title')} | {str(h.get('summary'))[:60]}")
            continue
        if cmd == "/memory":
            history = memory.long_term.get("history", [])
            print(f"\n记忆状态：工作 {len(memory.working)} 条 | 会话 {len(memory.session)} 条 | 长期历史 {len(history)} 条")
            continue
        if cmd == "/forget":
            memory.forget("long_term")
            rag.index([])
            print("长期记忆已清空。")
            continue

        print("\n--- 任务开始 ---")
        result = run_task(user_input, memory=memory, evaluator=evaluator)
        if result.get("status") == "ok":
            rag.index(memory.history_documents())  # 新记忆入库后重建 RAG 索引
        print("--- 任务结束 ---")


if __name__ == "__main__":
    main()
