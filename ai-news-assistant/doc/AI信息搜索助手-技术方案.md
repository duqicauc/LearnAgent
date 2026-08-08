# AI 信息搜索助手 — 技术实现方案说明

> 撰写对照《技术实现方案说明对照清单》，分**基础 / 治理 / 收尾**三模块，逐项落到实际代码与实测数据；未实现的能力如实标注边界，不堆砌空泛内容。

---

## 一、基础模块

### 1. 系统提示词

本项目无统一 System Prompt，而是**每个 Agent 独立定义**（`agents/*.py` 的 `SYSTEM_PROMPT`）。归纳其共同结构为四部分，并标注每条约束规避的失败场景：

| 部分 | 内容 | 约束实例 | 规避的失败场景 |
|---|---|---|---|
| ① 角色定义 | 明确身份与职责边界 | Planner：「你是 AI 信息搜索任务的主编，负责先规划、后执行」；Analyzer：「你是 AI 前沿信息分析专家」 | 模型漂移进无关话题，输出与任务无关内容 |
| ② 可用资源清单 | 明确可用站点/输入格式 | Planner 列出 5 个可用站点及各自定位 | 编造不存在的站点，计划无法执行 |
| ③ 行为与输出约束 | 流程约束 + 输出 JSON Schema + 数量约束 | Planner：「第一阶段不调用任何工具…输出 JSON 计划，第二阶段严格按计划调用工具」；Analyzer：「tldr 5 条且每条务必给 why、categories 2-4 个」；Reporter：「sections 2-4 个、每个 3-8 条、url 必须来自真实链接、impact 不要复述 note」 | 过早消耗工具配额、输出非结构化文本无法解析、报告过长/过短、编造链接、条目重复 |
| ④ 语言与质量要求 | 语言一致性、质量兜底 | 统一「请始终用中文回复」 | 中英混杂，报告不可读 |

**实际约束兜底**（提示词之外）：Analyzer/Reporter 对 LLM 回复做 JSON 正则提取，失败自动降级（统计摘要）或重试（Reporter ≤3 次），不因模型不听话而中断任务。

### 2. 四类测试

对应 `test_pipeline.py`（8）、`test_report.py`（7）、`test_web.py`（10），本机实测**全部通过**；`test_scrapers.py` 为网络验收脚本（依赖外网，非单测）。

| 情形 | 用例 | 输入样例 | 预期行为 | 实测结果 |
|---|---|---|---|---|
| **命中**（正常路径） | test_task_lifecycle | 提交正常任务 `{"query":"测试任务"}` | 202 返回 task_id → 后台完成 → 轮询返回 `status=done` | ✅ 通过 |
| **命中** | test_chart_data | 8 条样例任务输出 | 来源/类别/标签/趋势四图数据正确，含叙事标题与结论 | ✅ 通过 |
| **未命中**（空/不存在） | test_task_not_found | GET `/api/task/notexist` | 404 + `{"error":"任务不存在"}` | ✅ 通过 |
| **未命中** | test_submit_empty_query_rejected | POST `/api/task` body `{"query":"   "}` | 400 + 提示「请输入任务指令」 | ✅ 通过 |
| **未命中** | test_generate_report_minimal_tolerant | 无 tldr/sections/items 的最小输出 | 正常渲染，页面显示「暂无条目数据」 | ✅ 通过 |
| **边界** | test_single_task_lock | 任务 A 运行中再提交任务 B | 第二个请求 409「已有任务运行中」 | ✅ 通过 |
| **边界** | test_auth_unicode_password | 密码为「中文密码123」 | 正确中文密码 302 进入系统（bytes 比较） | ✅ 通过 |
| **边界** | test_keep_tag | 标签 `"a"`（长度 1）/ `"123"`（纯数字） | 均被过滤（<2 字符、纯数字符号剔除） | ✅ 通过 |
| **越界**（安全/未授权） | test_auth_flow | 未登录 GET `/api/config`；错误密码 POST `/login` | API 401 JSON；错误密码 200 + 「访问密码错误」 | ✅ 通过 |
| **越界** | test_clean_filters_stopword_tags | 标签含停用词 `ai`/`github`/`trending` | 全部剔除，热词提取不受污染 | ✅ 通过 |

> 端到端实测（容器内真实任务）：抓取 33 条 / 4 来源 / 综合评分 0.964 / 耗时 42.6s，报告与归档同步生成。

