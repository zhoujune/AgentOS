# AgentOS B 线 — Invariants（状态不变量）与 Theorems

**文档编号**: B2  
**版本**: 0.2  
**日期**: 2026-04-15  
**状态**: 对齐新版本设计，新增 Theorems

---

## 1. Invariants 与 Theorems 概述

B 线的目标是证明：

> **VTRM 的状态转移保持一组关键不变量，从而使高风险副作用在结构上不可达。**

本文档定义：
- **Invariants**：系统正常执行时必须始终保持为真的属性
- **Theorems**：基于状态转移函数 `step` 的形式化定理

---

## 2. 抽象状态模型（第一版）

建议从下面这个极简状态出发进行证明：

```text
State = {
  fs_objects   : Path -> FileObj,
  db_objects   : DBKey -> DBObj,
  caps         : Subject -> CapabilitySet,
  audit_log    : list AuditEvent
}
```

其中：

```text
FileObj = {
  object_class : FileClass,    // protected / workspace_writable / readonly / secret_source / audit_log / unknown
  conf_label   : Label,        // public / secret/high
  content      : Bytes
}

DBObj = {
  object_class : DBClass,      // readonly_table / mutable_table / audit_table / secret_table
  conf_label   : Label,
  value        : Value
}

FileClass ∈ {protected, workspace_writable, readonly, secret_source, audit_log, unknown}
DBClass ∈ {readonly_table, mutable_table, audit_table, secret_table}
Label ∈ {public, secret/high}
```

---

## 3. 规范化请求模型

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

**关键原则**：`capability_required` 和 `content_label` 不能信任模型自报，必须由系统推导。

---

## 4. 状态转移函数

```text
step : State × NormalizedRequest -> Decision × State'
```

其中：
- `Decision ∈ {Allow, Deny, Transform}`
- `State'` 是转移后的新状态
- `WorldEffect ∈ {ReadOnly, MutateFS, MutateDB, SendExternal}`

---

## 5. VTRM 核心 Invariants

### INV-VTRM-1: Fail-Closed

**陈述**：任何未通过 VTRM 验证的请求不得产生真实副作用。

**形式化描述**：
```text
∀ req: NormalizedRequest
  if step(s, req).decision = Deny
  then world_state_unchanged(s, s')
```

**工程验证方法**：
- 审计日志检查：所有 `decision=deny` 的请求，`world_effect` 必须为 `None`
- 代码审查：`vtrm_core.py` 中 deny 路径不调用任何执行函数
- 测试：注入非法请求，验证文件系统 / DB / 网络未变更

**违反后果**：agent 可能绕过 VTRM 直接产生副作用。

---

### INV-VTRM-2: Capability Monotonicity

**陈述**：agent 的 capability 在运行时不能通过 tool output 自动增长。

**形式化描述**：
```text
∀ req: NormalizedRequest
  if step(s, req) = (_, s')
  and not is_trusted_delegation(req)
  then caps(s')[subject] ⊆ caps(s)[subject]
```

其中 `caps` 是 capability 集合映射。

**工程验证方法**：
- capability 集合在 agent 生命周期内不可变（除非显式 delegation）
- 审计日志记录 capability 授予事件
- 测试：执行任意请求后检查 capability 未增长

**违反后果**：agent 可能通过工具调用逐步提升权限。

---

### INV-VTRM-3: Audit Completeness

**陈述**：每个请求（无论 allow 还是 deny）都必须有对应审计日志。

**形式化描述**：
```text
∀ req: NormalizedRequest
  ∃ log: AuditLog
    log.request_id = req.request_id
    and log.task_id = req.task_id
    and log.decision ∈ {Allow, Deny}
```

**工程验证方法**：
- 审计日志条数 ≥ 请求数
- 每个 `request_id` 在日志中有记录
- 测试：发送请求后检查 audit log 存在

**违反后果**：无法追踪系统行为，无法验证其他 invariants。

---

## 6. 文件系统 Invariants

### INV-FS-1: Protected-Path Integrity

**陈述**：没有明确 `fs.write.protected` capability 的主体，不能成功修改 `protected` 类对象。

**形式化描述**：
```text
∀ req: NormalizedRequest
  if req.tool = "fs.write"
  and req.target_object_class = protected
  then req.decision = Deny
```

或等价地：

