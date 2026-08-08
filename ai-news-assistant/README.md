# AI 信息搜索助手

多智能体驱动的 AI 前沿信息检索与可视化报告工具。输入一句指令，自动完成**规划 → 多源抓取 → 数据管道 → AI 分析 → 报告生成**，产出一份可交互、带置信度评估的单文件 HTML 报告。

支持 Docker 一键部署，只需配置 1 个 LLM API Key。

## 快速开始（Docker 推荐）

前置条件：已安装 Docker（含 compose 插件，`docker compose version` 可验证）。

```bash
# 1. 克隆项目并进入目录
cd ai-news-assistant

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxx

# 3. 构建并启动
docker compose up -d --build

# 4. 打开产品首页
open http://localhost:8080
```

在首页输入指令（如「抓取本周最新的 AI 前沿动态，重点关注模型发布与产业资讯」），点击「开始搜索」，约 1 分钟生成报告。

停止服务：`docker compose down`（数据保留）；卸载并清数据：`docker compose down -v`。

## 配置说明

| 环境变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | - | LLM API Key（DeepSeek 或任意 OpenAI 兼容服务） |
| `LLM_MODEL` | | `deepseek-v4-flash` | 模型名 |
| `LLM_BASE_URL` | | `https://api.deepseek.com` | API 端点，可换任意 OpenAI 兼容地址 |
| `LLM_TIMEOUT` | | `60` | LLM 请求超时（秒） |
| `PORT` | | `8080` | Web 端口（改端口后同时调整 compose 的 ports） |
| `ACCESS_PASSWORD` | | （关闭） | 访问密码：设置后所有页面/API 需先登录，30 天免登录；留空则完全开放 |
| `SECRET_KEY` | | 开发默认值 | session 签名密钥，生产环境务必设置为随机字符串 |

未配置 Key 时服务仍可启动，首页会显示配置引导，但无法运行任务。

公网部署时建议设置 `ACCESS_PASSWORD`（如 `ACCESS_PASSWORD=你的密码`），防止他人直接访问首页与报告；登录页会自动拦截未授权访问。

## 数据与备份

所有运行时数据存放在 `data/` 目录（compose 已挂载为卷，重启/重建容器不丢失）：

```
data/
├── reports/   报告 HTML、归档页 archive.html、任务 JSON、评估 JSON、归档索引 index.json
├── memory/    长期记忆（long_term.json，跨任务学习）
├── cache/     抓取缓存（避免重复请求）
└── logs/      trace 日志
```

- 备份：直接备份 `data/` 目录即可
- 迁移：把旧机器的 `data/` 复制到新机器对应目录后启动
- 归档浏览：首页「查看全部报告归档」或直接访问 `http://localhost:8080/archive`

## 本地开发（非 Docker）

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 Key
python -m web.app       # 启动 Web 服务（默认 8080）
# 或 CLI 方式：
python demo04.py --query "抓取本周 AI 动态" --quick
```

## 常见问题

**任务失败「Prompt 注入检测」**：输入指令包含安全规则关键词会被拦截，改用更自然的描述。

**抓取不到某来源**：外部站点偶发反爬/限流，已有缓存与超时兜底，重试一次即可；网络受限时可调小任务指令范围。

**国内访问 HuggingFace 慢**：HuggingFace 是默认信息源之一，网络受限时可改用偏中文来源的指令（如「关注国内大模型产业动态」），或按需调整站点技能。

**修改端口**：编辑 `.env` 的 `PORT`，同时把 `docker-compose.yml` 的 `ports` 改成 `"新端口:8080"`。

## 架构概览

```
Web 首页（Flask） ──提交指令──▶ 后台任务（单任务锁）
                                   ├─ 主编 Agent：规划站点 / 验证计划
                                   ├─ 抓取 Agent：并行抓取 5 类信息源
                                   ├─ 数据管道：清理 / 去重 / 多源统计
                                   ├─ 分析 Agent：摘要 / 分类 / 速览 / 置信度
                                   ├─ 报告 Agent：章节大纲（Schema 校验）
                                   └─ 生成 HTML 报告 + 更新归档
数据 ──▶ data/（报告 / 归档索引 / 长期记忆 / 缓存 / 日志）
```

技术栈：Python 3.13 · Flask · Jinja2 · Chart.js（报告内 CDN）· OpenAI 兼容 SDK · 轻量 RAG（TF-IDF）。
