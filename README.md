# rebuild_agent

一个基于 FastAPI 的结构化联网搜索服务：接收自然语言查询，后台执行搜索、候选结果排序、LLM 二阶段结构化整理与 Excel 导出，并提供任务状态查询接口。

项目目标对齐 `AI_Agent_requirement.md`：

- 支持自然语言输入
- 明确区分搜索工具层、结果处理层、结构化抽取层、Excel 导出层
- 使用真实联网搜索，而不是把“搜索”完全交给单次 prompt
- 提供任务状态持久化、阶段日志、失败兜底和结果预览

## 项目特性

- **任务式接口**：创建任务后立即返回 `202 Accepted`，实际执行在后台完成
- **真实联网搜索**：当前支持 `duckduckgo_html` 与 `sogou_html`
- **自动降级**：DuckDuckGo 失败时自动回退到 Sogou；LLM 抽取失败时回退到启发式结构化结果
- **结果持久化**：任务状态和结果写入 PostgreSQL
- **Excel 导出**：结构化结果自动导出到 `outputs/`
- **可测试**：包含 API、搜索解析、任务编排、Excel 导出等测试

## 技术栈

- **Web 框架**：FastAPI + Uvicorn
- **LLM 调用**：LangChain + OpenAI Compatible Chat API
- **联网搜索**：DuckDuckGo HTML / Sogou HTML + `httpx` + `lxml`
- **结构化抽取**：Pydantic + LangChain 输出解析
- **Excel 导出**：Pandas + OpenPyXL
- **数据库**：PostgreSQL + SQLAlchemy Async + Alembic + asyncpg
- **日志**：Loguru
- **测试**：Pytest + Pytest-Asyncio
- **依赖管理**：uv

## 系统架构

当前实现采用“路由层 + 任务编排层 + 纯函数辅助层 + 工具层 + 持久化层”的分层方式。

### 实际模块映射

- `main.py`：FastAPI 入口、生命周期、全局异常处理、基础探活接口
- `routers/task_router.py`：创建任务、查询任务
- `utils/task_runner.py`：后台任务执行入口
- `utils/task_service.py`：任务主编排、状态流转、结构化阶段调度、失败兜底
- `utils/task_service_helpers.py`：文本清洗、评分排序、候选结果映射、fallback 结果构造、统一结果拼装
- `utils/search_client.py`：联网搜索工具，支持 DuckDuckGo / Sogou HTML
- `utils/rag_retriever.py`：二阶段结构化输入重建
- `utils/structured_result_builder.py`：二阶段结构化抽取
- `utils/llm.py`：LLM 客户端初始化
- `utils/excel_service.py`：Excel 导出
- `utils/task_presenter.py`：任务记录转接口返回模型
- `crud/task_record_crud.py` / `models/task_record.py`：任务持久化
- `conf/settings.py`：配置管理
- `conf/db_conf.py`：异步数据库连接与会话管理
- `conf/logging_conf.py`：日志配置

### Mermaid 流程图

```mermaid
flowchart LR
  U[User Chat] --> API[POST /api/v1/tasks/search]
  API --> DB1[(task_records: pending)]
  API --> BG[BackgroundTasks]
  BG --> RUNNER[task_runner.execute_task_by_id]
  RUNNER --> ORCH[task_service.run_search_task]
  ORCH --> ST[search_client.search_web]
  ST --> HP[task_service_helpers.select_top_k_results / build_candidates]
  HP --> RP[retriever.build_rebuild_prompt_input]
  RP --> LLM[structured_result_builder]
  LLM --> XL[excel_service.export_results_to_excel]
  XL --> DB2[(task_records: success/failed)]
  DB2 --> QUERY[GET /api/v1/tasks/task_id]
```

## 核心执行流程

主链路如下：

`create task -> background run -> search tool -> rerank/top-k -> rebuild prompt -> structured LLM -> excel -> query task`

### 1. 创建任务并后台执行

`routers/task_router.py` 的 `POST /api/v1/tasks/search` 会先创建 `pending` 任务，再通过 FastAPI `BackgroundTasks` 触发后台执行。