```text
If
  step(s, req) = (Allow, s')
  and req.tool = fs.write
  and fs_objects(s)[path].object_class = protected
  and fs_objects(s)[path].content ≠ fs_objects(s')[path].content
then
  has_cap(req.subject, fs.write.protected)
```

**工程验证方法**：
- 审计日志检查：所有对 `protected` 对象的 `fs.write` 请求，`decision` 必须为 `deny`
- `path_classifier.classify()` 正确将 `/protected/**` 分类为 `protected`
- 测试：无 capability 时对 protected path 的写请求被拒绝

**违反后果**：敏感数据被篡改或泄露。

---

### INV-FS-2: Workspace Write Control

**陈述**：对 `workspace_writable` 类对象的写操作必须有对应 `fs.write.workspace` capability。

**形式化描述**：
```text
∀ req
  if req.tool = "fs.write"
  and req.target_object_class = workspace_writable
  then req.required_capability = fs.write.workspace
  and has_cap(req.subject, fs.write.workspace)
```

**工程验证方法**：
- `CapabilityRegistry.check()` 验证 `fs.write.workspace` capability
- 审计日志显示 capability 检查失败时 deny

---

### INV-FS-3: Deny = No FS Change

**陈述**：所有 `decision=deny` 的请求不产生文件系统变更。

**形式化描述**：
```text
∀ req
  if step(s, req).decision = Deny
  then fs_objects(s') = fs_objects(s)
```

**工程验证方法**：
- 在测试环境中注入不合法的 fs 请求，验证文件系统未变更
- 审计日志 `world_effect` 必须为 `None`

**违反后果**：deny 可能被绕过，导致状态泄露。

---

## 7. 网络 Invariants

### INV-NET-1: Secret Non-Exfiltration（核心）

**陈述**：带 `secret/high` 标签的数据不能成功发送到 `external_untrusted` sink。

**形式化描述**：
```text
∀ req: NormalizedRequest
  if req.tool = "network.send"
  and req.inferred_conf_label = secret/high
  and req.sink_class = external_untrusted
  then req.decision = Deny
```

**定理 T2（No Secret to Unauthorized Sink）**：

```text
If
  step(s, req) = (Allow, s')
  and req.tool = network.send
  and req.sink_class = external_untrusted
  and network_send_happened(s, s')
then
  req.inferred_conf_label ≠ secret/high
```

**工程验证方法**：
- `NetworkPolicy.check()` 对 `secret/high` 标签检查 URL 白名单
- 审计日志记录所有被 deny 的 secret 外发尝试
- 测试：标记为 secret 的数据无法发送到外部 URL

**违反后果**：敏感数据外泄。

---

### INV-NET-2: Public Data Freedom

**陈述**：`public` 标签数据可以发送到任意地址（受 capability 限制）。

**形式化描述**：
```text
∀ req
  if req.tool = "network.send"
  and req.inferred_conf_label = public
  and has_cap(req.subject, network.send.external)
  and req.sink_class = external_untrusted
  then req.decision = Allow
```

---

### INV-NET-3: Label Consistency

**陈述**：从 `secret_source` 类对象读取的数据，其 `inferred_conf_label` 必须为 `secret/high`。

**形式化描述**：
```text
∀ req
  if req.tool = "fs.read"
  and req.target_object_class = secret_source
  then req.inferred_conf_label = secret/high
```

**工程验证方法**：
- `path_classifier.classify()` 对 `/secrets/**` 返回 `secret_source`
- `label_model.infer_from_object_class()` 返回 `secret/high`
- 审计日志检查 secret source 读取的 label 设置

---

## 8. 数据库 Invariants

### INV-DB-1: Typed Operations Only

**陈述**：数据库操作必须通过 typed 接口（`db.read`/`db.insert`/`db.update`），不允许 `exec_sql(sql_string)`。

**形式化描述**：
```text
∀ req: NormalizedRequest
  if req.tool.startswith("db.")
  then req.tool ∈ {db.read, db.insert, db.update}
```

**工程验证方法**：
- JSON Schema 限制 `tool` 字段的枚举值
- `sqlite_wrapper.sh` 禁用 `exec`/`query` 子命令
- 测试：尝试使用 db.exec 应被拒绝

**违反后果**：agent 可能执行任意 SQL，导致数据破坏或泄露。

---

### INV-DB-2: Primary Key Access Only

**陈述**：`db.read` 操作只能按主键读取，不支持任意 WHERE 条件。

