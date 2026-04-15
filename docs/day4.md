# Day 4：任务平台接口与可观测性收口

## 今天的总目标

- 不再把这个项目看成“只有创建和查询两个接口的后台任务服务”
- 开始把它收口成一个更完整的任务平台
- 让状态、结果质量和执行过程都能被查询、控制和排障

## 今天结束前，你必须拿到什么

- `routers/task_router.py` 中的列表 / 取消 / 重试接口方案
- `crud/task_record_crud.py` 中的过滤、分页、条件更新能力
- `schemas/task_observability_schema.py`
- `utils/task_control_service.py`
- `utils/metrics.py`
- 一套你能自己复述的 `submit -> observe -> query -> cancel/retry -> diagnose` 理解框架

---

## Day 4 一图总览

如果把 Day 4 压缩成一句话，它做的就是：

> 把前面三天做出的状态语义和质量语义，真正变成平台对外能力。

今天的主链路可以先背成这样：

```text
submit task
-> list / query task
-> inspect status and quality flags
-> cancel or retry if allowed
-> inspect logs and metrics
-> diagnose queue / search / llm / export issues
```

你今天要特别清楚：

- Day 3 的重点是“结果可控”
- Day 4 的重点是“平台可用、可查、可诊断”

---

## 为什么 Day 4 也要重构

当前项目虽然已经有：

- `POST /api/v1/tasks/search`
- `GET /api/v1/tasks/{task_id}`

但对于一个任务系统来说，它仍然不够像平台：

- 没有任务列表
- 没有取消
- 没有重试
- 查询信息层次不够清楚
- 日志与指标还不成体系

所以 Day 4 的一句话重构目标就是：

> 让任务系统不只是“能提交”，而是“能使用、能控制、能排障”。

---

## Day 4 整体架构

```mermaid
flowchart TD
    A[client] --> B[POST /tasks/search]
    A --> C[GET /tasks]
    A --> D[GET /tasks/{task_id}]
    A --> E[POST /tasks/{task_id}/cancel]
    A --> F[POST /tasks/{task_id}/retry]
    C --> G[crud/task_record_crud.py]
    D --> G
    E --> H[utils/task_control_service.py]
    F --> H
    H --> G
    G --> I[models/task_record.py]
    B --> J[task execution system]
    J --> K[logs]
    J --> L[metrics]
```

### 你要怎么理解这张图

#### 第 1 层：平台接口层

这一层负责：

- 查询任务历史
- 查询任务详情
- 控制任务状态

白话理解：

- 用户不只是提交任务
- 用户还需要看、筛、控、重试

#### 第 2 层：任务控制层

这一层负责：

- 决定哪些状态允许取消
- 决定哪些状态允许重试
- 决定查询返回多少信息

这里的重点是：

- 状态合法性不要散落在路由里

#### 第 3 层：可观测层

这一层负责：

- 统一日志上下文
- 记录阶段耗时
- 提供最小可诊断指标

---

## 今天的边界要讲透

## 第 1 层：Day 4 不是“多加几个接口”

如果你今天只是新增：

- `GET /tasks`
- `POST /retry`

但没有重构：

- 状态合法性
- 错误码语义
- 查询层次

那 Day 4 其实没有真正完成。

## 第 2 层：Day 4 不是一次把监控系统做得很重

今天你不一定要立刻接：

- Prometheus
- Grafana
- 分布式 tracing
- 告警平台

今天最关键的是：

- 日志字段统一
- 阶段耗时有数据
- 有最小指标容器

## 第 3 层：Day 4 不是所有状态都能任意取消和重试

今天你要非常明确：

- `queued / running / retrying` 才适合取消
- `failed / timeout / partial_success` 更适合重试

状态控制不是“接口存在就能调”。

## 第 4 层：Day 4 的查询必须分层

今天建议明确区分：

- `preview`
- `detail`
- `debug`

否则详情接口会越来越重，前后端也会越来越难对齐。

---

## 上午学习：09:00 - 12:00

## 09:00 - 09:50：先把平台主链路讲顺

今天你必须能顺着说出来：

```text
submit
-> list
-> inspect
-> cancel / retry
-> observe
-> diagnose
```

你今天必须能回答这两个问题：

