# rebuild_agent

一个通用的 `Natural Language Query -> Structured Data Output` 系统。用户提交开放领域自然语言查询后，API 负责创建任务并入队，Celery worker 负责完成意图解析、Schema 解析、搜索、结构化整理、质量标注和 Excel 导出，最终通过任务接口查询状态与结构化结果。

## 当前状态

- 任务受理链路已经切到 `create -> queued -> worker -> running -> success/failed`
- 查询进入执行链路前会先解析为通用查询形态 intent：`general / lookup / collection / comparison`
- 当前默认使用 `generic_search_result` 输出 schema，后续可以扩展为更多查询形态 schema
- 执行侧已加入轻量 planner，用于显式表达 `search -> rank -> structure -> export` 的计划
- 搜索结果经过统一清洗、top-k 选择、候选映射后再进入结构化阶段
- 结构化阶段已恢复真实 `prompt + llm + parser` 实现
- 结构化失败或返回空结果时，会回退到候选结果生成 fallback 输出
- 最终任务对象会返回 `used_fallback / result_quality / warnings` 这类轻量质量标注
- `pytest` 当前通过：`34 passed`

## System Design Philosophy

本项目不是某个垂直场景 Agent，而是一个通用结构化数据生成 pipeline：

```text
Natural Language Query
-> Intent Parser
-> Schema Resolver
-> Planner
-> Search / Rank / Structure / Export
-> Task Memory
-> Result Quality Check
-> Structured Data Output
```

设计原则：

- 领域无关：具体业务查询只是使用场景，不是系统边界。
- Schema 可扩展：当前只有默认 `generic_search_result`，但 schema 解析层已经独立。
- Workflow-first：保留稳定工程链路，不引入复杂多轮 Agent runtime。
- 轻量 Agent-like：用 Intent、Schema、Planner、Task Memory 表达可解释执行过程。
- 不做独立自我评估模块：只做 `result_quality` 标注，不触发自动重试或自我修复循环。

## 技术栈

- Web：FastAPI + Uvicorn
- 任务调度：Celery + Redis
- 数据库：PostgreSQL + SQLAlchemy Async + Alembic + asyncpg
- 搜索：DuckDuckGo HTML / Sogou HTML + `httpx` + `lxml`
- 结构化抽取：LangChain + OpenAI Compatible Chat API + Pydantic
- 导出：Pandas + OpenPyXL
- 日志：Loguru
- 测试：Pytest + Pytest-Asyncio

## 核心流程

可以把这条链路分成 4 段来看：

- 提交任务：用户发起自然语言问题，API 创建任务并投递到 Celery
- 任务理解：worker 解析 intent、解析输出 schema，并构造轻量执行计划
- 执行任务：worker 完成联网搜索、结果清洗、候选构造、LLM 结构化整理、fallback、质量标注与 Excel 导出
- 查询结果：前端或调用方通过任务详情接口轮询最终结构化结果、预览结果和导出文件路径

```text
用户输入 query
-> POST /api/v1/tasks/search
-> 创建 task_record(status=created)
-> dispatch_task 投递到 Celery / Redis
-> 更新 status=queued
-> 返回 202 + task_id

Celery worker 消费任务
-> status=running
-> parse_search_intent 解析查询形态
-> resolve_output_schema 解析输出 schema
-> build_execution_plan 构造 search/rank/structure/export 计划
-> search_web 联网搜索
-> build_candidates 映射为候选结果
-> select_top_candidates 去重 + 简单相关性重排 + top-k
-> build_rebuild_prompt_input 重建结构化提示词输入
-> build_structured_results 调用 prompt + llm + parser
-> 若结构化失败或为空则 fallback 到候选结果
-> evaluate_result_quality 标注 high/fallback/low
-> export_results_to_excel 导出 Excel
-> 写回 task_records(status/result_payload/excel_path/error_message)

客户端轮询 GET /api/v1/tasks/{task_id}
-> task_presenter 把记录转换为 TaskItem
-> 返回 preview_items / result_items / excel_path / status / error / result_quality / warnings
```

