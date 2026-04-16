# polish3：让项目更瘦，同时更像 Agent 的重构方案

## 1. 目标

当前项目的主要问题，不是功能不够，而是：

- 模块名很多，但真正承担决策职责的核心不够突出
- 主流程更像固定 pipeline，而不是状态驱动的 agent loop
- `intent / schema / planner / memory / quality / fallback` 这些概念层彼此分散，导致架构显得臃肿

这次重构的目标不是继续堆功能，而是做一次减法：

1. **收缩模块数量**
2. **把“决策”集中到一个地方**
3. **把“状态”收敛成一个统一对象**
4. **把主流程改造成真实的 Agent Loop**

最终要达到的效果是：

> 这个项目看起来不再像“很多步骤拼在一起的工作流”，而是一个围绕任务状态持续决策、执行、更新、停止的轻量 Agent。

---

## 2. 重构原则

### 原则一：State 比 Module 更重要

不要继续增加模块，而要增强统一状态对象。

真正让项目像 Agent 的，不是模块名，而是下面这个闭环是否成立：

```text
State -> Decide -> Act -> Update
```

只要这个闭环存在，系统即使很小，也会像 Agent。

---

### 原则二：把“智能”集中在 Policy

架构里只有一个地方需要承担决策：`Policy`。

其余组件应尽量简单：

- `ToolRunner` 只负责执行动作
- `Reducer` 只负责把 observation 写回 state
- `Finalizer` 只负责组织最终输出

避免每一层都带一点“智能”，否则系统会越来越胖。

---

### 原则三：Memory 不是独立系统，而是 State 的一部分

当前项目里的 memory 更适合作为 **task-scoped working memory**，而不是独立大模块。

因此不要再做一套庞杂的 memory abstraction，而是直接把以下内容收进 `AgentState`：

- action history
- evidence pool
- slot progress
- conflicts
- round count
- stop reason

---

### 原则四：Quality 不是报告，而是控制信号

如果 quality 只是最后展示给用户的一个字段，那它是装饰。

更合理的方式是：

- coverage 不足 -> 继续搜索
- evidence 冲突 -> 触发 verify
- required slots 已完成 -> 停止
- round budget 用尽 -> 降级输出

也就是说，quality 不应该是单独大模块，而应该变成 `Policy` 的输入之一。

---

## 3. 重构后的最小架构

建议把系统收缩成 6 个核心件：

### 3.1 TaskCompiler
职责：

- 解析用户 query
- 判断任务类型
- 生成目标 schema
- 初始化 state

输出：`AgentState`

它等价于把原来的：

- Intent Parser
- Schema Resolver

折叠成一次性编译动作。

---

### 3.2 AgentState
职责：

- 统一承载执行期状态
- 作为整个 agent loop 的唯一上下文对象

建议字段：

```python
from dataclasses import dataclass, field
from typing import Any, Literal

SlotStatus = Literal["missing", "partial", "filled", "conflict"]

@dataclass
class Evidence:
    field: str | None
    value: Any
    source: str
    confidence: float
    note: str = ""

@dataclass
class ActionTrace:
    round_idx: int
    action_type: str
    params: dict[str, Any]
    reason: str
    summary: str = ""

@dataclass
class AgentState:
    query: str
    task_type: str
    schema: dict[str, Any]
    slots: dict[str, SlotStatus]
    result: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    trace: list[ActionTrace] = field(default_factory=list)
    round_idx: int = 0
    max_rounds: int = 3
    done: bool = False
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
```

这个对象本身就已经替代了大部分“memory / quality / progress”子模块。

---

### 3.3 Policy
职责：

- 基于当前 state 决定下一步 action

接口：

```python
def decide_next_action(state: AgentState) -> dict[str, Any]:
    ...
```

可返回的动作先尽量少，只保留 4 类：

- `search`
- `targeted_search`
- `verify`
- `finalize`

示例：

```python
{"type": "search", "query": "OpenAI CEO official site"}
{"type": "targeted_search", "field": "release_date", "query": "GPT-4o release date"}
{"type": "verify", "field": "organization", "value": "OpenAI"}
{"type": "finalize"}
```

注意：

`Planner / Router / Fallback Selector / Quality Gate` 都可以先被折叠进这个 `Policy`。

---

### 3.4 ToolRunner
职责：

- 执行 action
- 返回 observation

接口：

```python
def run_action(action: dict[str, Any]) -> dict[str, Any]:
    ...
```

输出示例：

```python
{
    "type": "search_result",
    "items": [...],
    "summary": "found 5 candidates"
}
```

不要把它做得很聪明。
它只需要可靠执行，不要在这里塞策略判断。

---

### 3.5 Reducer
职责：

- 根据 observation 更新 state
- 更新 evidence、slots、warnings、done 标记

接口：

```python
def reduce_state(state: AgentState, action: dict[str, Any], observation: dict[str, Any]) -> AgentState:
    ...
```