1. 为什么 `409 Conflict` 很适合表达“状态不允许取消或重试”？
2. 为什么查询接口要有 preview / detail / debug 分层？

## 09:50 - 10:40：先决定 Day 4 最小接口集合

今天建议你至少明确这些接口：

- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/cancel`
- `POST /api/v1/tasks/{task_id}/retry`

这里最重要的是：

- 列表、控制、详情三种需求必须分开考虑

## 10:40 - 11:20：先决定最小观测字段

今天建议你至少统一这些日志字段：

- `task_id`
- `stage`
- `attempt_count`
- `provider`
- `duration_ms`
- `status_before`
- `status_after`
- `error_code`

这里最重要的是：

- 以后排障不是靠“猜”
- 而是靠一致字段把日志串起来

## 11:20 - 12:00：先决定今天怎么验收

Day 4 的最小验收目标：

- 平台已不止有提交和详情查询
- 状态控制有合法性判断
- 查询接口已经开始支持分层返回
- 日志和指标开始形成最小闭环

---

## 下午编码：14:00 - 18:00

## 14:00 - 14:40：先改 `crud/task_record_crud.py`

今天建议你先把持久化能力补齐，因为列表、取消、重试都会依赖它。

### `crud/task_record_crud.py` 练手骨架版

```python
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from models.task_record import TaskRecord


def build_task_query_filters(
    *,
    status: str | None,
    query: str | None,
) -> list[ColumnElement[bool]]:
    # 你要做的事：
    # 1. 支持按状态过滤
    # 2. 支持按 query 模糊搜索
    raise NotImplementedError