```mermaid
flowchart TD
  U[用户输入自然语言问题<br/>query + max_results]

  subgraph S1[1. API 提交阶段]
    API[POST /api/v1/tasks/search]
    VALIDATE[FastAPI / Pydantic 校验请求体]
    CREATE[create_pending_task<br/>生成 task_id + 清洗 query]
    DB_CREATED[(task_records<br/>status=created)]
    DISPATCH[dispatch_task / dispatch_search_task]
    REDIS[(Redis / Celery Broker)]
    QUEUED[更新任务状态为 queued]
    ACCEPT[返回 202 Accepted<br/>task_id + status=queued]
  end

  subgraph S2[2. Worker 执行阶段]
    WORKER[Celery worker<br/>tasks.run_search_task]
    RUNNER[execute_task_from_payload]
    RUNNING[更新任务状态为 running]
    INTENT[parse_search_intent<br/>general / lookup / collection / comparison]
    SCHEMA[resolve_output_schema<br/>generic_search_result]
    PLAN[build_execution_plan<br/>search / rank / structure / export]
    SEARCH[search_web]
    PROVIDER{搜索 provider}
    DDG[DuckDuckGo HTML]
    SOGOU[搜狗 HTML]
    RAW[原始搜索结果<br/>title / url / snippet / rank]
    CAND[build_candidates<br/>转换为 CandidateResultItem]
    RERANK[select_top_candidates<br/>按 query 去重 + 简单相关性重排 + top-k]
    REBUILD[build_rebuild_prompt_input<br/>构造二阶段 JSON 提示输入]
    LLM[build_structured_results<br/>prompt + llm + pydantic parser]
    CHECK{结构化结果是否成功且非空}
    STRUCT[StructuredResultItem 列表<br/>query / title / source / url / summary / quality_score]
    FALLBACK[build_fallback_structured_items<br/>用候选结果生成保底结构化输出]
    QUALITY[evaluate_result_quality<br/>high / fallback / low]
    EXPORT{是否有最终结果}
    EXCEL[export_results_to_excel<br/>生成 .xlsx 文件]
    DB_SUCCESS[(写回 task_records<br/>status=success<br/>result_payload + excel_path)]
    DB_FAILED[(写回 task_records<br/>status=failed<br/>error_message)]
  end

  subgraph S3[3. 结果查询阶段]
    DETAIL[GET /api/v1/tasks/task_id]
    LOAD[读取 task_records]
    PRESENT[build_task_item_from_record]
    RESPONSE[返回 TaskItem<br/>status / preview_items / result_items / excel_path / error]
  end

  U --> API
  API --> VALIDATE --> CREATE --> DB_CREATED --> DISPATCH --> REDIS
  DISPATCH --> QUEUED --> ACCEPT

  REDIS --> WORKER --> RUNNER --> RUNNING --> INTENT --> SCHEMA --> PLAN --> SEARCH --> PROVIDER
  PROVIDER --> DDG --> RAW
  PROVIDER --> SOGOU --> RAW
  DDG -. 异常或空结果时兜底 .-> SOGOU
  RAW --> CAND --> RERANK --> REBUILD --> LLM --> CHECK
  CHECK -->|成功| STRUCT --> QUALITY --> EXPORT
  CHECK -->|失败或空结果| FALLBACK --> QUALITY --> EXPORT
  EXPORT -->|有结果| EXCEL --> DB_SUCCESS
  EXPORT -->|无结果| DB_SUCCESS
  SEARCH -. 搜索异常 .-> DB_FAILED
  LLM -. 未捕获异常 .-> DB_FAILED

  U --> DETAIL
  DETAIL --> LOAD --> PRESENT --> RESPONSE
  LOAD -. 读取最终状态与结果载荷 .-> DB_SUCCESS
  LOAD -. 读取失败信息 .-> DB_FAILED
```

## 主要模块