这是整个系统“像状态机”的关键。

---

### 3.6 Finalizer
职责：

- 输出最终结构化答案
- 输出 trace / warnings / stop reason

它不应再做新的检索或策略行为，只做最终组织。

---

## 4. 重构后的主循环

建议把主流程改成如下形式：

```python
state = task_compiler.compile(query)

while not state.done and state.round_idx < state.max_rounds:
    action = policy.decide_next_action(state)
    observation = tool_runner.run_action(action)
    state = reducer.reduce_state(state, action, observation)
    state.round_idx += 1

return finalizer.build(state)
```

这个 loop 本身就是项目“更像 agent”的最直接证据。

因为这里已经包含：

- 明确的 state
- 基于 state 的决策
- 外部动作
- 动作后的反馈写回
- 显式终止条件

---

## 5. 从当前架构到新架构的折叠关系

### 当前概念层

可能接近下面这种结构：

- Intent Parser
- Schema Resolver
- Planner
- Search
- Rank
- Structure
- Memory
- Quality Check
- Fallback
- Export

### 折叠后

对应收缩成：

| 当前模块 | 折叠后归属 |
|---|---|
| Intent Parser | TaskCompiler |
| Schema Resolver | TaskCompiler |
| Planner | Policy |
| Router | Policy |
| Fallback Selector | Policy |
| Memory | AgentState |
| Quality Check | AgentState + Policy |
| Search / Fetch | ToolRunner |
| Structure | ToolRunner / Reducer |
| Export | Finalizer |

其中最关键的是：

- `Planner / Router / Fallback / Quality Gate` 合并进 `Policy`
- `Memory / Progress / Evidence` 合并进 `AgentState`

这一步一做，架构会立刻瘦很多。

---

## 6. 怎么保证“更瘦”但“不变傻”

很多重构会误伤能力。这里需要明确：

### 6.1 不删能力，只删中间名义层

不建议删除：

- 搜索能力
- 结构化抽取能力
- 导出能力
- fallback 能力

建议删除或折叠的是：

- 只是负责“命名”但不直接改变行为的模块
- 彼此高度重叠的控制层
- 不直接被 runtime 消费的 quality 报告层

---

### 6.2 用 Slots 代替大而全的工作流

与其保留一个长 pipeline，不如让 runtime 围绕 slot 缺口工作。

例如目标 schema：

```json
{
  "name": "",
  "organization": "",
  "release_date": "",
  "features": [],
  "source_urls": []
}
```

执行期的状态只关心：

```json
{
  "name": "filled",
  "organization": "filled",
  "release_date": "missing",
  "features": "partial",
  "source_urls": "filled"
}
```

然后由 `Policy` 决策：

- 下一步优先补哪个字段
- 哪个字段值得验证
- 哪些字段可以接受 partial
- 何时停止

这样比“先搜、再排、再抽、再导”的大流程更轻，也更像 Agent。

---

## 7. 一个建议中的极简动作集

为了控制膨胀，第一版只保留 4 个动作：

### 7.1 `search`
用于一般性检索。

```python
{"type": "search", "query": "Claude 3.7 release date"}
```

### 7.2 `targeted_search`
用于补充缺失字段。

```python
{"type": "targeted_search", "field": "pricing", "query": "Claude pricing official"}
```

### 7.3 `verify`
用于处理冲突或低置信度字段。

```python
{"type": "verify", "field": "organization", "value": "Anthropic"}
```

### 7.4 `finalize`
用于停止并组装结果。

```python
{"type": "finalize"}
```

动作越少，架构越稳。

---

## 8. Policy 的最小决策逻辑

第一版建议完全不要做复杂 Agent Planning，只做一个轻量规则 / LLM 混合策略。

伪代码：

```python
def decide_next_action(state: AgentState) -> dict[str, Any]:
    if required_slots_filled(state):
        return {"type": "finalize"}

    if has_conflict_slots(state):
        field = pick_conflict_slot(state)
        return {
            "type": "verify",
            "field": field,
            "value": state.result.get(field)
        }

    missing = highest_priority_missing_slot(state)
    if missing:
        return {
            "type": "targeted_search",
            "field": missing,
            "query": build_slot_query(state.query, missing)
        }

    return {"type": "search", "query": state.query}
```

这样做的优点：

- 决策逻辑集中
- 容易解释
- 便于后续替换成更复杂策略
- 不会一开始就把项目搞胖

---

## 9. Reducer 要承担什么

`Reducer` 不是简单 append 日志，而是整个状态闭环的关键。

它至少要做四件事：

### 9.1 写入 evidence

把每次搜索 / 抽取得到的候选事实写入 evidence pool。

### 9.2 更新 slot 状态

根据 observation 更新：

- `missing -> partial`
- `partial -> filled`
- `filled -> conflict`

### 9.3 更新 warnings

例如：

- source quality low
- value conflict
- evidence insufficient

### 9.4 决定是否 done

例如：