async def list_task_records(
    db: AsyncSession,
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[TaskRecord]:
    # 你要做的事：
    # 1. 组装 select 语句
    # 2. 应用过滤条件
    # 3. 应用排序、分页
    raise NotImplementedError
```

### `crud/task_record_crud.py` 参考答案

```python
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from models.task_record import TaskRecord


def build_task_query_filters(
    *,
    status: str | None,
    query: str | None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(TaskRecord.status == status)
    if query:
        filters.append(
            or_(
                TaskRecord.query.ilike(f"%{query}%"),
                TaskRecord.task_id.ilike(f"%{query}%"),
            )
        )
    return filters


async def list_task_records(
    db: AsyncSession,
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[TaskRecord]:
    stmt = (
        select(TaskRecord)
        .where(*build_task_query_filters(status=status, query=query))
        .order_by(desc(TaskRecord.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

## 14:40 - 15:30：新增 `utils/task_control_service.py`

今天很建议你把取消和重试的状态判断收口。

### `utils/task_control_service.py` 练手骨架版

```python
def can_cancel(status: str) -> bool:
    # 你要做的事：
    # 1. queued / running / retrying 可以取消
    # 2. 其他状态不允许取消
    raise NotImplementedError


def can_retry(status: str) -> bool:
    # 你要做的事：
    # 1. failed / timeout / partial_success 可以重试
    # 2. success 不允许重试
    raise NotImplementedError
```

### `utils/task_control_service.py` 参考答案

```python
def can_cancel(status: str) -> bool:
    return status in {"queued", "running", "retrying"}


def can_retry(status: str) -> bool:
    return status in {"failed", "timeout", "partial_success"}
```

## 15:30 - 16:20：改 `routers/task_router.py`

今天建议你把接口补成任务平台风格。

至少建议新增：

- `GET /tasks`
- `POST /tasks/{task_id}/cancel`
- `POST /tasks/{task_id}/retry`

同时建议 `GET /tasks/{task_id}` 支持：

- `include_detail`
- `include_debug`

这样你才能把：

- 预览层
- 完整结果层
- 调试层

分开返回。

## 16:20 - 17:00：统一日志上下文

今天你最应该做的不是多打几条日志，而是统一字段。

更工程化的写法是：

- 日志上下文类型也放在 `schemas/`

建议新增：

- `schemas/task_observability_schema.py`

### `schemas/task_observability_schema.py` 练手骨架版

```python
from pydantic import BaseModel


class TaskLogContext(BaseModel):
    # 你要做的事：
    # 1. 统一 task_id / stage
    # 2. 允许 attempt_count / provider / duration_ms / error_code 可选
    raise NotImplementedError
```

### `schemas/task_observability_schema.py` 参考答案

```python
from pydantic import BaseModel


class TaskLogContext(BaseModel):
    task_id: str
    stage: str
    attempt_count: int = 0
    provider: str = ""
    duration_ms: float | None = None
    error_code: str = ""
```

### `utils/metrics.py` / logging helper 练手骨架版

```python
from collections import defaultdict
from schemas.task_observability_schema import TaskLogContext


def build_task_log_context(
    task_id: str,
    stage: str,
    *,
    attempt_count: int = 0,
    provider: str = "",
    duration_ms: float | None = None,
    error_code: str = "",
) -> TaskLogContext:
    # 你要做的事：
    # 1. 固定 task_id / stage
    # 2. 允许带 attempt_count / provider / duration_ms
    raise NotImplementedError


def record_stage_latency(
    metrics: defaultdict[str, list[float]],
    stage: str,
    duration_ms: float,
) -> None:
    # 你要做的事：
    # 1. 记录阶段耗时
    # 2. 为后续指标接入留简单容器
    raise NotImplementedError
```

### `utils/metrics.py` / logging helper 参考答案

```python
from collections import defaultdict
from schemas.task_observability_schema import TaskLogContext


def build_task_log_context(
    task_id: str,
    stage: str,
    *,
    attempt_count: int = 0,
    provider: str = "",
    duration_ms: float | None = None,
    error_code: str = "",
) -> TaskLogContext:
    return TaskLogContext(
        task_id=task_id,
        stage=stage,
        attempt_count=attempt_count,
        provider=provider,
        duration_ms=duration_ms,
        error_code=error_code,
    )


def record_stage_latency(
    metrics: defaultdict[str, list[float]],
    stage: str,
    duration_ms: float,
) -> None:
    bucket = metrics.setdefault(stage, [])
    bucket.append(round(duration_ms, 2))
```

## 17:00 - 17:40：把 `conf/logging_conf.py` 和 `main.py` 的观测入口理顺

今天建议你至少做到：

- 请求入口有统一日志字段
- worker 执行有统一日志字段
- 异常处理能带上任务上下文

重点不是“日志很多”，而是：

- 日志能串起来

## 17:40 - 18:00：把 Day 4 的平台语义写回 README

今天很建议你顺手把这些补进 README：

- 新状态机说明
- 取消与重试语义
- 本地怎么启动 API / worker / Redis
- 查询接口怎么区分 preview / detail / debug

---

## 晚上复盘：20:00 - 21:00

今晚你必须自己讲顺的 8 个点：

1. 为什么任务系统不能只有提交和详情接口？
2. 为什么 `409 Conflict` 很适合状态不合法的控制接口？
3. 哪些状态允许取消，哪些允许重试？
4. 为什么详情查询要开始支持字段裁剪？
5. 为什么日志要围绕 `task_id` 串联？
6. 为什么指标最开始只要做到“足够排障”就可以？
7. Day 4 的平台能力和 Day 2 的执行能力有什么区别？
8. 如果结果质量突然下降，Day 4 的观测层应该先帮你看什么？

---

## 今日验收标准

- 已有任务列表能力
- 已有取消与重试的合法性规则
- 详情查询开始支持分层返回
- 日志字段开始统一
- 阶段耗时开始有最小记录
- README 或运维说明开始反映平台化语义

---

## 今天最容易踩的坑

### 坑 1：新增了接口，但没有状态合法性控制

问题：

- 接口有了，平台语义还是乱的

规避建议：

- 把取消和重试判定收口到控制服务

### 坑 2：详情接口越来越大，什么都往里塞

问题：

- 前后端都难维护

规避建议：

- 从 Day 4 开始就做分层返回

### 坑 3：日志只加 message，不加上下文字段

问题：

- 线上仍然很难排障

规避建议：

- 统一 `task_id / stage / attempt_count / provider`

### 坑 4：为了做观测，一上来就把系统做得很重

问题：

- 成本高，推进慢

规避建议：

- 先做最小可诊断闭环

---

## 给明天的交接提示

如果后面继续扩展，下一步优先考虑：

- provider aggregation
- 正文抓取增强
- 对象存储导出
- 更完整的指标与告警

所以 Day 4 的意义是：

> 先让这个项目像一个真正的任务平台，然后再继续把它做成更完整的可运维 Agent 系统。
