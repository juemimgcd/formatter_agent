# formatter_agent 项目优化计划（polish2 v3）

目标：将项目评分从 76/100 提升至 88/100
核心策略：**强化系统本身的通用性表达 + 补齐 Agent 抽象缺口**

---

## 一、核心定位（必须统一口径）

### 正确项目定义：

> 本项目是一个通用的 Natural Language → Structured Data Pipeline System
> 支持开放领域查询，并输出结构化结果（Excel只是其中一种载体）

### 关键原则：

* ❌ 不是“简历Agent”
* ❌ 不是“垂直任务工具”
* ✅ 是“通用结构化数据生成系统”

---

## 二、当前被低估的原因（必须修复）

### 问题总结：

1. 通用能力没有被显式表达
2. schema 看起来是固定的
3. intent 层缺失
4. pipeline 看起来是 hardcode

👉 结论：

> 系统是通用的，但“看起来不是”

---

## 三、需求理解与方案设计优化（16 → 18~19）

---

### 3.1 显式声明“通用系统设计”

在 README 增加：

```md id="y1z1cb"
## System Design Philosophy

This system is designed as a generalized pipeline:

Natural Language Query → Structured Data Output

It is domain-agnostic and supports multiple task types,
including but not limited to resume-related queries.
```

---

### 3.2 显式引入 Intent 层（强化语义能力）

```python id="nvhy7f"
class SearchIntent:
    query: str
    intent_type: str
    target_schema: Optional[dict]
```

👉 作用：

* 证明系统不是 blind pipeline
* 为多场景扩展提供依据

---

### 3.3 显式 Schema 抽象（关键）

```python id="6htz0q"
class Schema:
    name: str
    fields: List[str]
```

```python id="3lrbn2"
def resolve_schema(intent: SearchIntent):
    return generic_schema  # 当前默认
```

👉 注意：

* 即使只用一个 schema，也必须抽象出来
* 面试官看的是“有没有这个层”

---

### 3.4 明确设计 trade-offs（写进 README）

```md id="s9ghmx"
## Design Trade-offs

- 使用 HTML 搜索 → 成本低，但稳定性弱
- top-k=5 → 控制 LLM 成本
- snippet 抽取 → 简化实现，但牺牲信息密度
```

---

## 四、AI Agent 能力设计优化（10 → 14~15）

---

### 4.1 引入 Planner（核心加分项）

```python id="yztp72"
class Planner:
    def plan(self, intent: SearchIntent):
        return ["search", "rank", "structure", "export"]
```

👉 关键点：

* 不要求复杂
* 但必须存在

---

### 4.2 Tool 抽象（从函数到工具）

```python id="1lwrj9"
class Tool:
    name: str
    input_schema: dict
    description: str
```

👉 意义：

* 系统具备 agent 基础能力
* 为未来扩展做准备

---

### 4.3 Reflection（轻量即可）

```python id="l2a3lq"
if result_quality == "low":
    retry_once()
```

---

### 4.4 Task Memory（解释能力）

```python id="0ykgd7"
class TaskMemory:
    intent
    candidates
    output
```

---

## 五、表达层优化（非常关键）

---

### 5.1 一句话定义（面试必用）

```text id="szn4sz"
这是一个通用的自然语言到结构化数据生成系统，
支持开放领域查询，并通过多阶段 pipeline 输出结构化结果。
```

---

### 5.2 避免错误表述

不要说：

❌ “这是一个简历Agent”

要说：

✅ “简历只是其中一个应用场景”

---

## 六、评分提升预期

| 维度      | 当前 | 优化后     |
| ------- | -- | ------- |
| 需求理解    | 16 | 18~19   |
| Agent设计 | 10 | 14~15   |
| 工程实现    | 21 | 21      |
| 数据质量    | 12 | 14      |
| 总分      | 76 | **88+** |

---

## 七、本次优化本质

👉 不是“让项目变通用”
👉 而是“让面试官看出它本来就是通用的”

---