### 3. 工具清单

共 **6 个工具**（`tools/schemas.py` 定义，`tools/fetchers.py` 实现）。

| 工具 | 用途 | 参数 Schema | 返回值设计逻辑 |
|---|---|---|---|
| `get_cached_data` | 查询站点/关键词抓取缓存（M1 占位，缓存逻辑已被 TTLCache 落地） | `site: str`、`keyword: str`，`additionalProperties: False` | `{cache, hit, note}` 明确告知命中状态，避免 LLM 误解 |
| `fetch_huggingface` | 抓取 HuggingFace 热门模型 | 统一 `keyword: str`（可空）+ `limit: int`（默认 10） | `{site, count, items}`——count 便于模型判断量级 |
| `fetch_github_trending` | 抓取 GitHub Trending 开源项目 | 同上 | 同上 |
| `fetch_arxiv` | 抓取 arXiv cs.AI 最新论文 | 同上 | 同上 |
| `fetch_qbitai` | 抓取量子位中文 AI 产业资讯 | 同上 | 同上 |
| `fetch_wired` | 抓取 WIRED AI 频道国际资讯 | 同上 | 同上 |

**Schema 设计逻辑**：
- 5 个抓取工具**统一参数模式**（`keyword` + `limit`），降低 LLM 选参成本、便于注册表批量注册
- `additionalProperties: False` 严格化：拒绝模型塞入未知参数
- `description` 带站点定位语义（如「中文 AI 产业资讯」），引导模型在规划阶段做语义匹配

**返回值设计逻辑**：
- 统一 **JSON 字符串回灌**给 LLM（`registry.execute` 保证类型一致），观察→再推理循环稳定
- 异常**不抛断**循环：`ToolRegistry.execute` 捕获异常转 `{"error": "工具执行失败: ..."}` 回灌，模型可自行调整后重试
- 抓取失败返回 `{"site": x, "count": 0}` 而非抛错，配合失败隔离

### 4. Agent 循环三道刹车

`agents/base_agent.py` 的 `BaseAgent.chat` 维护 tool-calling 循环，三道防护上限：

| 刹车 | 阈值 | 设定原因 |
|---|---|---|
| `MAX_ROUNDS` 最大推理轮数 | **6** | 实际任务（验证 3-5 站点）正常 3-4 轮即收敛；6 轮留足余量，避免偶发多轮徘徊 |
| `MAX_TOTAL_TOOL_CALLS` 工具调用总上限 | **12** | 成本红线：LLM 按 token 计费，5 站点 × 每站 1-2 次验证 + 意外重试，12 次封顶防费用失控 |
| `MAX_PER_TOOL_CALLS` 单工具调用上限 | **3** | 防某个工具死循环重试（如站点持续 403），触发即强制收敛 |

**触发行为**：不硬失败——注入系统提醒（说明触发原因），要求模型「基于已获取信息直接给出最终结论」，保证任务始终有产出。

**其他成本控制**：Planner 阶段二指令强制 `limit=3` 小批量验证（避免验证阶段就全量抓取）；工具结果回灌上下文时打印截断 200 字符。

### 5. 工具注册表：新增一个工具需修改的位置

以新增第 6 个站点抓取工具 `fetch_xxx` 为例：

| # | 位置 | 改动 |
|---|---|---|
| 1 | `ai_news/tools/fetchers.py` | 实现 `fetch_xxx()`（复用 `fetch_site_items` 模式，返回 JSON 字符串） |
| 2 | `ai_news/tools/schemas.py` | 定义 Schema（用 `_fetch_schema` 工厂），加入 `FETCH_TOOLS` 列表 |
| 3 | `ai_news/main.py` | **无需改**：`build_registry()` 自动遍历 `BUILTIN_TOOLS + FETCH_TOOLS` |
| 4 | `ai_news/scrapers/base.py` | `ALLOWED_SITE_DOMAINS` 增加域名（安全白名单，否则 `validate_url` 拒绝） |
| 5 | `ai_news/scrapers/xxx_scraper.py` | 新建 `BaseScraper` 子类，实现 `scrape()` |
| 6 | `ai_news/agents/planner.py` | `ALL_SITES` 列表增加站点标识（否则计划阶段被白名单过滤） |
| 7 | `ai_news/skills/` | 建议注册对应技能（关键词路由），供计划兜底发现 |
| 8 | `ai_news/report_generator.py` | `SOURCE_RELIABILITY`（置信度因子）与 `SOURCE_LINKS`（来源表链接）补充条目 |
| 9 | `test_scrapers.py` | `SCRAPERS` 列表加入新抓取器 |