- 任务创建：`utils/task_service.py` 中的 `create_pending_task`
- 后台入口：`utils/task_runner.py`
- 主编排：`utils/task_service.py` 中的 `run_search_task`

### 2. 联网搜索

`utils/search_client.py` 负责执行真实联网检索，当前支持：

- `duckduckgo_html`
- `sogou_html`

行为说明：

- 默认 provider 为 `duckduckgo_html`
- 如果 DuckDuckGo 返回异常或挑战页，会自动回退到 Sogou
- 搜索结果页当前只解析 `title / url / snippet / source / rank`
- 当前不抓取命中网页正文
- 搜索底层最多返回 10 条候选结果

### 3. 搜索结果排序与 Top-K 选择

`utils/task_service_helpers.py` 负责：

- 文本清洗
- query term 提取
- 搜索结果启发式打分
- top-k 排序
- 候选结果映射
- fallback 结构化结果构造

当前编排逻辑中：

- 搜索抓取数量会综合 `request.max_results`、`SEARCH_RESULT_LIMIT` 与固定 top-k 需求计算
- 进入结构化阶段的候选结果固定取 top-5
- 最终输出结果会再按 `request.max_results` 截断

这意味着：即使接口请求 `max_results=50`，当前版本也不会实际处理 50 条网页结果，因为搜索底层上限为 10，结构化阶段固定只使用 top-5 候选。

### 4. 重建结构化输入

`utils/rag_retriever.py` 负责把 top-k 候选结果压缩为 JSON 文本，用作第二阶段结构化抽取的输入。

### 5. 结构化整理

`utils/structured_result_builder.py` 对候选结果执行第二阶段结构化抽取，生成业务字段：

- `query`
- `title`
- `source`
- `url`
- `content_type`
- `region`
- `role_direction`
- `summary`
- `quality_score`
- `extraction_notes`

字段设计理由：当前输入主要来自搜索结果标题与 snippet，而不是网页正文，因此选择跨主题、跨来源都较稳定的通用字段，保证 Excel 可读、可排序、可复用。

### 6. 失败兜底与 Excel 导出

- DuckDuckGo 失败时自动回退到 Sogou
- 如果结构化阶段异常、超时或返回空结果，会回退到搜索结果生成 fallback 结构化输出
- 如果搜索阶段失败或没有结果，会返回空结果成功态或失败态提示
- `utils/excel_service.py` 将最终结果导出到 `outputs/` 目录

## API 一览

### 基础接口

- `GET /`：根路由，返回服务环境与路由挂载状态
- `GET /health`：健康检查

### 任务接口

- `POST /api/v1/tasks/search`：创建搜索任务
- `GET /api/v1/tasks/{task_id}`：查询任务详情

## 请求与响应模型

### 创建任务请求

位置：`schemas/task_schema.py`

```json
{
  "query": "大模型应用架构设计",
  "max_results": 5
}
```

字段说明：

- `query`：搜索主题，1~200 字符
- `max_results`：最终保留结果数，取值 1~50，默认 5

### 创建任务响应示例

> 接口会先返回 `202 Accepted`，状态为 `pending`，实际执行在后台完成。

```json
{
  "success": true,
  "message": "success",
  "data": {
    "task_id": "a1b2c3d4",
    "query": "大模型应用架构设计",
    "status": "pending",
    "total_items": 0,
    "excel_path": null,
    "preview_items": [],
    "result_items": [],
    "message": "任务已创建",
    "error": null
  }
}
```

### 查询任务响应示例

```json
{
  "success": true,
  "message": "success",
  "data": {
    "task_id": "a1b2c3d4",
    "query": "大模型应用架构设计",
    "status": "success",
    "total_items": 5,
    "excel_path": "E:/python_files/rebuild_agent/outputs/structured_search_result_xxx.xlsx",
    "preview_items": [
      {
        "query": "大模型应用架构设计",
        "title": "...",
        "source": "...",
        "url": "https://example.com/...",
        "content_type": "document",
        "region": "不限",
        "role_direction": "通用",
        "summary": "...",
        "quality_score": 84,
        "extraction_notes": "..."
      }
    ],
    "result_items": [
      {
        "query": "大模型应用架构设计",
        "title": "...",
        "source": "...",
        "url": "https://example.com/...",
        "content_type": "document",
        "region": "不限",
        "role_direction": "通用",
        "summary": "...",
        "quality_score": 84,
        "extraction_notes": "..."
      }
    ],
    "message": "任务执行完成",
    "error": null
  }
}
```