- `main.py`：应用入口、生命周期、全局异常处理
- `routers/task_router.py`：创建任务、查询任务详情
- `conf/celery_app.py`：Celery 应用初始化
- `tasks.py`：Celery task 注册入口
- `utils/task_dispatcher.py`：任务入队与 dispatch 元数据封装
- `utils/task_runner.py`：worker 侧执行入口
- `utils/task_service.py`：intent、schema、plan、搜索、结构化、导出和状态更新主编排
- `utils/task_service_helpers.py`：文本清洗、top-k、候选映射、fallback、结果拼装、质量标注
- `utils/intent_parser.py`：把自然语言 query 解析为通用查询形态
- `utils/schema_registry.py`：解析当前任务使用的输出 schema
- `utils/planner.py`：生成轻量执行计划，保留工具语义但不引入动态 tool registry
- `utils/search_client.py`：联网搜索 provider
- `utils/retriever.py`：二阶段结构化输入重建
- `utils/structured_result_builder.py`：LLM 结构化抽取
- `utils/task_presenter.py`：数据库记录转接口模型
- `schemas/search_schema.py`：搜索请求、搜索结果、候选结果、结构化结果
- `schemas/intent_schema.py`：查询意图模型
- `schemas/agent_schema.py`：执行计划、输出 schema、任务记忆等轻量边界模型
- `schemas/task_schema.py`：任务状态和任务接口返回模型
- `schemas/task_dispatch_schema.py`：dispatcher 边界模型

## API

### 创建任务

`POST /api/v1/tasks/search`

请求体位置：`schemas/search_schema.py`

```json
{
  "query": "大模型应用架构设计",
  "max_results": 5
}
```

成功响应现在返回 `queued`，而不是旧的 `pending`：

```json
{
  "success": true,
  "message": "success",
  "data": {
    "task_id": "a1b2c3d4",
    "query": "大模型应用架构设计",
    "status": "queued",
    "total_items": 0,
    "excel_path": null,
    "preview_items": [],
    "result_items": [],
    "message": "任务已排队",
    "error": null,
    "attempt_count": 0,
    "used_fallback": false,
    "result_quality": "unknown",
    "warnings": []
  }
}
```

### 查询任务

`GET /api/v1/tasks/{task_id}`

成功后可拿到：

- `status`
- `preview_items`
- `result_items`
- `excel_path`
- `error`
- `used_fallback`
- `result_quality`
- `warnings`

`result_quality` 是轻量质量标注，不等同于事实核查：

- `high`：结构化结果存在，且质量分、URL 等基础字段正常
- `fallback`：结构化阶段失败或为空，结果来自候选搜索结果保底生成
- `low`：结果为空、平均质量分过低或存在明显结构问题
- `unknown`：任务尚未完成或历史记录未写入质量信息

### 任务列表

`GET /api/v1/tasks`

支持查询参数：

- `status`：按任务状态过滤
- `query`：按任务 query / task_id 模糊过滤
- `limit`：分页大小，默认 `20`
- `offset`：分页偏移，默认 `0`

返回结构示例：

```json
{
  "success": true,
  "message": "success",
  "data": {
    "items": [
      {
        "task_id": "a1b2c3d4",
        "query": "AI 产品经理",
        "status": "success",
        "total_items": 5,
        "excel_path": "E:/python_files/rebuild_agent/outputs/structured_search_result_AI_产品经理_20260415_094851.xlsx",
        "preview_items": [],
        "result_items": [],
        "message": "任务执行完成",
        "error": null,
        "attempt_count": 0,
        "used_fallback": false,
        "result_quality": "unknown",
        "warnings": []
      }
    ],
    "count": 1,
    "limit": 20,
    "offset": 0
  }
}
```

### 重试任务

`POST /api/v1/tasks/{task_id}/retry?max_results=5`

当前仅允许这些状态重试：

- `failed`
- `timeout`
- `partial_success`

说明：

- 重试会清空旧的 `result_payload / excel_path / error_message`，并将任务重新派发到队列
- 由于当前数据库尚未持久化原始 `max_results`，重试接口要求显式传入或接受默认值

