# formatter_agent 打磨建议（冲刺 85+）

> 目标：在不大改整体架构的前提下，重点优化 `search` 相关设计，让项目从“能跑通”升级为“工程感更强、结果更稳、评审更容易给高分”。

---

## 一、先说结论

从面试题要求看，这个项目的方向是对的：

- 有完整链路：自然语言输入 → 联网搜索 → 结构化整理 → Excel 导出
- 有明确工程骨架：FastAPI / Celery / Redis / PostgreSQL / Agent Loop
- 不是一次性脚本，而是可运行工程
- 已经体现了 `state / policy / tool / reducer / finalizer` 这些 Agent 化设计

如果按面试评分维度来估算，当前项目大概在 **79–83 分** 区间。

如果把搜索模块再打磨一轮，并把文档与演示证据补齐，项目达到 **85+** 是现实目标。

---

## 二、当前项目的主要优点

### 1. 题目链路完整

题目要求的是一个完整任务链，而不是单轮对话。

你现在已经具备：

- 用户提交自然语言查询
- Worker 异步执行任务
- 搜索工具联网召回
- LLM 做结构化抽取
- 结果导出为 Excel
- 任务可查询、可追踪

这点本身就比很多“只有 prompt + print”式作业高一个档次。

### 2. 工程化意识比较强

当前仓库已经体现出真实工程习惯：

- API 与 Worker 分离
- 配置独立
- 状态流转清晰
- 数据库存储任务结果
- 支持日志、warnings、fallback
- 有测试覆盖

这些对“工程实现能力”评分很有帮助。

### 3. Agent 味道是够的

你不是简单“搜一下然后直接让 LLM 输出”。

而是已经做了：

- `TaskCompiler`
- `AgentState`
- `Policy`
- `ToolRunner`
- `Reducer`
- `Finalizer`

这说明你在往“显式工作流 Agent”方向走，这是加分项。

---

## 三、当前最影响分数的地方：Search 模块还不够像一个 Retrieval Pipeline

你的核心问题不是“不会搜索”，而是：

> `search` 现在更像“若干 provider 调用 + 一些后处理”，还没有完全升级成一个明确的检索流水线。

这会带来三个问题：

### 1. 职责边界不够清楚

目前搜索相关逻辑分散在多个地方：

- provider 调用
- HTML 解析
- fallback 处理
- 结果去重
- 候选构建
- 打分 / 筛选 / 重排

这些职责如果混在一起，代码虽然能跑，但评审会觉得：

- search 逻辑偏重
- 维护成本偏高
- 后续扩展 provider / ranking / extraction 时边界不够干净

### 2. 召回与排序还偏 baseline

当前排序更像“query 和 title/summary 的词面匹配”。

这个对简单 query 没问题，但遇到下面这些场景容易不稳：

- 同义表达
- 中英混合 query
- 查询意图是“模板 / 样本 / 对比 / 名单 / 聚合页”时
- 搜索结果 snippet 很短或质量很差时

也就是说，**有召回，但排序质量还不足以形成明显说服力**。

### 3. LLM 结构化抽取吃到的上下文太浅

如果结构化阶段主要依赖搜索结果摘要（title + summary），而不是页面正文，那么最终 Excel 的字段质量上限会被卡住。

题目里很看重：

- 提取有效信息
- 对无关内容进行过滤
- 输出具备业务意义的字段

只靠 snippet，评审很容易怀疑“抽取字段是否真的可靠”。

---

## 四、达到 85+ 的核心思路

不要把 search 继续往“接更多搜索源”方向堆复杂度。

更划算的方向是：

> 把 `search` 升级为 **多源召回 → 统一归一化 → 去重 → 重排 → 正文增强 → 结构化抽取** 的标准流水线。

这会同时提升：

- 工程实现能力分
- Agent 能力设计分
- 数据处理质量分
- 鲁棒性与可观测性分

---

## 五、建议你把 Search 重构成 4 层

建议把搜索模块稳定成以下结构：

```text
query_rewriter
    ↓
search_providers
    ↓
candidate_ranker
    ↓
content_enricher
```

### 1. `query_rewriter`
职责：根据用户 query 和 intent，生成更适合搜索引擎的查询表达。

例如：

