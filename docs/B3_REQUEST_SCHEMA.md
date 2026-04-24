# AgentOS B 线 — Typed Request Schema

**文档编号**: B3  
**版本**: 0.2  
**日期**: 2026-04-15  
**状态**: 对齐新版本设计

---

## 1. 概述

B 线不再允许 agent 输出任意 shell 风格字符串请求。

所有工具调用必须使用**结构化 JSON request**，经过 VTRM 验证后才能执行。

**核心原则**：LLM 输出的 JSON 只是**候选动作描述**，不是正式、可信、可执行的请求对象。

---

## 2. 请求模型分层

### Layer 1: LLM Output（不可信）
LLM 输出的 JSON，视为候选请求。

### Layer 2: NormalizedRequest（可信）
经过以下处理后的正式请求：
1. parse
2. schema validation
3. runtime metadata injection（`task_id`, `request_id`, `subject`）
4. object classification（`target_object_class`, `sink_class`）
5. capability derivation（`required_capability`）
6. label derivation / propagation（`inferred_conf_label`）

---

## 3. LLM Output Schema（候选请求）

```json
{
  "schema_version": "0.1",
  "tool": "fs.write",
  "args": {
    "path": "/workspace/out.txt",
    "content": "hello"
  },
  "content_label": "public",
  "capability_required": "fs.write.workspace"
}
```

**注意**：`content_label` 和 `capability_required` 仅作为建议，最终值由系统推导。

---

## 4. NormalizedRequest（正式请求）

真正进入 VTRM 语义的对象：

```text
NormalizedRequest = {
  task_id,                    // runtime 注入，可信
  request_id,                 // runtime 生成，可信
  subject,                    // runtime 确定，可信
  tool,
  args,
  target_object_class?,       // classifier 推导
  source_object_classes?,     // classifier 推导
  sink_class?,                // classifier 推导
  required_capability,        // 系统推导，不信模型自报
  inferred_conf_label,        // 系统推导，不信模型自报
}
```

---

## 5. Request Schema（高层 JSON）

```json
{
  "schema_version": "0.1",
  "task_id": "task-20260414-001",
  "request_id": "req-001",
  "subject": "agent-default",
  "tool": "fs.write",
  "args": { ... },
  "content_label": "public",
  "capability_required": "fs.write.workspace"
}
```

---

## 6. 字段详细说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `schema_version` | string | ✓ | Schema 版本号（用于兼容性管理） |
| `task_id` | string | ✓ | 所属任务 ID（runtime 注入） |
| `request_id` | string | ✓ | 请求唯一 ID（runtime 生成） |
| `subject` | string | ✓ | 执行主体标识（如 `agent-default`） |
| `tool` | string | ✓ | 工具类型（见下文枚举） |
| `args` | object | ✓ | 工具参数（schema 因工具而异） |
| `content_label` | string | ✓ | 数据敏感度标签建议（`public` \| `secret/high`） |
| `capability_required` | string | ✓ | 需要的 capability 建议 |

**关键**：以下字段由 runtime 注入或系统推导，不信任模型自报：
- `task_id`
- `request_id`
- `subject`
- `required_capability`（由 Capability Deriver 推导）
- `inferred_conf_label`（由 Label Engine 推导）

---

## 7. 工具类型与 Args Schema

### 7.1 fs.read

读取文件内容。

```json
{
  "schema_version": "0.1",
  "tool": "fs.read",
  "args": {
    "path": "/workspace/config.json"
  },
  "content_label": "public",
  "capability_required": "fs.read"
}
```

| args 字段 | 类型 | 说明 |
|-----------|------|------|
| `path` | string | 绝对路径（必须 canonicalize） |

**target_object_class**：由 `path_classifier.classify()` 推导  
**inferred_conf_label**：若 `target_object_class = secret_source` 则为 `secret/high`，否则继承 `content_label`

**world-state effect**: `ReadOnly`

---

### 7.2 fs.write

写入文件内容。

```json
{
  "schema_version": "0.1",
  "tool": "fs.write",
  "args": {
    "path": "/workspace/result.txt",
    "content": "hello world"
  },
  "content_label": "public",
  "capability_required": "fs.write.workspace"
}
```