---

## 二、治理模块

### 6. 权限规则：permission / approval / forbidden

**如实说明**：本项目**未实现分级权限体系**（无 permission/approval 状态机），采用「**架构级白名单 + 事前拦截**」替代，等效语义如下：

| 级别 | 本项目对应机制 | 判定标准 |
|---|---|---|
| **permission（许可）** | 工具循环内所有已注册工具默认放行 | 工具已注册于 `ToolRegistry`（`build_registry` 固定注册集，Agent 无动态注册能力） |
| **approval（审批）** | **无人工审批环节** | 单用户工具，不引入审批流程；代价是灵活性低 |
| **forbidden（禁止）** | 三重事前拦截 | ① 计划站点白名单：`planner.plan` 只保留 `ALL_SITES` 内站点（过滤幻觉站点）② 域名白名单：`security.validate_url` + `ALLOWED_SITE_DOMAINS`，抓取器只能访问声明域名 ③ Prompt 注入检测：命中 `INJECTION_PATTERNS` 直接拦截任务 |

> 边界：这种设计「禁止面大、无审批面」，适合只读信息获取场景；若未来开放写操作工具（删数据/发请求），必须先引入审批机制。

### 7. 高危动作界定

Agent 的**能力面是只读抓取**，天然不触碰下列高危动作（在架构层面就不存在执行入口）：

| 高危动作 | 本项目状态 |
|---|---|
| 写/删/改文件系统 | **禁止**：落盘仅由 `main.py` 代码执行（Agent 无文件工具）；容器内以非 root（appuser uid 1000）运行 |
| 执行任意 shell 命令 | **禁止**：无命令执行工具 |
| 访问白名单外域名 | **禁止**：`validate_url` 校验，抓取器域名硬编码在 `ALLOWED_SITE_DOMAINS` |
| 调用未注册工具 | **禁止**：`registry.execute` 返回 `{"error":"未知工具"}` |
| 并发提交任务 | **禁止**：Web 层单任务锁，运行中提交返回 409 |
| 泄露 API Key | **防护**：Key 仅环境变量注入，`mask_secret` 对日志/输出脱敏（`sk-*` → `sk-***`） |

### 8. 状态管理：State 维护的字段

**任务状态机**（`core/state_machine.py`，`TaskStateMachine`）：

| 字段 | 说明 |
|---|---|
| `task_id` | 任务唯一标识（uuid 前 8 位） |
| `state` | 生命周期：`queued → fetching → cleaning → analyzing → generating → completed/failed` |
| `max_retries` | 每阶段失败自动重试上限（**2**） |
| `_retry_counts` | 各阶段已重试次数（`{阶段: 次数}`） |
| `error` | 最近一次失败原因 |
| `tracer` | 全链路 trace（每次迁移/重试/失败均记录） |

**Web 任务记录**（`web/tasks.py`，`TaskManager`）：`task_id / query / status(running|done|failed) / created_at / log(列表) / result / error`，外加 `_current` 单任务指针（锁）。`get()` 返回快照时 `log` 截断为尾部 2000 字符。

### 9. 上下文策略

| 类别 | 内容 | 实现位置 |
|---|---|---|
| **固定携带** | System Prompt（角色 + 约束）；工具 JSON Schema（仅 `use_tools=True` 时） | `BaseAgent.reset/chat` |
| **每轮附带** | 用户指令 + assistant 消息（含 tool_calls）+ tool 执行结果，逐轮追加 | `BaseAgent.chat` 消息循环 |
| **裁剪过滤** | ① Token 预算压缩：`compress_context(budget=8000)`，滚动窗口从最新向前保留、system 保留、丢弃条数写入提示 ② 工具结果打印截断 200 字符 ③ Planner 验证阶段 `limit=3` 小批量 ④ 输出上限 `max_tokens=4096`（Analyzer/Reporter） | `core/context.py`、`base_agent.py`、`planner.py` |