**形式化描述**：
```text
∀ req
  if req.tool = "db.read"
  then "table" ∈ req.args
  and "key" ∈ req.args
  and no arbitrary WHERE clause
```

**工程验证方法**：
- `db_ops.py` 中 `read()` 方法只接受 `table` 和 `key` 参数
- SQL 生成不暴露给 agent

---

### INV-DB-3: Secret Table Detection

**陈述**：对 `secret_table` 类对象的读操作，返回数据必须标记为 `secret/high`。

**形式化描述**：
```text
∀ req, result: DBResult
  if req.tool = "db.read"
  and req.target_object_class = secret_table
  then result.conf_label = secret/high
```

**工程验证方法**：
- `DBClassifier.classify_table()` 正确识别 secret 表
- `db.read` 返回的 `LabeledData` 带有 `secret/high` 标签
- 测试：从 secrets 表读取应得到 secret/high 标签

---

## 9. 审计日志 Invariants

### INV-LOG-1: Logged Mutation

**陈述**：每一次成功的 world-state mutation，都必须有对应审计事件。

**形式化描述**：
```text
∀ req
  if step(s, req) = (Allow, s')
  and req.world_effect ∈ {MutateFS, MutateDB, SendExternal}
  then ∃ audit_log in s'.audit_log with same request_id
```

**定理 T3（Mutation Implies Audit）**：

```text
If
  step(s, req) = (Allow, s')
  and world_state_mutated(s, s')
then
  exists ev in audit_log(s') such that matches(ev, req, s, s')
```

**工程验证方法**：
- 审计日志与实际文件系统/数据库状态交叉验证
- `audit_logger.py` 在 `log_request()` 中正确记录 `world_effect`
- 测试：成功 mutation 后 audit log 包含对应事件

---

### INV-LOG-2: Deny Logging

**陈述**：所有 deny 必须记录到 `vtrm_deny.jsonl`。

**形式化描述**：
```text
∀ req
  if step(s, req).decision = Deny
  then ∃ entry in /var/log/sandbox/vtrm/vtrm_deny.jsonl
    with same request_id
```

**工程验证方法**：
- 定期检查 deny log 存在性和完整性
- 审计日志模块测试

---

## 10. Wrapper Backend Invariants

### INV-WRAP-1: No Independent Policy

**陈述**：wrapper backend 不能独立做 policy 决策。

**形式化描述**：
```text
∀ wrapper: Wrapper
  wrapper.execute() 只执行已批准操作
  wrapper 不包含 allow/deny 逻辑
```

**工程验证方法**：
- 代码审查：`fs_wrapper.sh`、`network_wrapper.sh`、`sqlite_wrapper.sh` 中不含 policy check
- wrapper 只接受 `execute` 子命令
- 测试：直接调用 wrapper 应执行但无 policy 保护

**违反后果**：VTRM 和 wrapper 可能有冲突的 policy，导致行为不一致。

---

### INV-WRAP-2: No Side Effects on Error

**陈述**：wrapper 出错时不产生状态变更。

**形式化描述**：
```text
∀ wrapper: Wrapper
  if wrapper.execute() fails
  then fs_objects_after = fs_objects_before
  and db_objects_after = db_objects_before
  and no_network_sent
```

**工程验证方法**：
- wrapper 测试：错误路径验证无状态变更
- 模拟 wrapper 执行失败，检查 world-state 未变

---

## 11. 第一批核心 Theorems

### Theorem T1: Protected Path Safety

**非正式表述**：
> 若某次状态转移后，某个 `protected` 文件的内容发生改变，则发起该请求的主体必然拥有允许修改该 protected 对象的 capability。

**形式化结构**：
```text
If
  step(s, req) = (Allow, s')
  and fs_objects(s)[p].object_class = protected
  and fs_objects(s)[p].content ≠ fs_objects(s')[p].content
then
  has_cap(req.subject, fs.write.protected)
```

**依赖的 Invariants**：INV-FS-1, INV-FS-3

---

### Theorem T2: No Secret to Unauthorized Sink

**非正式表述**：
> 若某次 `network.send` 成功发送到 `external_untrusted`，则发送数据的标签不能是 `secret/high`。

**形式化结构**：
```text
If
  step(s, req) = (Allow, s')
  and req.tool = network.send
  and req.sink_class = external_untrusted
  and network_send_happened(s, s')
then
  req.inferred_conf_label ≠ secret/high
```

**依赖的 Invariants**：INV-NET-1, INV-NET-3