## 目录结构

```text
rebuild_agent/
├─ main.py
├─ conf/
│  ├─ db_conf.py
│  ├─ logging_conf.py
│  └─ settings.py
├─ crud/
├─ models/
├─ routers/
│  └─ task_router.py
├─ schemas/
├─ utils/
│  ├─ excel_service.py
│  ├─ llm.py
│  ├─ rag_retriever.py
│  ├─ search_client.py
│  ├─ structured_result_builder.py
│  ├─ task_presenter.py
│  ├─ task_runner.py
│  ├─ task_service.py
│  └─ task_service_helpers.py
├─ tests/
├─ scripts/
│  └─ benchmark_api.py
├─ alembic/
├─ outputs/
├─ storage/
├─ Dockerfile
├─ docker-compose.yml
└─ pyproject.toml
```

## 环境准备

- Python 3.13+
- PostgreSQL
- uv

复制环境变量：

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

### 关键配置项

- `DATABASE_URL`：数据库连接地址，用于应用数据库访问和 Alembic 迁移
- `DASHSCOPE_API_KEY`：用于 LLM 结构化抽取；未配置时会触发结构化阶段降级
- `LLM_BASE_URL`：OpenAI Compatible 接口地址
- `LLM_MODEL_NAME`：结构化抽取使用的模型名
- `STRUCTURED_STAGE_TIMEOUT_SECONDS`：结构化阶段超时控制，`0` 表示不启用超时
- `SEARCH_PROVIDER`：当前支持 `duckduckgo_html` / `sogou_html`
- `SEARCH_TIMEOUT_SECONDS`：搜索请求超时时间
- `SEARCH_RESULT_LIMIT`：默认搜索结果数量上限
- `SEARCH_REGION`：DuckDuckGo 搜索地域参数

说明：

- `CANDIDATE_CHUNK_TIMEOUT_SECONDS` 已保留在配置中，但当前版本尚未接入实际执行逻辑
- `output_dir` 固定为项目下的 `outputs/` 目录，不通过环境变量配置

`.env.example` 示例：

```env
APP_NAME=Resume Search Agent
APP_ENV=dev
APP_DEBUG=true
APP_HOST=127.0.0.1
APP_PORT=8000
APP_API_PREFIX=/api/v1
DATABASE_URL=postgresql+asyncpg://postgres:123456@localhost:5432/rebuild_agent
DASHSCOPE_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=0
CANDIDATE_CHUNK_TIMEOUT_SECONDS=0
STRUCTURED_STAGE_TIMEOUT_SECONDS=0
SEARCH_PROVIDER=duckduckgo_html
SEARCH_TIMEOUT_SECONDS=12
SEARCH_RESULT_LIMIT=8
SEARCH_REGION=cn-zh
```

## 启动方式

### 安装依赖

```bash
uv sync
```

安装开发依赖：

```bash
uv sync --group dev
```

### 初始化数据库

```bash
uv run alembic upgrade head
```

### 启动服务

```bash
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Docker Compose 启动

```bash
docker compose up --build
```

当前 `docker-compose.yml` 会：

- 启动 `postgres:17-alpine`
- 等待数据库健康检查通过后再启动应用
- 应用容器启动前执行 `uv run alembic upgrade head`
- 将 `outputs/`、`storage/` 挂载到宿主机

## 接口示例

### 1. 创建任务

```http
POST http://127.0.0.1:8000/api/v1/tasks/search
Content-Type: application/json

