"""Web 层冒烟单测：路由可用 / 任务生命周期 / 单任务锁 / 鉴权。

运行方式：
    python tests/test_web.py   # 直接运行全部用例
    pytest tests/              # 或从项目根跑 pytest
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根入 path

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


# ── 权限验证（方案 A：单访问密码）──

def test_auth_disabled_by_default():
    """未配置 ACCESS_PASSWORD 时无需登录。"""
    old = app_module.ACCESS_PASSWORD
    app_module.ACCESS_PASSWORD = ""
    try:
        r = app.test_client().get("/")
        assert r.status_code == 200
    finally:
        app_module.ACCESS_PASSWORD = old


def test_auth_flow():
    """开启鉴权后：未登录拦截 / 错误密码拒绝 / 正确密码进入 / API 401 / healthz 放行。"""
    old = app_module.ACCESS_PASSWORD
    app_module.ACCESS_PASSWORD = "test123"
    try:
        c = app.test_client()
        # 未登录访问首页 → 302 跳登录页
        r = c.get("/")
        assert r.status_code == 302 and "/login" in r.headers["Location"]

        # 未登录访问 API → 401 JSON
        r = c.get("/api/config")
        assert r.status_code == 401
        assert r.get_json()["error"]

        # healthz 放行（容器健康检查不受影响）
        r = c.get("/healthz")
        assert r.status_code == 200

        # 错误密码 → 200 + 错误提示（页面内展示，不重定向）
        r = c.post("/login", data={"password": "wrong"})
        assert r.status_code == 200
        assert "访问密码错误" in r.get_data(as_text=True)

        # 正确密码 → 302 回首页
        r = c.post("/login", data={"password": "test123"})
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")

        # 登录后访问首页成功
        r = c.get("/")
        assert r.status_code == 200
        assert "AI 信息搜索助手" in r.get_data(as_text=True)

        # 登录后 API 可用
        r = c.get("/api/config")
        assert r.status_code == 200

        # 登出后再次被拦截
        c.get("/logout")
        r = c.get("/")
        assert r.status_code == 302
    finally:
        app_module.ACCESS_PASSWORD = old


def test_auth_unicode_password():
    """非 ASCII 密码（中文）也能正常登录（hmac.compare_digest 需 bytes 比较）。"""
    old = app_module.ACCESS_PASSWORD
    app_module.ACCESS_PASSWORD = "中文密码123"
    try:
        c = app.test_client()
        r = c.post("/login", data={"password": "中文密码123"})
        assert r.status_code == 302  # 正确中文密码 → 成功进入
        r = c.get("/")
        assert r.status_code == 200
    finally:
        app_module.ACCESS_PASSWORD = old


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