- 原 query：`帮我找前端工程师简历模板`
- 重写后查询：
  - `前端工程师 简历 模板`
  - `frontend engineer resume template`
  - `前端 简历 样本 模板 下载`

这样可以提升召回面，而不把复杂度塞进 provider 层。

### 2. `search_providers`
职责：只负责访问具体搜索源，返回统一格式结果。

统一返回结构示例：

```python
{
    "provider": "ddg",
    "title": "...",
    "url": "...",
    "summary": "...",
    "provider_rank": 1,
}
```

要求 provider 层不要做太多业务判断，只做：

- 请求
- HTML 解析
- 结果标准化
- 错误返回

### 3. `candidate_ranker`
职责：对多源结果统一去重、归一化、打分、排序。

这一层是真正决定搜索质量的地方。

### 4. `content_enricher`
职责：对 top candidates 拉取正文片段，为结构化抽取提供更可靠上下文。

这是最值得补的一层。

---

## 六、最优先的 Search 优化项

下面这些改动，投入不算太大，但非常容易拉分。

### 优先级 A1：多源 merge，而不是“首个 provider 成功就返回”

建议不要再采用：

- provider A 有结果 → 直接返回
- provider A 失败 → 再试 provider B

更建议：

- 每个 provider 各取前 5 条
- 合并成候选池
- 做 URL 规范化与去重
- 再统一重排输出 top K

#### 为什么这很重要

因为不同搜索源的覆盖面不一样：

- 有的中文命中更好
- 有的英文模板站更多
- 有的摘要质量更高

如果“谁先成功用谁”，会让结果不稳定。

#### 推荐做法

```python
provider_results = []
for provider in providers:
    provider_results.extend(provider.search(query, top_n=5))

normalized = normalize_urls(provider_results)
deduped = deduplicate(normalized)
ranked = rank_candidates(deduped, query, intent)
final = ranked[:top_k]
```

---

### 优先级 A2：把排序从“词面命中”升级为“多特征打分”

建议把候选打分改成多因素加权，而不是只比较 query 和标题摘要的字面重叠。

推荐公式：

```python
score = (
    0.45 * lexical_score
    + 0.20 * intent_pattern_score
    + 0.20 * source_score
    + 0.15 * provider_rank_score
)
```

#### 各项含义

- `lexical_score`：query 与 title/summary 的关键词命中
- `intent_pattern_score`：是否符合当前任务意图
- `source_score`：来源站点质量评分
- `provider_rank_score`：provider 自身排名前面的候选适当加分

#### 其中最关键的是 `intent_pattern_score`

例如：

如果 intent 是：

- `template / sample`：优先匹配 “模板 / 样本 / 下载 / resume template / cv sample”
- `comparison`：优先匹配 “vs / 对比 / comparison / best”
- `collection`：优先匹配 “列表 / 清单 / 榜单 / candidates / directory”

这会让你的 Agent 理解真正影响搜索结果，而不是只停留在 planner 层。

---

### 优先级 A3：补一个轻量正文抓取 `content_enricher`

这是最值得做的优化。

当前如果只依赖 `title + summary`，结构化结果会有两个问题：

- 字段信息不够丰富
- snippet 偶尔会误导 LLM

建议：

- 对 top 3 candidates 发 HTTP 请求
- 提取：
  - 页面标题
  - meta description
  - 正文前 1~2KB 文本
- 作为 `page_excerpt`
- 传给 LLM 结构化抽取

#### 输入从这样：

```python
{
  "title": "...",
  "summary": "...",
  "url": "..."
}
```

升级成这样：

```python
{
  "title": "...",
  "summary": "...",
  "page_excerpt": "...",
  "url": "..."
}
```

#### 这样做的收益

- 结构化字段更可信
- fallback 结果也更像“从正文提取”而不是“从摘要猜的”
- README 里能明确写出“先召回，再 enrich，再抽取”

这在评审眼里非常加分。

---

### 优先级 A4：从 URL 去重升级到“近重复去重”

互联网搜索里，重复不只是同 URL：

- 带参数的同页
- PC / mobile 页面
- 聚合站转载
- 同模板多镜像

建议在 URL 规范化之外，再加一层标题相似度去重。

#### 规范化建议

