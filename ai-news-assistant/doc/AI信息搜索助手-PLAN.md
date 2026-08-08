# AI 信息搜索助手 — PLAN（构建计划与任务拆分）

> 依据：[AI信息搜索助手-SPEC.md](./AI信息搜索助手-SPEC.md)
> 目标：按 M1→M5 五个里程碑推进，覆盖 **16 个核心知识点**，每个任务明确产出文件与验收标准。

---

## 0. 总览

```
M1 核心骨架 ──► M2 Scraper+数据管道 ──► M3 多智能体编排 ──► M4 记忆/RAG/评估 ──► M5 报告+联调
（可运行CLI）   （真实数据可抓取）      （端到端Agent流程）  （智能体完善）       （产品交付形态）
```

**依赖原则**：
- M1 是所有模块的地基（LLM、trace、工具注册），必须先完成
- M2 的 Scraper 独立于 Agent，可并行开发
- M3 依赖 M1+M2
- M4 依赖 M3（记忆在 Agent 流程中读写）
- M5 依赖 M3 的报告 JSON（可视化渲染）

**环境前置**：`requirements.txt` 已含 `openai`、`python-dotenv`；`.env` 已含 `DEEPSEEK_API_KEY`。

---

## 1. M1 — 核心骨架（知识点：#3 工具调用、#15 可观测性）

| 任务 | 产出文件 | 内容 | 验收标准 |
|---|---|---|---|
| T1.1 | `ai_news/__init__.py`、`ai_news/agents/__init__.py`、`ai_news/core/__init__.py`、`ai_news/scrapers/__init__.py`、`ai_news/skills/__init__.py`、`ai_news/tools/__init__.py`、`data/` 目录、更新 `requirements.txt` | 包骨架 + 依赖（加 `requests`、`beautifulsoup4`、`jinja2`、`numpy`） | `python -c "import ai_news"` 无报错 |
| T1.2 | `ai_news/core/llm.py` | LLM 封装（复用 `ops_agent/llm.py` 模式：model/api_key/base_url + `chat(messages, tools)` + 支持无 thinking） | 能发起对话并返回内容 |
| T1.3 | `ai_news/core/tracing.py` | 全链路 trace：span 上下文、`trace_step(agent, action, detail, cost)`、JSONL 落盘 `data/logs/trace_*.jsonl` | 调用后日志文件出现结构化 JSON 行 |
| T1.4 | `ai_news/tools/schemas.py`、`ai_news/core/tool_registry.py` | 工具 Schema 定义 + 注册表（`register`/`get_schema`/`execute`/`list`），内置 `get_cached_data` 占位 | 注册表可注册并执行函数 |
| T1.5 | `ai_news/agents/base_agent.py` | Agent 基类：消息管理、循环防护（最大轮数/总调用/单工具上限）、工具执行回灌 | 触发上限能强制收敛 |
| T1.6 | `ai_news/main.py` | CLI 对话循环骨架（`exit`/`reset`/`save`/`forget` 命令占位） | 能启动、能对话、能退出 |

**M1 验收**：`python -m ai_news.main` 启动 CLI，输入任意问题得到 LLM 回复；`data/logs/` 下生成 trace JSONL。

---

## 2. M2 — Scraper + 数据管道（知识点：#14 缓存去重、#16 数据管道）

| 任务 | 产出文件 | 内容 | 验收标准 |
|---|---|---|---|
| T2.1 | `ai_news/scrapers/base.py` | `BaseScraper`：UA 伪装、超时、重试、请求间隔 ≥1s、错误分类、`scrape() -> list[Item]` 契约 | 3 个假站点用例通过 |
| T2.2 | `ai_news/scrapers/hf_scraper.py` | HuggingFace 热门模型（官方 API，国内走 hf-mirror.com 镜像） | 返回 ≥5 条真实数据 |
| T2.3 | `ai_news/scrapers/github_trending_scraper.py` | GitHub Trending（github.com/trending，AI 相关） | 返回 ≥5 条真实数据 |
| T2.4 | `ai_news/scrapers/arxiv_scraper.py` | arXiv cs.AI/cs.LG 最新论文（官方 Atom API） | 返回 ≥5 条真实数据 |
| T2.5 | `ai_news/scrapers/qbitai_scraper.py` | 量子位（qbitai.com 首页资讯；替代 SPA 无法静态抓取的机器之心） | 返回 ≥5 条真实数据 |
| T2.6 | `ai_news/scrapers/wired_scraper.py` | WIRED AI（wired.com/tag/ai；替代被 Cloudflare 拦截的 TechCrunch） | 返回 ≥5 条真实数据 |
| T2.7 | `ai_news/pipeline.py` | 五阶段管道：`collect → clean → dedup → normalize → aggregate`；Item 结构 `{title,url,source,published_at,summary,tags}`；指纹去重（URL+标题哈希）、多源合并 | 管道单测通过，重复数据去重率>0 |
| T2.8 | `ai_news/core/cache.py` | TTL 缓存（JSON 落盘 `data/cache/`）+ 命中统计 | 二次抓取命中缓存、不发起网络请求 |