| args 字段 | 类型 | 说明 |
|-----------|------|------|
| `path` | string | 绝对路径（必须 canonicalize） |
| `content` | string | 写入内容（纯文本） |

**target_object_class**：由 `path_classifier.classify()` 推导  
**required_capability**：由 `capability_deriver.derive(req)` 推导  
**inferred_conf_label**：继承 `content_label`

**world-state effect**: `MutateFS`

**security note**：若 `target_object_class = protected` 则 deny

---

### 7.3 network.send

发送网络请求。

```json
{
  "schema_version": "0.1",
  "tool": "network.send",
  "args": {
    "url": "https://api.example.com/data",
    "method": "GET",
    "body": null,
    "headers": {}
  },
  "content_label": "public",
  "capability_required": "network.send.external"
}
```

| args 字段 | 类型 | 说明 |
|-----------|------|------|
| `url` | string | 目标 URL（必须 canonicalize） |
| `method` | string | HTTP 方法（`GET` \| `POST` \| `PUT` \| `DELETE`） |
| `body` | string \| null | 请求体（可选） |
| `headers` | object | HTTP 头部（可选） |

**sink_class**：由 `sink_classifier.classify()` 推导（`trusted_internal` 或 `external_untrusted`）  
**required_capability**：由 `capability_deriver.derive(req)` 推导  
**inferred_conf_label**：继承 `content_label`

**world-state effect**: `SendExternal`

**security note**：
- 若 `inferred_conf_label = secret/high` 且 `sink_class = external_untrusted` 则 deny
- 这是核心 non-exfiltration 保障

---

### 7.4 db.read

读取数据库记录（按主键）。

```json
{
  "schema_version": "0.1",
  "tool": "db.read",
  "args": {
    "table": "tasks",
    "key": "task-001"
  },
  "content_label": "public",
  "capability_required": "db.read.tasks"
}
```

| args 字段 | 类型 | 说明 |
|-----------|------|------|
| `table` | string | 表名 |
| `key` | string | 主键值 |

**target_object_class**：由 `db_classifier.classify_table()` 推导  
**inferred_conf_label**：若 `target_object_class = secret_table` 则为 `secret/high`

**world-state effect**: `ReadOnly`

---

### 7.5 db.insert

插入数据库记录。

```json
{
  "schema_version": "0.1",
  "tool": "db.insert",
  "args": {
    "table": "results",
    "row": {
      "task_id": "task-001",
      "status": "success",
      "output": "done"
    }
  },
  "content_label": "public",
  "capability_required": "db.insert.results"
}
```

| args 字段 | 类型 | 说明 |
|-----------|------|------|
| `table` | string | 表名 |
| `row` | object | 整行数据（键值对） |

**target_object_class**：由 `db_classifier.classify_table()` 推导  
**required_capability**：由 `capability_deriver.derive(req)` 推导

**world-state effect**: `MutateDB`

**security note**：若 `target_object_class = readonly_table` 或 `audit_table` 则 deny

---

### 7.6 db.update

更新数据库记录（部分字段）。

```json
{
  "schema_version": "0.1",
  "tool": "db.update",
  "args": {
    "table": "tasks",
    "key": "task-001",
    "patch": {
      "status": "running"
    }
  },
  "content_label": "public",
  "capability_required": "db.update.tasks"
}
```

| args 字段 | 类型 | 说明 |
|-----------|------|------|
| `table` | string | 表名 |
| `key` | string | 主键值 |
| `patch` | object | 需要更新的字段（键值对） |

**target_object_class**：由 `db_classifier.classify_table()` 推导  
**required_capability**：由 `capability_deriver.derive(req)` 推导

**world-state effect**: `MutateDB`

**security note**：若 `target_object_class = readonly_table` 或 `audit_table` 则 deny

---

## 8. Object Classification 规则

### 8.1 文件路径分类

| 路径模式 | Object Class | 语义 |
|----------|--------------|------|
| `/protected/**` | `protected` | 默认不可写 |
| `/workspace/**` | `workspace_writable` | 按 capability 写 |
| `/secrets/**` | `secret_source` | 读取结果带 `secret/high` |
| `/var/log/sandbox/vtrm/**` | `audit_log` | 仅 monitor 可写 |
| `/var/log/sandbox/trace/**` | `audit_log` | 仅 monitor 可写 |
| `/var/lib/agentos/*.db` | `db_file` | 不直接访问 |
| 其他 | `unknown` | 默认 deny |