- 去掉 tracking 参数
- 去掉末尾 `/`
- 合并 `www.` 与非 `www.`
- 统一 scheme

#### 近重复建议

对 `normalized_title` 做：

- 小写化
- 去标点
- 去停用词
- 再做简单相似度比较

相似度高于阈值时，只保留高分候选。

---

### 优先级 A5：增加状态分级，不要只有成功/失败

建议把任务结果分成：

- `success`
- `partial_success`
- `degraded_success`
- `failed`

#### 示例

- `success`：搜索、抽取、导出都成功
- `partial_success`：结构化失败，但 fallback 输出成功
- `degraded_success`：部分 provider 失败，但结果仍可用
- `failed`：所有链路都失败

这会显得你对生产系统状态语义有思考。

---

## 七、建议补一层 Query Rewrite

这是一个投入小、观感好的增强项。

### 目标

让用户自然语言问题，先转成更适合搜索引擎的检索语句。

### 推荐策略

#### 1. 关键词提纯

例如：

- 用户输入：`帮我找一些适合应届生的 Java 简历模板`
- 改写后：`应届生 Java 简历模板`

#### 2. 中英双路召回

例如：

- `产品经理简历模板`
- 同时补：`product manager resume template`

#### 3. 意图扩展词

按意图补召回词：

- template 类：模板 / 样本 / 示例 / 下载 / sample / template
- comparison 类：对比 / comparison / vs / best
- collection 类：名单 / list / directory / ranking

### 注意

不要把 rewrite 做成很重的 LLM 步骤。

面试项目里，更推荐：

- 规则 + 轻量模板
- 必要时 LLM 只生成 1~3 个 rewrite query

这样更稳，也更容易解释。

---

## 八、建议把 Search 的可观测性显式做出来

题目很强调“可观测”。

建议在日志与任务结果里记录以下指标：

```text
provider_attempts
provider_successes
provider_errors
raw_result_count
deduped_result_count
ranked_candidate_count
enriched_page_count
structured_result_count
used_fallback
result_quality
```

### 示例日志

```text
[search] query="前端工程师简历模板"
[search] providers=[ddg,bing,sogou] raw_count=13 deduped=8 ranked=5
[search] enriched=3 warnings=["bing timeout"]
[structure] extracted_rows=6 used_fallback=false quality=high
```

这样的日志一贴到 README 或截图里，评审会立刻觉得：

- 系统不是黑盒
- 能解释结果从哪来
- 真有工程可观测性

---

## 九、建议把 Search 模块目录再拆清楚一些

推荐目录：

```text
utils/
  search/
    coordinator.py
    query_rewriter.py
    ranker.py
    deduplicator.py
    enricher.py
    providers/
      base.py
      ddg.py
      sogou.py
      bing.py
```

### 组件职责

#### `coordinator.py`
负责：

- 调用 query rewrite
- 并发/顺序调用 provider
- merge 结果
- 调用 dedup + rank + enrich
- 输出统一候选结果

#### `providers/*.py`
负责：

- 请求搜索页
- HTML 解析
- 返回统一结构

#### `ranker.py`
负责：

- 打分
- 排序
- 筛选 top K

#### `deduplicator.py`
负责：

- URL canonicalization
- 标题相似度去重

#### `enricher.py`
负责：

- 拉取页面正文
- 提取 excerpt
- 对失败页面记录 warning

这样评审一看就知道你在按模块治理复杂度。

---

## 十、推荐一个更像工程项目的 Search 输出数据结构

建议候选结果统一成：

```python
from pydantic import BaseModel
from typing import Optional


class SearchCandidate(BaseModel):
    provider: str
    title: str
    url: str
    summary: str = ""
    provider_rank: int = 0
    source_domain: str = ""
    normalized_url: str = ""
    lexical_score: float = 0.0
    intent_pattern_score: float = 0.0
    source_score: float = 0.0
    final_score: float = 0.0
    page_excerpt: Optional[str] = None
    notes: list[str] = []
```

这样后面：

- 结构化抽取
- fallback 输出
- trace 展示
- 任务审计

都会更清楚。

---

## 十一、建议你在 README 里主动解释“为什么 Search 这样设计”

这会很加分。

你可以直接写成下面这段：

### Search Design