**M2 验收**：编写 `test_scrapers.py` 逐个运行 5 个 Scraper 输出真实条目；缓存命中后 trace 中可见 `cache_hit=true`。

---

## 3. M3 — 多智能体编排（知识点：#1 多智能体、#2 ReAct、#3 二阶段 Loop、#5 技能管理、#10 状态机、#13 安全防护、#11 结构化输出）

| 任务 | 产出文件 | 内容 | 验收标准 |
|---|---|---|---|
| T3.1 | `ai_news/skills/registry.py` | 技能注册表：元信息（名称/描述/场景/依赖工具）、发现（关键词检索）、路由、热插拔 | 技能可按描述检索命中 |
| T3.2 | `ai_news/skills/open_source.py`、`papers.py`、`labs_blog.py`、`cn_media.py`、`intl_media.py` | 5 个组合技能，编排对应 Scraper 集合 | 组合技能可复用执行 |
| T3.3 | `ai_news/agents/planner.py` | 主编 Agent：**二阶段循环**——阶段一不传 tools 纯推理产出行动计划 JSON（站点/关键词/优先级/时间范围），阶段二按计划调工具并验证 | trace 中可见两阶段分界，思考阶段零工具调用 |
| T3.4 | `ai_news/agents/fetcher.py` | 抓取 Agent：`concurrent.futures` 并行调度技能/Scraper，单站点失败隔离 | 并行抓取耗时 < 串行；单站点失败不影响整体 |
| T3.5 | `ai_news/agents/analyzer.py` | 分析 Agent：调用 LLM 做分类、摘要、趋势提取、热词统计 | 输出结构化分析结果 |
| T3.6 | `ai_news/core/state_machine.py` | 任务状态机：`排队→抓取→清洗→分析→生成→完成/失败`，失败自动重试（≤2 次） | 状态流转可观测、可注入失败验证重试 |
| T3.7 | `ai_news/core/security.py` | Prompt 注入检测（关键词/模式）、URL 白名单校验（仅 SPEC §2 域名）、日志脱敏（API Key） | 注入样例被拦截；白名单外 URL 被拒 |
| T3.8 | `ai_news/agents/reporter.py` | 报告 Agent：LLM 按 JSON Schema 产出报告大纲（摘要/分类条目/图表数据），schema 校验 | 非法 JSON 被检出并触发重试 |

**M3 验收**：一次完整任务端到端跑通——用户输入 → 主编二阶段规划 → 抓取 Agent 并行抓取 → 分析 → 报告 JSON；`main.py` 打印任务流程。

---

## 4. M4 — 记忆 / RAG / 评估 / 上下文压缩（知识点：#7 记忆、#8 RAG、#9 上下文压缩、#12 评估、#6 提示词工程）

| 任务 | 产出文件 | 内容 | 验收标准 |
|---|---|---|---|
| T4.1 | `ai_news/core/memory.py` | 三级记忆：工作（任务内）/ 会话（跨任务）/ 长期（用户偏好+历史要点）；`write/retrieve/update/forget`；JSON 落盘 `data/memory/` | `save` 后重启仍保留；`forget` 生效 |
| T4.2 | `ai_news/core/rag.py` | RAG：历史报告要点向量化（numpy TF-IDF/余弦），Top-K 检索注入上下文 | 能回答「上次报告结论」类问题 |
| T4.3 | `ai_news/core/context.py` | 上下文压缩：Token 估算（tiktoken）、分级压缩（截断→摘要→事实抽取→滚动窗口），压缩前后统计 | 长对话 Token 超阈值自动压缩且回答不失真 |
| T4.4 | `ai_news/core/evaluator.py` | 评估评测：工具调用正确率、报告质量评分（完整性/准确性/时效性）、任务指标汇总 | 每次任务产出 `evaluation.json` |
| T4.5 | 各 Agent system prompt 完善 | 分层角色提示词 + few-shot 示例 + 结构化输出约束 | 计划 JSON 与报告 JSON 格式稳定率 ≥90% |

**M4 验收**：同一会话连续两轮任务后，追问「上次抓到的模型叫什么」能通过 RAG 正确回答；单次任务产出评估报告。

---

## 5. M5 — 交互式报告 + 端到端联调（知识点：报告交付）