**关键**：分类前必须 canonicalize（绝对路径检查、normalize、symlink resolution）

---

### 8.2 网络 Sink 分类

| URL 模式 | Sink Class | 语义 |
|----------|------------|------|
| `https://api.internal.example.com/**` | `trusted_internal` | 受信任内部 sink |
| 其他 | `external_untrusted` | 外部不可信 sink |

---

### 8.3 数据库表分类

| 表名模式 | Table Class | 语义 |
|----------|-------------|------|
| `secrets` / `credentials` | `secret_table` | 读取结果带 `secret/high` |
| `audit*` | `audit_table` | 仅 monitor 可 append |
| 系统只读表 | `readonly_table` | agent 不可写 |
| 其他 | `mutable_table` | 按 capability 更新 |

---

## 9. Content Label 定义

| 标签值 | 说明 |
|--------|------|
| `public` | 公开数据，可自由外发 |
| `secret/high` | 敏感数据，禁止发送到 `external_untrusted` |

**Label Join 规则**：

```text
join(public, public) = public
join(public, secret/high) = secret/high
join(secret/high, public) = secret/high
join(secret/high, secret/high) = secret/high
```

**传播规则**：
1. 从 `secret_source` 类文件读取 → `secret/high`
2. 从 `secret_table` 读取 → `secret/high`
3. Join 规则：只要结果依赖任一 `secret/high` 输入，输出就是 `secret/high`
4. 写入时，`inferred_conf_label` 继承自请求的 `content_label`
5. 网络发送时，VTRM 检查 `inferred_conf_label` + `sink_class`

---

## 10. Capability 命名规范

`<tool>.<action>.<resource>`

**示例**：

| Capability | 说明 |
|------------|------|
| `fs.read` | 读任意文件 |
| `fs.write.workspace` | 写 `/workspace/**` |
| `fs.write.protected` | 写 `/protected/**`（高权限） |
| `network.send.external` | 发送到任意外部地址 |
| `network.send.trusted_internal` | 发送到受信任内部地址 |
| `db.read` | 读任意表 |
| `db.read.secret` | 读 `secret_table` |
| `db.insert.mutable` | 插入到 `mutable_table` |
| `db.update.mutable` | 更新 `mutable_table` |
| `audit.append` | 添加审计日志 |

---

## 11. Response Schema

VTRM 返回的决策结果：