本项目的搜索模块采用 **多源召回 + 统一归一化 + 相关性重排 + 正文增强** 的设计：

1. 先根据用户 query 与 intent 生成适合检索的查询表达；
2. 再从多个搜索 provider 召回候选结果；
3. 对候选做 URL 规范化、去重与多特征打分；
4. 对 top candidates 抓取正文片段，作为结构化抽取的上下文输入；
5. 最终由 LLM 根据候选证据生成结构化数据并导出 Excel。

这样设计的目标不是把系统做成搜索引擎，而是让开放域查询在工程上具备：

- 更稳定的召回质量
- 更可解释的结果选择依据
- 更可靠的结构化输出质量

这段话非常适合放进 README。

---

## 十二、你可以这样回答“为什么 search 部分现在显得麻烦”

如果面试官追问，你可以这么说：

> 当前版本的 search 已经能用，但职责还偏集中：provider 调用、去重、排序、候选构建和后续结构化输入之间边界还不够利落。下一步我的优化方向不是继续增加 provider 数量，而是把 search 升级为标准 retrieval pipeline，把多源召回、统一归一化、重排、正文增强和结构化抽取解耦开。这样既能提升结果质量，也能降低系统复杂度，并让 Agent 的决策更可解释。

这会显得你对项目问题有准确判断，而不是只会“继续加功能”。

---

## 十三、如果时间有限，最推荐的落地顺序

### 第一阶段：最划算，先做

1. 多 provider merge
2. 多特征 rank
3. top 3 页面正文 enrich
4. 结果状态分级

### 第二阶段：继续拉高上限

5. query rewrite
6. 标题近重复去重
7. search 指标日志化

### 第三阶段：锦上添花

8. provider timeout / retry / backoff
9. source whitelist / blacklist
10. 结果缓存（避免重复抓取）

---

## 十四、按评分维度看，如何把项目抬到 85+

### 1. 需求理解与方案设计
目标：从 16/20 提到 18/20

做法：

- README 里明确 search 设计
- 补充为什么要 enrich 正文
- 补充 fallback 与 degraded success 设计

### 2. 工程实现能力
目标：从 20/25 提到 22/25

做法：

- search 模块拆层
- 输出统一候选结构
- 减少 `task_service` 对搜索细节的侵入

### 3. AI Agent 能力设计
目标：从 16/20 提到 18/20

做法：

- 让 intent 参与 ranking / rewrite
- 让 Policy 决策影响搜索策略，而不只是决定是否搜索

### 4. 数据处理质量
目标：从 11/15 提到 13/15

做法：

- 正文 enrich
- 近重复去重
- 更合理的候选排序

### 5. 异常处理与鲁棒性
目标：从 8/10 提到 9/10

做法：

- degraded success
- provider warnings
- enrich 失败容忍

### 6. 文档与表达
目标：从 8/10 提到 9/10

做法：

- README 新增 search design
- 给一组真实输入输出示例
- 放日志截图或任务 trace

这样项目整体到 **85–89 分** 是很有机会的。

---

## 十五、最终建议

一句话总结：

> 你当前的问题不是 search 做不出来，而是 search 还停留在 provider 调用层，没有完全升格成一个可解释、可扩展、可观察的 retrieval pipeline。

真正能帮你冲分的，不是继续接更多搜索源，而是把下面这条链做扎实：

```text
Query Rewrite
→ Multi-source Retrieval
→ Normalize / Deduplicate
→ Rank
→ Content Enrich
→ Structured Extraction
→ Excel Export
```

如果这条链清楚了，项目的工程味道会明显增强，评审也更容易给出 85+ 的分数。

---

## 十六、可直接执行的下一步清单

- [ ] 把 provider 搜索改成多源 merge
- [ ] 新增 `candidate_ranker.py`
- [ ] 新增 `content_enricher.py`
- [ ] 给 candidate 增加统一数据结构
- [ ] 增加 URL 规范化 + 标题近重复去重
- [ ] 让 intent 参与 rank 分数
- [ ] 增加 `partial_success / degraded_success`
- [ ] 在 README 增加 `Search Design` 小节
- [ ] 放一组“优化前 vs 优化后”的搜索效果示例
- [ ] 放一段 search 可观测日志截图