{
  "query": "大模型应用架构设计",
  "max_results": 5
}
```

### 2. 查询任务结果

```http
GET http://127.0.0.1:8000/api/v1/tasks/a1b2c3d4
```

### 3. 健康检查

```http
GET http://127.0.0.1:8000/health
```

## 示例输入输出

示例输入：

- `大模型应用架构设计`
- `RAG 检索增强生成`
- `上海 AI 产品经理岗位分析`
- `跨境电商选品方法`

示例输出：

- `POST /api/v1/tasks/search` 返回任务 ID 与 `pending` 状态
- `GET /api/v1/tasks/{task_id}` 返回任务状态、Excel 路径、预览数据、完整结果
- `outputs/` 目录生成 Excel 文件

## 异常处理与鲁棒性

当前实现已覆盖：

- 搜索 provider 不支持时返回明确错误
- DuckDuckGo 异常时自动回退到 Sogou
- 搜索超时或上游失败时返回明确提示
- 二阶段结构化超时、异常或空结果时回退到搜索结果
- 最终无结果时返回“未找到可用结果”或空结果成功态
- 创建任务、查询任务、参数校验均有统一接口包装
- 全局异常统一包装
- 全链路阶段日志

## 运行测试

```bash
uv run pytest
```

当前测试覆盖：

- 根路由与健康检查接口
- 创建任务与查询任务接口包装
- 请求参数校验与全局异常处理
- 搜索结果解析
- 搜索结果评分、top-k 排序与字段映射路径
- 任务编排层的成功、空结果、搜索失败、结构化超时降级路径
- Excel 导出
- 统一响应包装

## 接口压测

压测脚本位于 `scripts/benchmark_api.py`，默认会压测以下接口：

- `GET /health`
- `POST /api/v1/tasks/search`
- `GET /api/v1/tasks/{task_id}`

使用前请先启动服务。

默认压测：

```bash
uv run python scripts/benchmark_api.py --base-url http://127.0.0.1:8000
```

输出 JSON：

```bash
uv run python scripts/benchmark_api.py --base-url http://127.0.0.1:8000 --output json
```

自定义并发和请求量：

```bash
uv run python scripts/benchmark_api.py \
  --base-url http://127.0.0.1:8000 \
  --health-total 200 \
  --health-concurrency 50 \
  --create-total 30 \
  --create-concurrency 10 \
  --detail-total 100 \
  --detail-concurrency 20
```

只压创建任务接口：

```bash
uv run python scripts/benchmark_api.py \
  --base-url http://127.0.0.1:8000 \
  --skip-health \
  --skip-detail
```

## 示例运行结果

仓库评审时建议附上：

- 一个示例输入
- 一次任务执行日志或终端截图
- `outputs/` 下生成的 Excel 文件
- `GET /api/v1/tasks/{task_id}` 的成功响应示例

## 已知问题与后续优化方向

- 当前搜索工具依赖 HTML 搜索页面解析，稳定性弱于商业搜索 API，可继续抽象 provider 并接入 Serper、Bing、SearXNG。
- 当前结构化输入仍以搜索结果标题和 snippet 为主，后续可增加页面抓取与正文解析层。
- 当前任务执行方式为 FastAPI `BackgroundTasks` 进程内后台执行，后续可接入 Celery、RQ 或消息队列。
- 当前结构化阶段固定只使用 top-5 候选，后续可按 query 类型动态调整候选数。
- 当前 `.env.example` 中的 `APP_NAME=Resume Search Agent` 与项目整体命名不完全一致，后续可统一为更贴近仓库定位的名称。
- `storage/` 当前主要作为预留目录和容器挂载目录，尚未承担核心业务功能。

## 与题目要求的对应关系

按 `AI_Agent_requirement.md` 评估，当前版本已覆盖：

- **需求理解与方案设计**：完整覆盖输入、搜索、抽取、输出链路，并采用任务式接口返回
- **工程实现能力**：模块清晰，配置分离，可运行，可测试，可通过 Docker Compose 启动
- **AI Agent 能力设计**：包含搜索工具调用、候选筛选、结构化整理、状态流转、失败兜底
- **数据处理质量**：包含过滤、打分、去重、结构化字段设计与 Excel 导出
- **异常处理与鲁棒性**：搜索异常、结构化失败、空结果、全局异常均有处理
- **文档与表达**：README 对技术栈、架构、流程、运行方式和优化方向进行了完整说明