```json
{
  "request_id": "req-001",
  "task_id": "task-001",
  "decision": "allow" | "deny" | "transform",
  "effect": "ReadOnly" | "MutateFS" | "MutateDB" | "SendExternal",
  "reason": "string",
  "timestamp": "2026-04-14T10:30:00Z",
  "audit_logged": true,
  "transformed_request": { ... }  // 仅当 decision=transform 时出现
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | string | 请求 ID |
| `task_id` | string | 任务 ID |
| `decision` | string | `allow` / `deny` / `transform` |
| `effect` | string | `ReadOnly` / `MutateFS` / `MutateDB` / `SendExternal` |
| `reason` | string | 决策原因（deny 时必须提供） |
| `timestamp` | string | ISO 8601 时间戳 |
| `audit_logged` | boolean | 是否已记录审计日志 |
| `transformed_request` | object | 仅 transform 时 |

---

## 12. Audit Event Schema

```json
{
  "event_id": "ev-001",
  "request_id": "req-001",
  "task_id": "task-001",
  "subject": "agent-default",
  "tool": "fs.write",
  "args": { ... },
  "decision": "allow",
  "effect": "MutateFS",
  "reason": "capability check passed",
  "target_object_class": "workspace_writable",
  "inferred_conf_label": "public",
  "timestamp": "2026-04-14T10:30:00Z",
  "world_state_before": { ... },
  "world_state_after": { ... }
}
```

---

## 13. 与现有系统的映射

### 13.1 agent_runner 需要做的转换

**当前状态**：agent_runner 接收 LLM 输出（任意 JSON），直接调用 wrapper。

**B 线修改后**：
1. LLM 输出必须是 typed request（按 schema 验证）
2. 构建 `NormalizedRequest` 对象（runtime injection + derivation）
3. 发送给 VTRM 进行验证
4. 根据 VTRM decision 执行或拒绝
5. 生成 audit event

### 13.2 wrapper 需要做的修改

**当前状态**：wrapper 自己进行 policy check。

**B 线修改后**：
1. 移除 wrapper 内部的独立 policy 逻辑
2. wrapper 只作为纯执行后端
3. 接受来自 VTRM 的明确指令（allow/deny 已由 VTRM 决策）
4. 记录操作结果（供 audit 使用）
5. **严格无副作用 on error**

---

## 14. 安全性考虑

### 14.1 禁止任意 SQL

**错误设计**：
```json
{ "tool": "db.exec", "args": { "sql": "DELETE FROM users" } }
```

**正确设计**：
```json
{ "tool": "db.update", "args": { "table": "tasks", "key": "...", "patch": {...} } }
```

### 14.2 路径类型化

**错误设计**：直接把路径当 string，不做分类。

**正确设计**：
- `path_classifier.classify(path)` 返回 `PathType` 枚举
- `canonicalize_path(path)` 先规范化路径
- policy 基于 `object_class` 决策

### 14.3 标签传播一致性

VTRM 必须确保 secret 标签的传播是确定性的：
- 从 `/secrets/secret.json` 读取 → `secret/high`
- 从 `secrets` 表读取 → `secret/high`
- 写入 `/workspace/derived.json` 时，若内容源自 secret source → 标记为 `secret/high`
- 网络发送时检查 `inferred_conf_label` + `sink_class`

### 14.4 runtime metadata vs model metadata

**以 runtime 为准**：
- `task_id`
- `request_id`
- `subject`

**不能信模型自报**：
- `capability_required`
- `content_label`

---

## 15. Schema 版本管理

Request Schema 版本通过 `schema_version` 字段管理：

```json
{
  "schema_version": "0.1",
  ...
}
```

向后兼容策略：
- minor version 增加：添加可选的 args 字段
- major version 增加：结构性变更，需 VTRM 升级

---

## 16. Proof-Friendly 设计理由

使用 typed request 而非任意 shell/SQL 的原因：

| 设计 | 可验证性 |
|------|----------|
| Typed request | ✅ 参数类型确定，易于建模 state transition |
| Path classification | ✅ 路径类型有限，易于枚举 invariant |
| Sink classification | ✅ sink 类型有限，易于枚举 |
| Label propagation | ✅ 标签传播函数可定义，易于推理 |
| Typed DB ops | ✅ 操作语义确定，可形式化描述 |
| Arbitrary shell | ❌ 语义无限，无法穷尽验证 |
| Arbitrary SQL | ❌ 查询任意，难以保证安全属性 |

---

## 17. 实施检查清单

- [ ] 定义 JSON Schema 文件（`tool_request_schema.json`）
- [ ] agent_runner 拒绝非 schema 验证的请求
- [ ] 实现 Request Normalizer（Layer 1）
- [ ] 实现 Path Classifier（含 canonicalize）
- [ ] 实现 Sink Classifier
- [ ] 实现 DB Classifier
- [ ] 实现 Capability Deriver
- [ ] 实现 Label Engine
- [ ] VTRM 实现 schema 验证 + derivation + decision
- [ ] wrapper backend 改为纯执行模式
- [ ] 审计日志字段统一
- [ ] 测试：deny = no side effect
- [ ] 测试：secret non-exfiltration

---

## 引用文档

- [B1_SYSTEM_BOUNDARY.md](./B1_SYSTEM_BOUNDARY.md) — 系统边界与分层架构
- [B2_INVARIANTS.md](./B2_INVARIANTS.md) — 不变量与 Theorems
- [B4_ASSUMPTIONS.md](./B4_ASSUMPTIONS.md) — 假设清单
- `tool_request_schema.json` — JSON Schema 实现
- [OBJECT_MODEL_AND_LABELS.md](../agentos_top_level_design_docs/OBJECT_MODEL_AND_LABELS.md) — 对象模型与标签
