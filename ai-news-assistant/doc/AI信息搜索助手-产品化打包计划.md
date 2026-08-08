# AI 信息搜索助手 — 产品化打包计划（Docker）

> 目标：把 ai-news-assistant 打包成一个 Docker 镜像，别人只需配置 1 个 API Key 即可在自己机器上启动使用。

## 一、现状与差距

| 能力 | 现状 | 产品化差距 |
|---|---|---|
| 任务执行 | CLI（demo04.py / ai_news.main） | 无 Web 界面，非技术用户无法使用 |
| 报告产出 | 单文件 HTML（已优化） | 已可直接阅读 ✅ |
| 数据保留 | task json / HTML / 归档索引 / 长期记忆 | 已完备 ✅ |
| 配置 | .env（DEEPSEEK_API_KEY 等） | 已支持环境变量 ✅ |
| 容器化 | 无 | **缺 Dockerfile / compose / 文档** |
| Web 服务 | 无 | **缺** |

有利条件：`DATA_DIR` 为项目根 `data/`，天然可挂载卷；LLM 配置全部读环境变量（`DEEPSEEK_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL`/`LLM_TIMEOUT`），零改造即可容器化。

## 二、产品形态

**单镜像 + Web UI（浏览器访问）**：

```
用户浏览器 ──> http://localhost:8080
                  │
            Flask Web 服务（容器内）
                  │
          ┌───────┴────────┐
          │ 任务执行（后台线程） │
          │ 报告/归档静态服务    │
          └───────┬────────┘
                  │ 持久化
             /app/data（挂载卷）
              ├── reports/  报告 + 归档 + task json
              ├── memory/   长期记忆
              ├── cache/    抓取缓存
              └── logs/     trace 日志
```

核心交互闭环：**首页输入指令 → 运行 → 进度展示 → 打开报告 → 浏览归档**。

保留 CLI（demo04.py）作为容器内调试入口，不影响镜像主体。

## 三、配置设计（用户只需配 1 个 Key）

| 环境变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | - | LLM 接入密钥 |
| `LLM_MODEL` | | `deepseek-v4-flash` | 模型名 |
| `LLM_BASE_URL` | | `https://api.deepseek.com` | 可换任意 OpenAI 兼容端点 |
| `LLM_TIMEOUT` | | `60` | 秒 |
| `PORT` | | `8080` | Web 端口 |

- 未配置 Key 时：首页显示配置引导，不阻塞启动，健康检查仍通过
- Key 只存在于容器环境变量，不落入代码/前端/日志（沿用现有 mask_secret）

## 四、交付物清单

1. `web/` — Flask Web 服务模块
   - `app.py`：路由（首页 / 任务 API / 报告与归档静态服务 / 健康检查 / 配置检测）
   - `templates/index.html`：产品首页（指令输入、运行按钮、进度轮询、最近任务列表、归档入口），视觉风格与报告一致
   - `tasks.py`：后台任务线程池（单任务锁 + 状态机：queued→running→done/failed）
2. `Dockerfile` — python:3.13-slim，非 root 用户，时区 Asia/Shanghai
3. `.dockerignore` — 排除 data/、.env、__pycache__、测试
4. `docker-compose.yml` — 一键启动（端口 + 数据卷 + 环境变量）
5. `.env.example` — 配置模板（用户复制改名为 .env）
6. `README.md` — 产品使用文档：快速开始 / 配置说明 / 数据备份 / 常见问题
7. `requirements.txt` — 追加 flask
8. `test_web.py` — Web 层冒烟单测（路由可用 / 无 Key 提示 / 任务接口）

## 五、实施里程碑

**M1 Web 服务层**（web/app.py + tasks.py）
- Flask 路由：`GET /`（首页）、`POST /api/task`（提交指令）、`GET /api/task/<id>`（查状态）、`GET /reports/<file>`（静态报告）、`GET /archive.html`、`GET /healthz`
- 任务线程：提交后立即返回 task_id；后台执行 run_task + 生成报告 + 更新归档索引；状态存内存 dict + 阶段文本（规划/抓取/分析/生成）
- 单任务锁：任务运行中重复提交返回 409
- 复用现有 `run_task`，**不改动核心链路**

**M2 前端首页**（web/templates/index.html）
- 输入区（默认指令）+ 运行按钮；运行时进度轮询（阶段文本 + 转圈）
- 最近任务列表（读归档 index.json 倒序展示 + 跳转报告）
- 归档入口链接；无 Key 时顶部黄色配置引导条
- 与报告同风格（同一配色/字体），移动端可用

**M3 容器化**
- Dockerfile：基础镜像 → 装依赖 → 复制源码与模板 → 创建非 root 用户 → 健康检查 → CMD 启动 Flask
- .dockerignore：data/、.env、__pycache__、test_*.py、*.md
- docker-compose.yml：端口映射 + 数据卷 + env 注入 + 重启策略
- 数据卷首次挂载自动创建目录结构（镜像内置空 data 骨架）

**M4 文档与工程**
- README（含 Docker 快速开始、env 模板、数据备份/迁移说明、常见问题）
- requirements 补 flask（+ 版本锁定）
- build.sh 构建脚本（tag 化）

**M5 验收**
- 单测回归（test_report/test_pipeline/test_web 全绿）
- 本地 `docker build` + `docker compose up` 冒烟
- 浏览器端到端：首页 → 输入指令 → 运行任务 → 进度 → 打开报告 → 归档页
- 验证持久化：重启容器后数据仍在；挂载卷为空时自动初始化

## 六、风险与对策

| 风险 | 对策 |
|---|---|
| 任务耗时 40s+，同步请求会超时 | 后台线程 + 状态轮询 |
| 部分站点抓取受限（GitHub/量子位） | 已有缓存与超时兜底；README 提示网络要求 |
| 国内访问 HuggingFace 慢 | 镜像不锁死站点，用户可换 `LLM_BASE_URL`/调整 planner；README 说明 |
| 多人/并发提交拖垮资源 | 单任务锁（409），明确为单用户产品 |
| API Key 泄露 | 只走环境变量，前端/日志不展示，.dockerignore 排除 .env |
| 容器内时区/中文乱码 | 镜像固定 Asia/Shanghai + UTF-8 |

## 七、明确不做（本期）

- 多用户/登录鉴权（单用户自托管产品）
- 爬虫代理/镜像站（外部网络直接访问）
- 定时任务/消息推送（保留手动触发）
- 独立 API 文档（Web UI 为唯一入口，CLI 保留调试）