---

### Theorem T3: Mutation Implies Audit

**非正式表述**：
> 任何成功 mutation 都必然对应一条审计事件。

**形式化结构**：
```text
If
  step(s, req) = (Allow, s')
  and world_state_mutated(s, s')
then
  ∃ ev ∈ audit_log(s') : matches(ev, req, s, s')
```

**依赖的 Invariants**：INV-LOG-1

---

### Theorem T4: Deny Has No Side Effect

**非正式表述**：
> 任意 deny 转移都不会改变 world-state 的 mutation 部分。

**形式化结构**：
```text
If
  step(s, req).decision = Deny
then
  fs_objects(s') = fs_objects(s)
  ∧ db_objects(s') = db_objects(s)
  ∧ no_network_effect(s, s')
```

**依赖的 Invariants**：INV-VTRM-1, INV-FS-3, INV-WRAP-2

---

### Theorem T5: Capability Monotonicity

**非正式表述**：
> 普通请求执行不会增加主体 capability 集。

**形式化结构**：
```text
If
  step(s, req) = (_, s')
  and ¬is_trusted_delegation(req)
then
  caps(s')[req.subject] ⊆ caps(s)[req.subject]
```

注：若 capability 完全不动态变化，则可简化为相等。

**依赖的 Invariants**：INV-VTRM-2

---

## 12. 证明��序建议

### Phase 1
- T4 Deny Has No Side Effect
- T1 Protected Path Safety

### Phase 2
- T3 Mutation Implies Audit

### Phase 3
- T5 Capability Monotonicity

### Phase 4
- T2 No Secret to Unauthorized Sink

理由：`fs` 最容易，`audit` 次之，`capability monotonicity` 需要元数据语义稳定，`network non-exfiltration` 需要 label propagation 先清楚。

---

## 13. 证明风格建议

三层规范：

### Layer A：Abstract Spec
只定义：
- 状态
- 操作
- 不变量

### Layer B：Executable Spec
定义：
- monitor 决策逻辑
- capability / label / class derivation 的可执行版本

### Layer C：Implementation-facing Model
定义：
- Python / Rust monitor core 与 spec 对齐的接口层

第一篇不必直接做到代码级 refinement。
先做到：
- abstract invariants
- executable monitor semantics
- 关键 theorem 的 machine-checked proof

就已经很强。

---

## 14. 验证优先级

| Invariant / Theorem | 优先级 | 备注 |
|---------------------|--------|------|
| INV-VTRM-1 (Fail-Closed) | P0 | 最核心 |
| INV-FS-1 (Protected-Path) | P0 | 核心安全属性 |
| INV-NET-1 (Secret Non-Exfil) | P0 | 核心安全属性 |
| T4 (Deny No Side Effect) | P0 | 基础性质 |
| INV-VTRM-3 (Audit Completeness) | P1 | 可验证性基础 |
| INV-DB-1 (Typed Ops Only) | P1 | 防止 SQL 注入 |
| T1 (Protected Path Safety) | P1 | 完整性定理 |
| T3 (Mutation Implies Audit) | P1 | 审计完整性 |
| INV-WRAP-1 (No Independent Policy) | P1 | 架构一致性 |

---

## 15. Proof Checklist

��新增一个 tool / object class，都问 5 个问题：

1. 它会产生什么真实副作用？
2. 它的目标对象属于什么 class？
3. 它读取的数据带什么 label？
4. 它需要什么 capability？
5. deny 时如何保证无副作用？

如果这 5 个问题答不清楚，就不要让它进入 verified core。

---

## 16. 文档引用

- [B1_SYSTEM_BOUNDARY.md](./B1_SYSTEM_BOUNDARY.md) — 系统边界与分层架构
- [B3_REQUEST_SCHEMA.md](./B3_REQUEST_SCHEMA.md) — 请求 Schema
- [B4_ASSUMPTIONS.md](./B4_ASSUMPTIONS.md) — 假设清单
- [TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md](../agentos_top_level_design_docs/TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md)
- [OBJECT_MODEL_AND_LABELS.md](../agentos_top_level_design_docs/OBJECT_MODEL_AND_LABELS.md)
- [INVARIANTS_THEOREMS_AND_PROOF_PLAN.md](../agentos_top_level_design_docs/INVARIANTS_THEOREMS_AND_PROOF_PLAN.md)
- `tool_request_schema.json`
