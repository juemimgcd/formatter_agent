# rebuild_agent 优化进度与后续计划

## 目标

把当前项目从“能跑的 Demo”继续收紧到“边界清晰、链路可验证、任务语义明确的工程化 Agent 服务”。

这份文档不再把所有内容都写成未来计划，而是明确区分：

1. 已完成的优化
2. 当前仍然存在的缺口
3. 下一阶段的优先级

---

## 一、当前已完成的优化

### 1. 任务受理与执行解耦

当前主链路已经不再走 FastAPI `BackgroundTasks` 旁路，而是：

```text
POST /tasks/search
-> create task record(status=created)
-> dispatch to Celery
-> update status=queued
-> return 202

Celery worker
-> consume tasks.run_search_task
-> update status=running
-> execute search / llm / export
-> update final status
```

已落地模块：

- `conf/celery_app.py`
- `tasks.py`
- `utils/task_dispatcher.py`
- `utils/task_runner.py`
- `routers/task_router.py`

### 2. schema 边界已收紧

当前边界已经按职责拆开：

- `schemas/search_schema.py`
  - `SearchRequest`
  - `SearchResult`
  - `CandidateResultItem`
  - `StructuredResultItem`
  - `StructuredResultSet`
- `schemas/task_schema.py`
  - `TaskStatus`
  - `TaskItem`
- `schemas/task_dispatch_schema.py`
  - `DispatchPayload`
  - `DispatchResult`
- `schemas/task_runtime_schema.py`
  - `StageTimestampPatch`

这比早期把搜索、任务、派发边界混在一起要清晰得多。

### 3. 结构化抽取真实实现已恢复

`utils/structured_result_builder.py` 已重新接回：

```text
prompt
-> llm
-> pydantic parser
-> normalize structured items
```

当前不再是只有占位函数的半成品状态。

### 4. task_service 运行辅助能力已恢复

`utils/task_service_helpers.py` 已补回核心运行函数：

- `clean_text`
- `select_top_k_results`
- `build_candidates`
- `build_fallback_structured_items`
- `build_result_payload`
- `build_task_item`

这意味着 `utils/task_service.py` 的运行链路已经重新闭合。

### 5. 最小可运行基线已验证

当前测试结果：

```text
26 passed
```

说明至少以下基线已恢复：

- API 创建任务
- API 查询任务
- 搜索失败路径
- 结构化超时 / 空结果 fallback 路径
- Excel 导出路径

---

## 二、当前还没完成的部分

### 1. 状态机只是“枚举到位”，不是“全链路到位”

`TaskStatus` 已经有：

```text
created
queued
running
partial_success
success
failed
timeout
retrying
empty_result
```

但当前主链路真正稳定使用的主要还是：

- `created`
- `queued`
- `running`
- `success`
- `failed`

下面这些还没有真正落地完整语义：

- `partial_success`
- `timeout`
- `retrying`
- `empty_result`

### 2. 阶段时间戳 schema 有了，但还没真正持久化

`StageTimestampPatch` 已存在，但当前主链路没有把这些阶段字段完整写回数据库：

- `search_finished_at`
- `llm_finished_at`
- `export_finished_at`

也还没有扩展 `task_record` 以承接这批字段。

### 3. Celery 已接入，但运行时能力仍是最小版

目前已经完成“入队 + worker 执行”，但还没补全：

- retry 策略
- backoff 策略
- queue routing 的更细粒度使用
- timeout 后状态落库
- worker 级异常分类

### 4. 任务平台接口还不完整

当前接口仍然只有：

- `POST /api/v1/tasks/search`
- `GET /api/v1/tasks/{task_id}`

还缺：

- 任务列表
- 重试任务
- 查询裁剪参数

### 5. 结果质量控制仍然是第一版

当前已经有：

- 文本清洗
- URL 去重
- top-k 截断
- fallback 输出

但还没做强一些的候选质量控制：

- 域名占比限制
- 标题相似度去重
- 更明确的规则评分
- 多源 aggregation
- 结果质量等级

### 6. 结构化输出还缺“工程化可解释性”

还没落地：

- `warnings`
- `used_fallback`
- `result_quality`
- 字段级来源追踪
- `confidence`

这些都已经在之前规划里讨论过，但当前真实代码里还没有闭合。

### 7. Docker / 配置刚补齐到“能跑通”，还不够稳

当前 `docker-compose.yml` 已补上：

- `app`
- `worker`
- `db`
- `redis`

但还没做：

- 多 worker 队列拆分
- 健康检查更细化
- 生产级日志与监控挂载
- 对象存储或共享文件系统支持

---

## 三、下一阶段建议按什么顺序做

建议继续按下面顺序推进。

### Phase A：先把任务运行时做扎实

目标：

- 让任务状态不只是“能跑”，而是“可解释、可恢复、可重试”

优先做：

1. 扩展 `models/task_record.py`
2. 增加 `attempt_count / started_at / finished_at / search_finished_at / llm_finished_at / export_finished_at`
3. 在 `utils/task_service.py` 里真正写入阶段时间
4. 给 Celery 增加 retry / timeout 策略
5. 打通 `timeout -> TaskStatus.TIMEOUT`

### Phase B：把结果质量控制从启发式补到工程版

目标：

- 降低低质量候选进入 LLM 的概率

优先做：

1. 强化 `build_candidates`
2. 增加域名限制和标题相似度去重
3. 明确规则评分字段
4. 逐步从 provider fallback 走向 provider aggregation

### Phase C：把结构化输出从“可用”变成“可审计”

目标：

- 调用方能知道结果是不是 fallback、质量如何、哪些字段不可靠

优先做：

1. 扩展 `StructuredResultItem` 或新增更强输出 schema
2. 加 `warnings / used_fallback / result_quality`
3. 加字段来源追踪
4. 重新定义 `success / partial_success / empty_result`

### Phase D：补平台接口

目标：

- 项目从“单接口任务提交器”升级到“最小任务平台”

优先做：

1. `GET /api/v1/tasks`
2. `POST /api/v1/tasks/{task_id}/retry`
3. 查询结果裁剪参数

### Phase E：补监控和排障能力

目标：

- 出问题时能快速知道卡在哪一层

优先做：

1. 围绕 `task_id` 统一日志字段
2. 阶段耗时统计
3. 队列长度和 worker 消费监控
4. fallback rate / parse success rate 指标

---

## 四、当前最值得继续优化的点

如果只选 3 个最值钱的点，建议是：

### 1. 先把阶段时间和 timeout 真的落库

因为这决定了你能不能解释：

- 为什么任务慢
- 为什么任务卡住
- 为什么任务失败

### 2. 把 `partial_success / empty_result / used_fallback` 做实

因为现在“有结果就 success”仍然过于粗糙，不利于前端和调用方理解结果质量。

### 3. 补任务列表 / 重试接口

因为项目已经有任务记录、调度器和 worker，再缺这层平台接口，就还是半个平台。

---

## 五、简短结论

这个项目现在已经不是“优化还没做”的状态了。

当前更准确的判断是：

- 第一阶段“修复断链、恢复运行、切到 dispatcher/Celery”已经完成
- 第二阶段“把状态机、结果质量和平台能力做全”还没完成

所以接下来的工作重点，不是再修基础断点，而是把现有这条可运行链路继续做深、做实、做完整。