- required slots 全部 filled
- 已经达到 max_rounds
- fallback 已触发且无必要继续

---

## 10. 输出里要保留什么，才能体现 Agent 性

为了让这个项目对外更像 Agent，最终结果里建议保留一个很薄的执行轨迹。

例如：

```json
{
  "result": {...},
  "warnings": [...],
  "stop_reason": "required_slots_filled",
  "trace": [
    {
      "round_idx": 0,
      "action_type": "search",
      "reason": "initial evidence collection"
    },
    {
      "round_idx": 1,
      "action_type": "targeted_search",
      "reason": "release_date missing"
    },
    {
      "round_idx": 2,
      "action_type": "finalize",
      "reason": "minimum schema satisfied"
    }
  ]
}
```

这不只是调试信息，也是“Agent 性”的直接证明。

---

## 11. 推荐目录结构

建议重构后的目录尽量收缩：

```text
rebuild_agent/
├─ agent/
│  ├─ state.py          # AgentState / Evidence / ActionTrace
│  ├─ compiler.py       # TaskCompiler
│  ├─ policy.py         # decide_next_action
│  ├─ reducer.py        # reduce_state
│  ├─ runner.py         # Agent loop
│  └─ finalizer.py      # final output
├─ tools/
│  ├─ search.py
│  ├─ extract.py
│  ├─ verify.py
│  └─ tool_runner.py
├─ schemas/
│  └─ registry.py
├─ api/
│  └─ routes.py
└─ main.py
```

对比旧结构，原则是：

- 控制层集中到 `agent/`
- 外部动作集中到 `tools/`
- schema 单独留存
- 不再为“概念上好看”的层级额外建目录

---

## 12. 推荐迁移顺序

### 第一步：先合并控制层
先把：

- planner
- router
- fallback selector
- quality gate

合并到 `policy.py`。

目标不是优雅，而是先把“谁在做决策”变清楚。

---

### 第二步：把 memory、evidence、progress 合并进 state
建立统一 `AgentState`，把执行期上下文统一塞进去。

这一步会让 runtime 变得很清楚。

---

### 第三步：把主流程改成 loop
把固定 DAG 改成：

```python
compile -> loop(decide/act/update) -> finalize
```

这是最关键的一步。

---

### 第四步：压缩动作种类
不要保留太多 action type。先只保留 4 类动作，跑顺了再扩。

---

### 第五步：补 trace 输出
让每一轮 action 都留下理由和结果摘要，便于调试、展示和面试说明。

---

## 13. 一份最小可运行骨架

### `agent/runner.py`

```python
from agent.compiler import compile_task
from agent.policy import decide_next_action
from agent.reducer import reduce_state
from tools.tool_runner import run_action
from agent.finalizer import build_output


def run_agent(query: str):
    state = compile_task(query)

    while not state.done and state.round_idx < state.max_rounds:
        action = decide_next_action(state)
        observation = run_action(action)
        state = reduce_state(state, action, observation)
        state.round_idx += 1

    return build_output(state)
```

### `agent/policy.py`

```python
def decide_next_action(state):
    if state.done:
        return {"type": "finalize"}

    if all_required_slots_filled(state):
        return {"type": "finalize"}

    conflict_field = first_conflict_slot(state)
    if conflict_field:
        return {
            "type": "verify",
            "field": conflict_field,
            "value": state.result.get(conflict_field)
        }

    missing_field = first_missing_slot(state)
    if missing_field:
        return {
            "type": "targeted_search",
            "field": missing_field,
            "query": build_slot_query(state.query, missing_field)
        }

    return {"type": "search", "query": state.query}
```

### `agent/finalizer.py`

```python
def build_output(state):
    return {
        "result": state.result,
        "warnings": state.warnings,
        "stop_reason": state.stop_reason,
        "trace": [
            {
                "round_idx": t.round_idx,
                "action_type": t.action_type,
                "params": t.params,
                "reason": t.reason,
                "summary": t.summary,
            }
            for t in state.trace
        ],
    }
```

---

## 14. 这次重构之后，项目会发生什么变化

### 14.1 对内

- runtime 更清晰
- 控制权更集中
- 调试成本更低
- 新功能更容易插入 action 层，而不是继续扩模块层

### 14.2 对外

- 更容易解释“为什么它是 Agent”
- 更容易展示执行轨迹
- 更容易在 README / 面试里讲清楚架构
- 不再显得“模块很多但抓不住核心”

---

## 15. 最终结论

这个项目要同时做到“更瘦”和“更像 Agent”，最有效的办法不是继续增加能力模块，而是：

1. **把模块折叠成统一状态驱动模型**
2. **把所有控制逻辑集中进 Policy**
3. **把主流程改成显式 Agent Loop**
4. **把 Memory / Quality / Progress 都收进 AgentState**
5. **只保留极少数高价值动作类型**

一句话概括：

> 用更少的组件，换来更强的状态、更清晰的决策、更真实的 Agent 闭环。

