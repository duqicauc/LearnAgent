"""CLI 入口：AI 信息搜索助手一键演示。

运行方式（需在项目根目录）：
    python3 -m ai_news.cli                          # 完整模式（交互式报告）
    python3 -m ai_news.cli --quick "抓取AI论文动态"  # 快速模式 + 自定义指令

流程：任务编排（规划→抓取→管道→分析→报告）→ 生成交互式 HTML 报告。
"""
import argparse
import json
import sys

from .core.evaluator import Evaluator
from .core.memory import Memory
from .main import run_task
from .report_generator import generate_report, update_archive_index

DEFAULT_QUERY = "抓取本周最新的 AI 前沿动态，重点关注模型发布与产业资讯"


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 信息搜索助手")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="任务指令")
    parser.add_argument("--quick", action="store_true", help="快速模式")
    args = parser.parse_args()

    print(f"任务指令: {args.query}\n")
    result = run_task(args.query, memory=Memory(), evaluator=Evaluator())

    if result.get("status") != "ok":
        print(f"\n任务失败: {result}")
        sys.exit(1)

    # 加载完整任务输出（含 items/analysis/stats）用于报告渲染
    with open(result["out_path"], "r", encoding="utf-8") as f:
        task_output = json.load(f)

    mode = "quick" if args.quick else "full"
    html_path = generate_report(task_output, mode=mode)
    update_archive_index(task_output, html_path)  # 归档索引补写 HTML 文件名
    print(f"\nHTML 报告已生成: {html_path}")
    print(f"评估: {result.get('evaluation', '见 evaluation 文件')}")


if __name__ == "__main__":
    main()