| 任务 | 产出文件 | 内容 | 验收标准 |
|---|---|---|---|
| T5.1 | `ai_news/templates/report.html` | Jinja2 模板：顶部摘要、卡片网格、Chart.js 图表（站点分布/时间趋势/类别占比/热词）、Tab 切换、搜索筛选、排序、亮/暗主题 | 浏览器打开各交互可用 |
| T5.2 | `ai_news/report_generator.py` | 渲染器：报告 JSON → HTML 单文件；快速模式（摘要+Top10）/完整模式 | 生成有效 HTML |
| T5.3 | `demo04.py` | 一键演示入口：对话循环 + 报告生成提示（输出路径） | `python demo04.py` 端到端运行 |
| T5.4 | 全量回归 | 16 项知识点对照 SPEC §9 矩阵逐项验收 + 边界用例（空结果站点、超时、注入、循环） | 矩阵 16 项全部通过 |

**M5 验收**：`python demo04.py` → 输入「抓取本周 AI 前沿动态」→ 生成 `data/reports/ai_news_YYYYMMDD_HHMMSS.html` → 浏览器验证可视化与交互。

---

## 6. 任务依赖关系图

```
M1: T1.1 → T1.2/T1.3 → T1.4 → T1.5 → T1.6
M2: T2.1 → T2.2~T2.6（可并行）→ T2.7/T2.8
M3: T3.1 → T3.2（依赖 M2）→ T3.3（依赖 M1+T3.2）
     T3.4（依赖 M2）→ T3.5 → T3.8 → 联调
     T3.6/T3.7（与 T3.3~T3.5 并行）
M4: T4.1 → T4.2/T4.3（依赖 T4.1）→ T4.4/T4.5
M5: T5.1 → T5.2（依赖 M3 报告 JSON）→ T5.3 → T5.4
```

## 7. 文件清单（最终交付）

```
ai-news-assistant/
├── ai_news/
│   ├── __init__.py
│   ├── main.py                     # M1 T1.6
│   ├── pipeline.py                 # M2 T2.7
│   ├── report_generator.py         # M5 T5.2
│   ├── agents/
│   │   ├── __init__.py             # M1 T1.1
│   │   ├── base_agent.py           # M1 T1.5
│   │   ├── planner.py              # M3 T3.3
│   │   ├── fetcher.py              # M3 T3.4
│   │   ├── analyzer.py             # M3 T3.5
│   │   └── reporter.py             # M3 T3.8
│   ├── core/
│   │   ├── __init__.py             # M1 T1.1
│   │   ├── llm.py                  # M1 T1.2
│   │   ├── tracing.py              # M1 T1.3
│   │   ├── tool_registry.py        # M1 T1.4
│   │   ├── cache.py                # M2 T2.8
│   │   ├── state_machine.py        # M3 T3.6
│   │   ├── security.py             # M3 T3.7
│   │   ├── memory.py               # M4 T4.1
│   │   ├── rag.py                  # M4 T4.2
│   │   ├── context.py              # M4 T4.3
│   │   └── evaluator.py            # M4 T4.4
│   ├── scrapers/
│   │   ├── __init__.py             # M1 T1.1
│   │   ├── base.py                 # M2 T2.1
│   │   ├── hf_scraper.py           # M2 T2.2
│   │   ├── github_trending_scraper.py  # M2 T2.3
│   │   ├── arxiv_scraper.py        # M2 T2.4
│   │   ├── qbitai_scraper.py       # M2 T2.5
│   │   └── wired_scraper.py        # M2 T2.6
│   ├── skills/
│   │   ├── __init__.py             # M1 T1.1
│   │   ├── registry.py             # M3 T3.1
│   │   ├── open_source.py          # M3 T3.2
│   │   ├── papers.py               # M3 T3.2
│   │   ├── labs_blog.py            # M3 T3.2
│   │   ├── cn_media.py             # M3 T3.2
│   │   └── intl_media.py           # M3 T3.2
│   ├── tools/
│   │   ├── __init__.py             # M1 T1.1
│   │   └── schemas.py              # M1 T1.4
│   └── templates/
│       └── report.html             # M5 T5.1
├── data/                           # 运行时：logs/cache/memory/reports
├── demo04.py                       # M5 T5.3
├── AI信息搜索助手-SPEC.md
├── AI信息搜索助手-PLAN.md
├── requirements.txt                # M1 T1.1
├── .env                            # API Key（已就绪）
└── .gitignore
```

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 部分站点反爬（403/验证码） | UA 伪装 + 请求间隔 + 失败降级（返回空列表并记录 trace，不阻塞流程） |
| 站点 HTML 结构变更 | BaseScraper 内集中 selector 配置，失败有明确错误分类 |
| LLM 输出非 JSON | JSON Schema 校验 + 自动重试（≤2 次） |
| 长对话上下文膨胀 | M4 上下文压缩兜底 + Token 预算监控 |
| 抓取数据量超 Token 预算 | 单站点 20 条上限 + 分析前摘要截断 |
