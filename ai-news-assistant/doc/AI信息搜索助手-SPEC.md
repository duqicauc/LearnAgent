# AI 信息搜索助手 — SPEC

> 版本：v2.0（知识点全覆盖版）
> 定位：作为 **AI 智能体开发的综合实践项目**，将 Agent 开发核心知识点全部融入一个真实可运行的产品级 Demo。

---

## 1. 概述

构建一个 AI 智能体，自动访问指定的 AI 前沿站点（模型社区、论文、官方实验室、中文资讯、国际媒体），抓取最新信息，经多智能体协作分析与总结后，输出一份**交互式 HTML 可视化报告**。

本项目不仅是一个信息抓取工具，更是一套 **AI 智能体开发知识体系的教学型参考实现**，覆盖：多智能体协作、ReAct 循环、二阶段 Agent Loop、工具调用、技能管理、提示词工程、记忆管理、RAG、上下文压缩、工作流状态机、结构化输出、评估评测、安全防护、缓存去重、可观测性、数据管道共 **16 个核心知识点**。

## 2. 目标站点（5 大类 15+ 站点）

| 类别 | 站点 | 采集内容 |
|---|---|---|
| **模型与开源社区** | [Hugging Face](https://huggingface.co) · [魔塔 ModelScope](https://modelscope.cn) · [AtomGit](https://atomgit.com) · [GitHub Trending](https://github.com/trending) | 热门模型、数据集、开源项目 |
| **论文与学术前沿** | [arXiv](https://arxiv.org) (cs.AI/cs.LG/cs.CL) · [Papers With Code](https://paperswithcode.com) · [HF Daily Papers](https://huggingface.co/papers) | 最新论文、Benchmark、代码 |
| **官方实验室博客** | [OpenAI Blog](https://openai.com/blog) · [Google DeepMind](https://deepmind.google/blog) · [Meta AI](https://ai.meta.com/blog) · [Anthropic Research](https://anthropic.com/research) · [NVIDIA Blog](https://developer.nvidia.com/blog) | 模型发布、技术突破、安全研究 |
| **中文 AI 资讯** | [HyperAI](https://hyper.ai) · [AI Era](https://aiera.com.cn) · [机器之心](https://jiqizhixin.com) · [量子位](https://qbitai.com) | 中文 AI 新闻、产业动态 |
| **国际行业媒体** | [TechCrunch AI](https://techcrunch.com/category/artificial-intelligence) · [MIT Tech Review](https://technologyreview.com/topic/artificial-intelligence) · [The Verge AI](https://theverge.com/ai-artificial-intelligence) | 融资、产品、商业分析 |

## 3. 架构设计：多智能体协作

采用 **主编/执行/分析/报告 四角色多智能体架构**，通过共享黑板（Blackboard）协作：

```
                     ┌─────────────────────────┐
                     │  主编 Agent (Planner)    │
                     │ 二阶段循环：思考→行动     │
                     └───────────┬─────────────┘
                                 │ 规划（站点清单、关键词、优先级）
                 ┌───────────────┼───────────────┐
                 ▼               ▼               ▼
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │ 抓取 Agent A │ │ 抓取 Agent B │ │ 抓取 Agent C │  并行执行
        │ (HF/arXiv)   │ │ (开源社区)   │ │ (中文资讯)   │
        └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
               │                │                │
               └────────────┬───┴───────┬────────┘
                            ▼           ▼
                 ┌──────────────────────────────┐
                 │ 分析 Agent (Analyzer)         │
                 │ 去重、分类、摘要、趋势、热词    │
                 └──────────────┬───────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │ 报告 Agent (Reporter)         │
                 │ 结构化输出 JSON → 渲染 HTML    │
                 └──────────────────────────────┘
```

## 4. 核心能力（按知识点组织）

### 4.1 多智能体协作
- **主编 Agent**：ReAct 推理 → 决策抓哪些站点、关键词、优先级、是否需要补充抓取
- **抓取 Agent**：并行执行各站点 Scraper，隔离失败
- **分析 Agent**：综合多源数据，去重、分类、摘要、趋势、热词统计
- **报告 Agent**：按 JSON Schema 组织报告大纲，渲染 HTML
- 智能体间通过**共享数据对象**通信（Blackboard 模式），解耦职责

### 4.2 ReAct 循环与二阶段 Agent Loop
- **ReAct 模式**：主编 Agent 采用 Reasoning + Acting 循环：先推理当前信息是否充分，再决定调用抓取工具或直接收敛
- **二阶段设计（Plan-Then-Act）**：将循环拆分为两个明确的阶段：

```
┌─ 阶段一：思考循环（无工具）─────────────────────┐
│  强制纯推理，逐步细化行动方案（选哪些站点、      │
│  关键词、优先级、时间范围）→ 产出行动计划 JSON    │
│  收敛条件：推理已足够明确 或 达最大思考轮数       │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─ 阶段二：执行循环（有工具）─────────────────────┐
│  按计划调用工具 → 观察结果 → 补充推理 →          │
│  必要时调整计划再执行，直至收敛或达循环防护上限    │
└─────────────────────────────────────────────────┘
```

- **阶段衔接**：行动计划以结构化 JSON 在阶段间传递（站点清单、关键词、每站点抓取意图）
- **阶段一不消耗工具配额**，只消耗推理 Token；阶段二按计划精准调用工具
- 每轮循环记录推理过程与行动，供可观测性模块展示
- 学习点：**思考与行动分离**，减少无效工具调用，提升工具调用质量、降低 Token 成本

### 4.3 工具调用
- **系统工具（原子操作）**：所有 Scraper 以 JSON Schema 形式注册为工具（`fetch_ai_news`、`get_cached_data` 等）
- 统一的工具注册表 + 循环防护（最大轮数/最大调用次数/单工具上限）
- 工具与技能分层：工具是**原子能力**，技能是**工具的组合封装**（见 §4.14）

### 4.4 提示词工程
- **分层 System Prompt**：每个 Agent 独立角色提示词
- **few-shot 示例**：抓取计划决策、报告大纲生成各附示例
- **结构化输出约束**：JSON Schema 强制报告大纲格式稳定

### 4.5 记忆管理（长短期分层）
采用 **三级记忆架构**，对应认知科学中的工作记忆 / 情景记忆 / 语义记忆：

| 层级 | 作用域 | 内容 | 持久化 |
|---|---|---|---|
| **工作记忆**（短期） | 当前任务 | 任务上下文（messages）、进行中的抓取状态 | 任务结束即清理 |
| **会话记忆**（中期） | 多轮对话 | 本次会话跨任务的历史要点 | 会话文件，过期清理 |
| **长期记忆**（长期） | 跨会话 | 用户偏好（默认站点/关键词）+ 历史报告要点 | JSON + 向量库 |

- 记忆操作原语：`write`（写入）、`retrieve`（检索）、`update`（更新）、`forget`（遗忘/过期清理）
- 记忆与 RAG 协同：长期记忆中的历史报告要点经向量化后成为 RAG 检索源
- CLI 命令：`reset` 清空短期记忆、`save` 固化长期记忆、`forget <key>` 删除指定记忆

### 4.6 RAG 检索增强
- 历史报告生成**向量索引**（本地轻量向量库或 TF-IDF 关键词索引）
- 回答「上次关于多模态的报告结论」「上周出现过的模型」等追溯性追问
- 检索 Top-K 片段注入上下文，增强回答准确性

### 4.7 工作流状态机
- 任务全生命周期状态机：`排队 → 抓取 → 清洗 → 分析 → 生成 → 完成/失败`
- 失败自动重试（最多 N 次）、单站点失败不影响整体

### 4.8 结构化输出
- 抓取数据统一 `Item` 结构：`{title, url, source, published_at, summary, tags, metadata}`
- 报告大纲由 AI 以 JSON 输出，后端 schema 校验后再渲染

### 4.9 评估评测
- **工具调用正确率**：AI 选择的站点/参数是否合理
- **报告质量评分**：完整性、准确性、时效性（AI 自评 + 规则打分）
- **信息时效性**：抓取条目发布时间距现在时长分布
- 每次任务产出评估报告，追加到日志

### 4.10 安全防护
- **Prompt 注入防护**：对用户输入做关键词/模式检测，限制系统提示词被覆盖
- **URL 校验**：仅允许白名单域名，防 SSRF
- **循环防护**：Agent 无限循环检测与强制收敛
- **脱敏**：日志中隐藏 API Key、用户敏感信息

### 4.11 缓存与去重
- 抓取结果**指纹去重**（URL + 标题哈希），多源相同信息自动合并
- 站点数据 TTL 缓存，重复查询不重复抓取

### 4.12 可观测性
- 全链路 **trace 日志**：每个 Agent 的决策、工具调用、耗时、Token 消耗
- 任务级汇总指标：抓取条目数、去重率、失败站点、分析耗时
- 结构化 JSONL 日志输出，便于后续接入监控系统

### 4.13 数据管道
- 标准五阶段管道：`采集 → 清洗 → 去重 → 标准化 → 分析`
- 每阶段可独立测试、替换、插桩

### 4.14 技能管理（Skill Management）
将 Agent 的抓取/分析能力封装为可管理的**技能（Skill）**，与原子工具（§4.3）区分：

| 概念 | 说明 |
|---|---|
| **技能定义** | 元信息（名称、描述、适用场景、依赖工具）+ 实现（工具链编排） |
| **技能注册表** | 统一加载、发现（按关键词检索技能）、热插拔（运行时增减） |
| **技能路由** | Agent 根据任务意图选择合适技能，而非直接选工具 |
| **技能组合** | 组合技能 = 多基础技能编排，如「开源情报技能」= HF + GitHub + arXiv |

- 内置技能示例：`开源模型动态`、`论文前沿追踪`、`官方博客快讯`、`中文产业资讯`、`国际行业动态`
- 技能可复用、可评估（技能级调用成功率统计）、可持久化
- 学习点：从「工具调用」到「技能管理」的能力抽象演进

### 4.15 上下文压缩（Context Compression）
治理多轮对话后上下文无限膨胀的问题，降低 Token 成本、避免超过窗口限制：

| 策略 | 机制 | 触发条件 |
|---|---|---|
| **摘要压缩** | 旧对话由 LLM 生成摘要，替换原文 | 历史消息数 > 阈值 |
| **滚动窗口** | 保留最近 N 条完整消息 + 之前全部摘要 | Token 预算接近上限 |
| **关键事实抽取** | 从冗余对话中抽取事实写入记忆（§4.5），删除原文 | 会话轮次 > 阈值 |
| **冗余丢弃** | 工具结果截断/折叠，仅保留要点 | 单条消息超长 |

- Token 预算监控：每次 LLM 调用前估算，触发分级压缩（轻量截断 → 摘要 → 事实抽取）
- 压缩过程可观测：记录压缩前后 Token 数、被压缩消息量
- 学习点：上下文是 Agent 的核心资源，压缩是长对话稳定的关键保障

## 5. 技术栈

| 组件 | 技术选型 | 对应知识点 |
|---|---|---|
| 编程语言 | Python 3.10+ | — |
| LLM API | DeepSeek (OpenAI 兼容) | LLM 接入 |
| Function Calling | `openai` tools 接口 | 工具调用 |
| 网页抓取 | `requests` + `BeautifulSoup4` | 数据采集 |
| 并发 | `concurrent.futures` / asyncio | 并行抓取 |
| HTML 模板 | `jinja2` | 报告渲染 |
| 前端可视化 | Chart.js (CDN) | 交互式报告 |
| 向量检索 | `numpy`/`scikit-learn` 轻量实现 | RAG |
| 记忆存储 | JSON + 向量索引 | 记忆管理 |
| Token 预算 | `tiktoken` 估算 | 上下文压缩 |
| 日志 | `logging` + JSONL | 可观测性 |
| 配置 | `python-dotenv` | 环境管理 |

## 6. 交互式 HTML 报告规格

| 特性 | 说明 |
|---|---|
| 格式 | 单文件 HTML（CSS/JS 经 CDN 引入） |
| 可视化 | Chart.js 柱状图（站点分布）、折线图（时间趋势）、饼图（类别占比）、热词频次 |
| 交互 | Tab 切换（按类别）、搜索筛选、表格排序、卡片折叠/展开、亮/暗主题 |
| 布局 | 顶部摘要 → 信息卡片网格 → 图表区域 → 来源链接表 |
| 模式 | 快速模式（仅摘要+Top 条目）/ 完整模式（含所有可视化） |

## 7. 数据流

```
用户指令
  │
  ▼
[主编 Agent] ReAct 决策抓取计划（站点/关键词/优先级）
  │
  ▼
[抓取 Agent × N] 并行执行 Scraper ──► 指纹去重 + TTL 缓存
  │
  ▼
[数据管道] 清洗 → 标准化 → Item 结构
  │
  ▼
[分析 Agent] 分类、摘要、趋势提取、热词统计
  │
  ▼
[报告 Agent] JSON 大纲（schema 校验）→ 渲染 HTML
  │
  ▼
交互式 HTML 报告 + 评估报告 + trace 日志
  │
  ▼
（历史报告入 RAG 向量库，供追溯问答）
```

## 8. 项目结构

```
ai-news-assistant/
├── ai_news/
│   ├── __init__.py
│   ├── main.py                # CLI 入口（对话循环）
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py      # Agent 基类（LLM + 工具循环 + 防护）
│   │   ├── planner.py         # 主编 Agent（ReAct 决策）
│   │   ├── fetcher.py         # 抓取 Agent（并行调度）
│   │   ├── analyzer.py        # 分析 Agent（去重/摘要/趋势）
│   │   └── reporter.py        # 报告 Agent（JSON 大纲 → HTML）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── llm.py             # LLM 封装（复用 ops_agent/llm.py 模式）
│   │   ├── memory.py          # 三级记忆管理（工作/会话/长期）
│   │   ├── context.py         # 上下文压缩（摘要/滚动窗口/事实抽取）
│   │   ├── rag.py             # RAG 检索（向量索引 + Top-K）
│   │   ├── state_machine.py   # 任务状态机
│   │   ├── evaluator.py       # 评估评测
│   │   ├── security.py        # Prompt 注入防护 / URL 白名单 / 脱敏
│   │   ├── cache.py           # TTL 缓存 + 指纹去重
│   │   └── tracing.py         # 全链路 trace 日志
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── registry.py        # 技能注册表（发现/路由/热插拔）
│   │   ├── open_source.py     # 技能：开源模型动态（HF+GitHub+arXiv）
│   │   ├── papers.py          # 技能：论文前沿追踪
│   │   ├── labs_blog.py       # 技能：官方博客快讯
│   │   ├── cn_media.py        # 技能：中文产业资讯
│   │   └── intl_media.py      # 技能：国际行业动态
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py            # BaseScraper 基类 + 注册表
│   │   ├── hf_scraper.py      # HuggingFace
│   │   ├── modelscope_scraper.py
│   │   ├── github_trending_scraper.py
│   │   ├── arxiv_scraper.py
│   │   ├── paperswithcode_scraper.py
│   │   ├── openai_scraper.py
│   │   ├── deepmind_scraper.py
│   │   ├── meta_ai_scraper.py
│   │   ├── anthropic_scraper.py
│   │   ├── nvidia_scraper.py
│   │   ├── hyperai_scraper.py
│   │   ├── aiera_scraper.py
│   │   ├── qbitai_scraper.py
│   │   ├── wired_scraper.py
│   │   └── mit_tech_review_scraper.py
│   ├── pipeline.py            # 数据管道编排（采集→清洗→去重→标准化）
│   ├── report_generator.py    # HTML 渲染（jinja2）
│   ├── tools/
│   │   └── schemas.py         # 工具 JSON Schema 定义
│   └── templates/
│       └── report.html        # Jinja2 交互式模板
├── data/                      # 运行时数据（记忆、缓存、历史报告、日志）
├── ai_news/cli.py                 # 一键演示入口
├── AI信息搜索助手-SPEC.md     # 本文件
├── AI信息搜索助手-PLAN.md     # 实施计划
├── requirements.txt
└── .env
```

## 9. 知识点覆盖矩阵（验收清单）

| # | 知识点 | 落地位置 | 验收标准 |
|---|---|---|---|
| 1 | 多智能体协作 | `agents/` 四角色 | 各角色职责独立，可单独运行 |
| 2 | ReAct 循环 | `planner.py` | 日志中可见「推理→行动→观察」轨迹 |
| 3 | 二阶段 Agent Loop | `planner.py`（plan/act 两阶段） | 思考阶段零工具调用，行动阶段按计划执行 |
| 4 | 工具调用 | `core/llm.py` + `tools/schemas.py` | AI 能自主调用抓取/缓存工具 |
| 5 | 技能管理 | `skills/registry.py` + 各技能 | 技能可注册/发现/路由，组合技能可复用 |
| 6 | 提示词工程 | 各 Agent system prompt | 分层角色 + few-shot + 结构化约束 |
| 7 | 记忆管理 | `core/memory.py` | 三级记忆可用，reset/save/forget 生效 |
| 8 | RAG | `core/rag.py` | 能回答历史报告追溯问题 |
| 9 | 上下文压缩 | `core/context.py` | 长对话 Token 超阈值自动压缩且不失真 |
| 10 | 工作流状态机 | `core/state_machine.py` | 任务状态流转可观测、失败重试 |
| 11 | 结构化输出 | 报告 JSON schema | schema 校验失败可检出 |
| 12 | 评估评测 | `core/evaluator.py` | 每次任务产出评分报告 |
| 13 | 安全防护 | `core/security.py` | 注入尝试被拦截、仅白名单 URL |
| 14 | 缓存去重 | `core/cache.py` | 重复查询命中缓存，多源去重率>0 |
| 15 | 可观测性 | `core/tracing.py` | 全链路 trace 输出 JSONL |
| 16 | 数据管道 | `pipeline.py` | 五阶段可独立测试 |

## 10. 约束与限制

- **抓取频率**：每站点请求间隔 ≥ 1s，遵循 robots.txt 基本礼仪
- **内容规模**：单次任务每站点最多 20 条，总条目上限 100 条（控制 Token）
- **LLM 成本**：单次任务 LLM 调用控制在 8 次以内（含重试）
- **静态抓取**：仅服务端渲染页面，不处理 SPA/JS 渲染
- **环境**：DeepSeek API Key 从 `.env` 读取，不入 Git
- **Python 版本**：3.10+（项目自带虚拟环境）

## 11. 里程碑

| 里程碑 | 内容 |
|---|---|
| M1 | 核心骨架：LLM 封装、Agent 基类、工具注册、trace 日志 |
| M2 | 5 个代表站点 Scraper（HF/GitHub/arXiv/量子位/WIRED）+ 数据管道 |
| M3 | 多智能体编排 + 二阶段循环（思考/行动）+ 状态机 + 安全防护 |
| M4 | 记忆 + RAG + 评估评测 |
| M5 | 交互式 HTML 报告 + 端到端联调 + 知识点验收 |

> 实现注记：实际落地站点经实测确定——HF 走 hf-mirror.com 镜像；中文资讯用量子位（机器之心为 SPA 无法静态抓取）；国际媒体用 WIRED（TechCrunch 被 Cloudflare 拦截、The Verge/MIT TR 为懒加载 SPA）。其余站点按需增量接入。