## 目录结构

```text
rebuild_agent/
├─ main.py
├─ tasks.py
├─ conf/
├─ crud/
├─ models/
├─ routers/
├─ schemas/
├─ utils/
├─ tests/
├─ docs/
├─ scripts/
├─ alembic/
├─ outputs/
├─ storage/
├─ docker-compose.yml
└─ pyproject.toml
```

## 环境变量

复制环境变量文件：

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

关键配置：

- `DATABASE_URL`：PostgreSQL 连接串
- `CELERY_BROKER_URL`：Celery broker，默认 Redis `0` 号库
- `CELERY_RESULT_BACKEND`：Celery backend，默认 Redis `1` 号库
- `DASHSCOPE_API_KEY`：结构化抽取使用的模型 API Key
- `LLM_BASE_URL` / `LLM_MODEL_NAME`：OpenAI Compatible 模型配置
- `STRUCTURED_STAGE_TIMEOUT_SECONDS`：结构化阶段超时
- `SEARCH_PROVIDER`：`duckduckgo_html` 或 `sogou_html`

`.env.example` 中已经包含上述默认项。

## 本地启动

### 1. 安装依赖

```bash
uv sync
uv sync --group dev
```

### 2. 初始化数据库

```bash
uv run alembic upgrade head
```

### 3. 启动 Redis

本地需要一个可用的 Redis 实例，默认地址：

```text
redis://127.0.0.1:6379/0
redis://127.0.0.1:6379/1
```

### 4. 启动 Celery worker

Windows 本地开发请使用 `solo` pool，避免 `billiard` 进程池权限错误：

```powershell
uv run celery -A conf.celery_app:celery_app worker --pool=solo --loglevel=INFO -Q search_queue
```

macOS / Linux 可继续使用默认 pool：

```bash
uv run celery -A conf.celery_app:celery_app worker --loglevel=INFO -Q search_queue
```

### 5. 启动 API

