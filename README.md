# LearnAgent

LLM 智能体学习与产品化实践仓库，包含 3 个递进式 Demo、一个多智能体 AI 信息检索产品和一个运维智能体框架。

所有脚本均基于 **OpenAI 兼容 API**（默认 DeepSeek），只需配置 1 个 API Key 即可运行。

## 目录结构

```
LearnAgent/
├── demo01.py            # Demo1：LLM 基础调用（单轮对话）
├── demo02.py            # Demo2：多轮对话（保留上下文）
├── demo03.py            # Demo3：Function Calling（JSON 数据库查询工具）
├── users.json           # Demo3 使用的演示用户数据库
├── requirements.txt     # 根目录依赖（openai / python-dotenv / pytest）
├── ai-news-assistant/   # 产品一：AI 信息搜索助手（Web + Docker，含 demo04 CLI）
└── ops_agent/           # 产品二：运维智能体框架（审批/审计/记忆）
```

## 快速开始

### 1. 配置 API Key

在项目根目录创建 `.env`（已加入 .gitignore，不会被提交）：

```ini
DEEPSEEK_API_KEY=sk-你的Key
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
```

### 2. 运行 Demo

```bash
pip install -r requirements.txt

python demo01.py        # 单轮对话：打招呼
python demo02.py        # 多轮对话：终端聊天
python demo03.py        # Function Calling：让 AI 查询 users.json
```

### 3. 运行测试

```bash
python -m pytest         # 根目录 Demo 无单测，测试在各子项目内
```

## 子项目一：AI 信息搜索助手（ai-news-assistant/）

多智能体驱动的 AI 前沿信息检索与可视化报告工具。输入一句指令，自动完成 **规划 → 多源抓取 → 数据管道 → AI 分析 → 报告生成**，产出一份可交互、带置信度评估的单文件 HTML 报告。支持 Docker 一键部署。

```bash
cd ai-news-assistant
cp .env.example .env    # 填入 DEEPSEEK_API_KEY
docker compose up -d --build
open http://localhost:8080
```

能力特性：

- **多智能体流水线**：主编 Agent（规划/验证）→ 抓取 Agent（5 类来源并行）→ 数据管道（清理/去重/多源统计）→ 分析 Agent（摘要/分类/速览/置信度）→ 报告 Agent（大纲生成）
- **信息源**：量子位、WIRED AI、HuggingFace、arXiv、GitHub Trending
- **报告体系**：三级置信度（报告级评估 / 总结级自评 / 条目级规则）、Chart.js 可视化、全文搜索、打印适配
- **数据管理**：原始抓取保留、报告归档索引（index.json + archive.html 浏览页）、长期/短期记忆（RAG 检索）
- **产品形态**：Flask Web 首页 + 后台单任务队列 + 前端轮询状态；Docker 单镜像 + 数据卷持久化

详细说明见 [ai-news-assistant/README.md](ai-news-assistant/README.md)。

## 子项目二：运维智能体框架（ops_agent/）

带 **审批、审计、幂等、记忆** 的企业级 LLM Agent 骨架，面向运维场景：

- **工具集**：日志查询、指标查询、发布查询、工单查询、重启服务、删库（危险工具）等，通过 ToolRegistry 注册
- **安全机制**：PolicyEvaluator 危险操作预判 → ApprovalManager 人工审批 → AuditRecorder 全量审计
- **运行时**：内存管理（MemoryManager）、会话持久化（SessionStore）、幂等保护（IdempotencyGuard）
- **运行模式**：交互式 Agent（`--role` / `--resume`）与审批入口（`--list-approvals` / `--approve` / `--reject`）

```bash
cd ops_agent
python3 main.py                      # 启动交互式 Agent
python3 main.py --list-approvals     # 查看待审批任务
python3 main.py --approve TASK_ID    # 批准并执行
```

> 说明：`ops_agent` 依赖的 LLM 与记忆数据位于其 `var/` 目录（已加入 .gitignore，不提交）。

## 环境变量总览

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | - | LLM API Key（DeepSeek 或任意 OpenAI 兼容服务） |
| `LLM_MODEL` | | `deepseek-v4-flash` | 模型名 |
| `LLM_BASE_URL` | | `https://api.deepseek.com` | API 端点，可换任意 OpenAI 兼容地址 |
| `LLM_TIMEOUT` | | `60` | LLM 请求超时（秒，ai-news-assistant 使用） |

## 安全提示

- `.env` 已加入 `.gitignore`，请勿提交或分享你的 API Key
- `ops_agent` 的删库工具为教学演示，生产使用前请自行评估风险