Token 估算不引入 tiktoken：中文按 1.5 字符/token、英文按 4 字符/token（`estimate_tokens`），足够支撑压缩决策。

### 10. 审批与故障恢复

**审批暂停**：本项目**无人工审批暂停机制**（单用户只读场景），如实说明未实现。

**故障恢复矩阵**：

| 层 | 恢复策略 | 阈值 |
|---|---|---|
| 任务状态机 | 每阶段 `fail()` 自动重试同阶段 | ≤ 2 次，超限整体 `failed` |
| 报告结构化输出 | JSON 校验失败自动重试并反馈错误 | ≤ 3 次（`MAX_ATTEMPTS`），超限抛异常 → 任务 failed |
| 站点抓取 | HTTP/网络异常重试（退避 1s/2s） | ≤ 2 次，403 视为反爬立即失败 |
| Web 任务 | 异常兜底置 `failed`，前端展示错误 | 1 次 |

**状态存储位置**：任务状态存**内存**（`TaskManager` 字典 + `working` 记忆），**无跨进程持久化**——进程/容器重启后进行中任务丢失（已计入已知限制）。

**幂等键**：**无独立幂等机制**，由「单任务锁（串行）+ 同 `task_id` 归档覆盖」天然规避并发重复写；报告文件按时间戳命名避免覆盖，归档索引按 task_id 覆盖。

### 11. 记忆机制

| 维度 | 设计 |
|---|---|
| **隔离维度** | 三级隔离：`working`（单任务内，任务开始清空→写 plan/stats）/ `session`（进程内跨任务摘要）/ `long_term`（跨会话持久化，`data/memory/long_term.json`） |
| **冲突处理** | working/session 按 key **覆盖写**；long_term 的 history **追加 + 截断**（≤ 50 条），`latest` 记录最近一次任务；RAG 索引在任务完成后重建 |
| **信息准入标准** | `remember_task` 只写**要点摘要**：task_id / 时间 / 标题 / 分析摘要 / 热词 Top8；**原始抓取全文不入长期记忆**（存于 `data/reports/task_*.json` 的 `items` + `raw` 字段，按需读取） |

**RAG**：`SimpleRAG`（numpy 手写 TF-IDF + 余弦相似度），索引 `history_documents()`（标题+摘要+热词拼接），`/recall` 检索 Top-3 注入 LLM 回答跨任务问题——规模小（≤50 条）时不引入向量库，零部署成本。

---

## 三、收尾模块

### 12. 已知限制

| 限制 | 说明 |
|---|---|
| 注入检测是**关键词正则** | `INJECTION_PATTERNS` 覆盖常见句式，新型注入/编码变体可绕过；外部抓取内容同样不保证免疫 |
| 任务状态仅存内存 | 重启丢失进行中任务；无跨进程队列（无 Celery/RQ） |
| 信息源固定 5 站点 | 扩展需改代码（见 §5），不是全网搜索 |
| 抓取受外部环境制约 | 反爬 403 / 网络受限 / 站点改版 → 该站点降级为空列表，报告覆盖度下降 |
| 域名白名单用子串匹配 | `validate_url` 用 `domain in url`，存在前缀误判风险（如 `qbitai.com` 命中 `xqbitai.com`） |
| 无审批、无多用户、无审计日志 | 单密码登录仅为防滥用，不面向多租户 |
| LLM 结构化输出依赖模型稳定性 | 偶发 JSON 解析失败触发重试/降级，任务耗时波动 |
| huggingface 域名配置为 `hf-mirror.com` | 国内可达性优先的取舍，抓取的是镜像站 |

### 13. 迭代规划（按优先级）

1. **抓取治理**：来源健康度统计、失败站点自动剔除与重试队列、域名匹配改为规范化域名校验（修复子串误判）
2. **调度能力**：定时任务（cron 表达式）+ Webhook/邮件结果推送
3. **审批机制**：为未来写操作工具引入 permission/approval 状态机（对应治理清单 §6/§10）
4. **多用户与审计**：账号体系、操作审计日志、会话管理
5. **任务持久化**：任务状态落盘 + 崩溃恢复（补齐 §10 的边界）
6. **记忆增强**：长期记忆接入 embedding 向量库（规模超 50 条后）、冲突消解策略
7. **成本可观测**：单任务 LLM token 消耗统计与预算面板
8. **报告形态**：PDF 导出、邮件版报告