```bash
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Docker Compose

当前 `docker-compose.yml` 已包含：

- `app`
- `worker`
- `db`
- `redis`

启动：

```bash
docker compose up --build
```

## 压测

项目提供两个压测脚本：

- `scripts/benchmark_api.py`：固定请求总量的基准测试，适合快速比较单次改动前后的接口延迟。
- `scripts/load_test_api.py`：持续时长型压测，适合观察固定并发下的吞吐、延迟分位数和错误率。

先启动 API，再运行压测脚本：

```bash
uv run python scripts/load_test_api.py --scenario health --duration-seconds 30 --concurrency 20
```

如果要压任务链路，需要确保 PostgreSQL、Redis、Celery worker 都已启动：

```bash
uv run python scripts/load_test_api.py --scenario mixed --duration-seconds 60 --concurrency 10 --max-results 1
```

输出 JSON 方便后续归档或画图：

```bash
uv run python scripts/load_test_api.py --scenario mixed --duration-seconds 60 --concurrency 10 --output json
```

### 本机实测结果

测试环境：Windows 本机开发环境，API 使用 `uv run uvicorn main:app --host 127.0.0.1 --port 8000` 单进程启动，压测客户端与服务端在同一台机器上。测试时间：2026-04-15。

| 接口场景 | 压测参数 | 请求数 | 成功率 | 吞吐量 RPS | 平均响应 | P50 | P95 | P99 | 状态码 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `GET /health` | `30s / concurrency=20` | 32553 | 100.00% | 1091.38 | 18.31ms | 8.42ms | 61.29ms | 101.72ms | `200: 32553` |
| `GET /api/v1/tasks` | `30s / concurrency=10` | 8663 | 100.00% | 290.25 | 34.43ms | 33.30ms | 38.20ms | 51.39ms | `200: 8663` |
| `GET /api/v1/tasks/{task_id}` | `30s / concurrency=10` | 15436 | 100.00% | 518.20 | 19.29ms | 18.41ms | 22.49ms | 34.45ms | `200: 15436` |
| `POST /api/v1/tasks/search` | `10s / concurrency=2 / think-time=100ms` | 115 | 100.00% | 11.67 | 64.21ms | 52.76ms | 164.57ms | 209.66ms | `202: 115` |

对应命令：

```bash
uv run python scripts/load_test_api.py --scenario health --duration-seconds 30 --concurrency 20 --output json
uv run python scripts/load_test_api.py --scenario list --duration-seconds 30 --concurrency 10 --output json
uv run python scripts/load_test_api.py --scenario detail --duration-seconds 30 --concurrency 10 --output json
uv run python scripts/load_test_api.py --scenario create --duration-seconds 10 --concurrency 2 --think-time-ms 100 --max-results 1 --output json
```

解读：

- `/health` 主要反映 FastAPI/Uvicorn 的基础 HTTP 开销，不代表完整业务链路能力。
- 任务列表和详情接口都经过数据库查询，当前本机读接口 P95 分别约为 `38.20ms` 和 `22.49ms`。
- 任务创建接口会真实写库并投递 Celery/Redis，本次用低并发和 `think-time` 控制入队速度，测到的是安全压测参数下的受理能力，不是极限吞吐。
- 这些数据是本机开发环境结果，生产环境需要在目标机器、目标 worker 数、目标数据库和 Redis 配置下重新压测。

可选场景：

- `health`：只压 `GET /health`，用于观察 API 基础吞吐和框架开销。
- `create`：只压 `POST /api/v1/tasks/search`，会真实创建任务并入队。
- `list`：只压 `GET /api/v1/tasks`，用于观察任务列表查询性能。
- `detail`：先创建一个种子任务，再压 `GET /api/v1/tasks/{task_id}`。
- `mixed`：按比例混合 `health / list / create / detail`，更接近综合访问形态。

压测指标说明：

- `total`：压测期间实际发出的请求总数。
- `concurrency`：并发请求 worker 数，不等同于 QPS。
- `rps`：每秒完成请求数，计算方式为 `total / duration_seconds`。
- `success`：HTTP 状态码在 `2xx` 范围内的请求数。
- `errors`：非 `2xx` 响应和请求异常数量。
- `success_rate` / `error_rate`：成功率与错误率，单位是百分比。
- `avg_ms`：平均响应耗时，容易受慢请求影响。
- `p50_ms`：中位响应耗时，代表典型请求体验。
- `p90_ms` / `p95_ms` / `p99_ms`：尾部延迟，优先关注 `p95_ms` 和 `p99_ms` 是否异常放大。
- `min_ms` / `max_ms`：最小和最大响应耗时，用于快速发现极端值。
- `status_codes`：状态码分布，用于区分参数错误、服务错误、限流或上游异常。
- `sample_errors`：最多保留 5 条错误样本，便于快速定位失败原因。

注意：`create` 和 `mixed` 场景会真实调用任务创建接口，可能触发 worker 搜索、LLM 调用和 Excel 导出。压测前建议把 `--max-results` 设小，并确认测试环境的模型额度、Redis 队列和数据库写入能力足够。

## 测试

运行测试：

```bash
uv run pytest
```

当前覆盖：

- 根路由与健康检查
- 创建任务与查询任务接口
- 请求参数校验与全局异常处理
- 搜索结果解析
- 任务编排成功/失败/降级路径
- intent / planner / result quality 轻量组件
- Excel 导出

当前结果：

```text
34 passed
```

## Design Trade-offs

- HTML 搜索 provider：成本低、便于本地 demo，但稳定性弱于商业搜索 API。
- `top-k=5`：在召回、LLM token 成本、延迟和结构化稳定性之间取平衡。
- snippet-based extraction：保持链路轻量，但牺牲网页正文级信息密度。
- generic schema first：先证明 schema 层存在，不急于过早堆多套场景 schema。
- no separate tool registry：工具名直接放在 `PlanStep.tool_name`，保留可解释性，同时减少运行时代码。
- no self-evaluation module：只做结果质量标注，不引入不可控的多轮自我修复。
