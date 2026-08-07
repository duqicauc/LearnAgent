"""产品化 Web 服务：首页 / 任务 API / 报告与归档 / 健康检查。

启动：python -m web.app （默认 0.0.0.0:8080）
"""
import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

from ai_news.core.tracing import DATA_DIR
from .tasks import TaskManager

load_dotenv()  # 本地开发读 .env；容器内由环境变量注入（幂等）

REPORTS_DIR = DATA_DIR / "reports"

app = Flask(__name__)


def _run_web_task(query: str) -> dict:
    """后台任务主体：完整任务 → 生成 HTML 报告 → 更新归档索引。"""
    from ai_news.core.evaluator import Evaluator
    from ai_news.core.memory import Memory
    from ai_news.main import run_task
    from ai_news.report_generator import generate_report, update_archive_index

    result = run_task(query, memory=Memory(), evaluator=Evaluator())
    if result.get("status") != "ok":
        return {"ok": False, "error": str(result.get("error") or result.get("status"))}
    with open(result["out_path"], "r", encoding="utf-8") as f:
        task_output = json.load(f)
    html_path = generate_report(task_output, mode="full")
    update_archive_index(task_output, html_path)
    return {"ok": True, "out_path": result["out_path"], "html": html_path.name}


manager = TaskManager(_run_web_task)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "busy": manager.busy})


@app.get("/")
def index():
    return render_template(
        "index.html",
        has_key=bool(os.getenv("DEEPSEEK_API_KEY")),
        model=os.getenv("LLM_MODEL", "deepseek-v4-flash"),
    )


@app.get("/api/config")
def api_config():
    return jsonify(
        {"has_key": bool(os.getenv("DEEPSEEK_API_KEY")), "busy": manager.busy}
    )


@app.post("/api/task")
def api_submit():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify({"error": "请输入任务指令"}), 400
    if manager.busy:
        return jsonify({"error": "已有任务运行中，请稍后再试"}), 409
    task_id = manager.submit(query)
    if task_id is None:
        return jsonify({"error": "已有任务运行中，请稍后再试"}), 409
    return jsonify({"task_id": task_id}), 202


@app.get("/api/task/<task_id>")
def api_task(task_id: str):
    record = manager.get(task_id)
    if record is None:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(record)


@app.get("/reports/<path:filename>")
def reports(filename: str):
    """报告 / 归档页 / 索引等静态文件。"""
    return send_from_directory(REPORTS_DIR, filename)


@app.get("/archive")
def archive():
    """归档页入口（兼容旧地址，重定向到 reports 目录下的归档页）。"""
    return redirect(url_for("reports", filename="archive.html"))


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
