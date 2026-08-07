"""Web 层冒烟单测：路由可用 / 任务生命周期 / 单任务锁。

运行方式：
    python test_web.py        # 直接运行全部用例
    pytest test_web.py        # 也可被 pytest 收集
"""
import time

import web.app as app_module

app = app_module.app


def _reset_manager() -> None:
    app_module.manager._tasks = {}
    app_module.manager._current = None


def test_healthz():
    r = app.test_client().get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_index_page():
    r = app.test_client().get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "AI 信息搜索助手" in html
    assert "发起新任务" in html


def test_config_api():
    r = app.test_client().get("/api/config")
    assert r.status_code == 200
    assert "has_key" in r.get_json()


def test_submit_empty_query_rejected():
    r = app.test_client().post("/api/task", json={"query": "   "})
    assert r.status_code == 400


def test_task_lifecycle():
    _reset_manager()
    app_module.manager._run_fn = lambda q: {"ok": True, "html": "ai_news_test.html"}
    c = app.test_client()
    r = c.post("/api/task", json={"query": "测试任务"})
    assert r.status_code == 202
    task_id = r.get_json()["task_id"]

    rec = None
    for _ in range(50):
        rec = app_module.manager.get(task_id)
        if rec and rec["status"] != "running":
            break
        time.sleep(0.1)
    assert rec is not None and rec["status"] == "done"
    assert rec["result"]["html"] == "ai_news_test.html"

    r2 = c.get(f"/api/task/{task_id}")
    assert r2.status_code == 200
    assert r2.get_json()["status"] == "done"


def test_task_not_found():
    r = app.test_client().get("/api/task/notexist")
    assert r.status_code == 404


def test_single_task_lock():
    _reset_manager()

    def slow(q: str) -> dict:
        time.sleep(0.5)
        return {"ok": True, "html": "x.html"}

    app_module.manager._run_fn = slow
    c = app.test_client()
    r1 = c.post("/api/task", json={"query": "任务一"})
    assert r1.status_code == 202
    r2 = c.post("/api/task", json={"query": "任务二"})
    assert r2.status_code == 409  # 运行中拒绝并发

    for _ in range(30):
        if not app_module.manager.busy:
            break
        time.sleep(0.1)


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n共 {len(tests)} 个用例，通过 {len(tests) - failed}，失败 {failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
