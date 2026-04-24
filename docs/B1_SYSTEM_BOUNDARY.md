# AgentOS B 线 — 系统边界定义

**文档编号**: B1  
**版本**: 0.2  
**日期**: 2026-04-15  
**状态**: 对齐新版本设计

---

## 1. 设计目标与定位

本项目（代号 B 线）的目标不是要对整个 AgentOS、整个 VM、整个 Linux/Buildroot、整个网络栈或整个 SQLite 引擎做形式化验证。

**目标定位**：从现有 AgentOS baseline 中切出一个"小而硬"的可验证安全核心，作为后续形式化验证的 toolchain reference monitor。

**验证范围**：只针对 `fs + network + sqlite` 这三个工具通道构建 capability control、policy enforcement、state invariants 和 auditability。

**核心问题定义**：

> 我们能否为工具型智能体构建一个基于能力约束、可审计、部分形式化验证的工具链，使得某些高风险后果由结构性约束排除，而不是仅依赖 prompt 层防御？

---

## 2. 分层架构（6 层）

### Layer 0：环境与现实世界（不证明）

包括：
- LLM 本体
- prompt
- 外部网站 / API
- 宿主机外部资源
- Linux 大量未建模部分
- 真实网络世界

**默认不可信。**

---

### Layer 1：Request Frontend

**职责**：
- 接收 LLM 输出
- 提取 JSON
- 做 schema validation
- 做 runtime metadata injection
- 产出 `NormalizedRequest`

**目标**：
> 把"不可信文本/JSON 世界"切换到"可建模请求对象世界"。

---

### Layer 2：Classification & Derivation

**职责**：
- path → object class
- db object → object class
- sink → sink class
- request → required capability
- source / result → confidentiality label

**输出**：
- `object_class`
- `sink_class`
- `required_capability`
- `conf_label`

---

### Layer 3：VTRM（真正证明对象）

**职责**：

输入：`State × NormalizedRequest`  
输出：`Decision × StateDelta × AuditEvent`

VTRM 负责：
1. capability check
2. parameter check
3. state precondition check
4. allow / deny / transform
5. 审计事件生成
6. 对 effect adapter ���出受限执行指令

**这一层是整个主线 B 的证明核心。**

---

### Layer 4：Effect Adapters

包括：
- fs adapter
- network adapter
- sqlite adapter

**职责**：
- 执行 VTRM 已经批准的 effect
- 不自己做策略决策
- 不允许旁路 monitor

理想状态下，它们越来越"傻"，只消费 monitor 输出的结构化 effect。

---

### Layer 5：OS Guard Rails

包括：
- no_new_privs
- seccomp
- Landlock
- 只读挂载
- 最小网络暴露
- 容器 / mount namespace 等额外沙箱机制

**职责**：
> 收缩 ambient authority，给 monitor 的逻辑安全做 defense-in-depth。

---

## 3. 可信计算基（TCB）

### 必须信任
- Request normalizer
- Object classifier
- Capability deriver
- Label engine
- VTRM core
- Effect adapter glue code
- 审计落盘最小链路

### 尽量降低假设但不证明
- Linux kernel
- 文件系统实现
- Python runtime
- SQLite 引擎
- 网络栈
- VM / hypervisor
- Host / VM bridge 机制

### 明确不信任
- LLM 输出
- 用户 task 描述
- 外部网站内容
- 未经 normalizer 的 request metadata

---

## 4. 核心架构图

```
agent_runner / daemon
    │
    ▼
typed tool request (JSON)  ← Layer 1: Request Frontend
    │
    ▼
VTRM (Verified Toolchain Reference Monitor)  ← Layer 3: 证明核心
    ├── capability 检查
    ├── 参数合法性检查
    ├── 状态转移检查
    ├── object classification
    ├── label derivation
    └── 决策输出 (allow / deny / transformed)
    │
    ▼
wrapper backend (fs / network / sqlite)  ← Layer 4: Effect Adapters
    │
    ▼
audit log / world-state
    │
    ▼
OS Guard Rails (Layer 5): no_new_privs, seccomp, Landlock, ro-mount
```

---

## 5. 明确排除在验证核心之外的能力

以下能力**不在** B 线第一阶段验证范围内：

| 能力 | 排除理由 |
|------|----------|
| LLM 推理正确性 | 不在 toolchain 控制范围 |
| Prompt injection 检测 | 属于 semantic 层，不属于 reference monitor |
| VM / kernel 安全 | 属于 seL4 / VM 层面，B 线不负责 |
| 外部网站内容可信性 | 不在系统边界内 |
| 任意 shell 命令执行 | B 线不支持任意 shell，只支持 typed 接口 |
| 任意 SQL 查询 | B 线只支持受限的 typed DB 操作 |
| wrapper backend 绕过 VTRM | 这是一个 assumed assumption，不在验证范围内 |

---

## 6. VTRM 的职责边界

### 6.1 VTRM 负责

1. **接收 typed request**：接收结构化的 JSON tool request
2. **Request normalization**：构建 `NormalizedRequest`
3. **Object classification**：路径/DB对象/网络sink分类
4. **Capability 检查**：验证 request 是否在 agent 当前 capability 范围内
5. **Label derivation**：推导 `content_label`
6. **参数合法性检查**：验证路径格式、内容标签、数据库表/字段等
7. **状态转移检查**：验证当前 world-state 是否允许该操作
8. **决策输出**：输出 `allow` / `deny` / `transformed_request`
9. **审计日志**：为每个请求生成统一格式的审计事件

### 6.2 VTRM 不负责

1. LLM 推理正确性
2. prompt injection 检测
3. VM / kernel 安全
4. 外部网站内容可信性
5. 任意 shell 的完整真实语义
6. SQLite 引擎本身的 correctness

---

## 7. 第一批 Verified Core 工具

| 工具 | 类型 | 说明 |
|------|------|------|
| `fs.read` | 读文件 | 只读，不产生副作用 |
| `fs.write` | 写文件 | 写操作，产生 FS mutation |
| `network.send` | 网络发送 | 外发请求，可能产生 data exfiltration |
| `db.read` | 数据库读 | 只读，不产生副作用 |
| `db.insert` | 数据库插入 | 写操作，产生 DB mutation |
| `db.update` | 数据库更新 | 写操作，产生 DB mutation |

**注意**：`shell` 工具在 B 线第一阶段**不是** verified core 接口。如需保留，只能是 shell-lite 或白名单子集，且不能成为 capability system 的后门。

---

## 8. 对象分类（Object Classes）

最小 object class 集合：

| 类名 | 典型路径 | 读权限 | 写权限 | 说明 |
|------|----------|--------|--------|------|
| `protected` | `/protected/**` | ✓ | ✗ | 默认不可写，完整性保护 |
| `workspace_writable` | `/workspace/**` | ✓ | ✓ | 按 capability 控制写 |
| `readonly` | `/var/**` | ✓ | ✗ | 系统只读区 |
| `secret_source` | `/secrets/**` | ✓ | ✗ | 读取结果自动标记 `secret/high` |
| `audit_log` | `/var/log/sandbox/vtrm/**` | ✗ | ✗ | 审计目录，仅 monitor 可写 |
| `db_file` | `/var/lib/agentos/*.db` | ✗ | ✗ | 不直接访问，通过 db adapter |
| `unknown` | 其他 | ✗ | ✗ | 默认 deny |

**分类前必须 canonicalize**：绝对路径检查、normalize、symlink resolution，防止路径穿越。

---

## 9. 保密标签模型（Confidentiality Labels）

第一版最小标签集合：

| 标签 | 说明 |
|------|------|
| `public` | 公开数据，可自由外发 |
| `secret/high` | 敏感数据，禁止发送到未授权 sink |

**传播规则**：

1. 从 `secret_source` 类对象读出 → `secret/high`
2. 从 `secret_table` 读出 → `secret/high`
3. Join 规则：`join(public, secret/high) = secret/high`
4. 网络发送时检查 `inferred_conf_label`

**关键原则**：不依赖内容语义分析判断"这是不是秘密"，而是依赖 label discipline（标签传播）。

---

## 10. 网络 Sink 分类

| Sink 类 | 语义 |
|---------|------|
| `trusted_internal` | 受信任内部 sink（暂不开放） |
| `external_untrusted` | 外部不可信 sink，禁止 `secret/high` 外发 |

---

## 11. 数据库对象模型

**禁止** `exec_sql(sql_string)` 形式的任意 SQL。

**表类别**：

| 类别 | 语义 |
|------|------|
| `readonly_table` | 允许读，agent 不可写 |
| `mutable_table` | 可在 capability 满足下更新 |
| `audit_table` | 仅 monitor 可 append |
| `secret_table` | 读出的数据标记为 `secret/high` |

**Typed Operations**：

| 操作 | 接口 | 参数 |
|------|------|------|
| 读 | `db.read(table, key)` | table, key |
| 插入 | `db.insert(table, row)` | table, row_dict |
| 更新 | `db.update(table, key, patch)` | table, key, patch_dict |

---

## 12. 状态转移类型

| 类型 | 枚举值 | 说明 |
|------|--------|------|
| 只读 | `ReadOnly` | 不改变 world-state |
| 文件系统变更 | `MutateFS` | 写入文件 |
| 数据库变更 | `MutateDB` | 写入/更新数据库 |
| 外部发送 | `SendExternal` | 发起网络请求 |

---

## 13. Capability 命名规范

采用层次命名：`<tool>.<action>.<resource>`

**示例**：
- `fs.read` — 读任意文件
- `fs.write.workspace` — 写 `/workspace/**`
- `fs.write.protected` — 写 `/protected/**`（高权限）
- `network.send.external` — 发送到任意外部地址
- `db.read.tasks` — 读 tasks 表
- `db.insert.results` — 插入 results 表
- `db.update.tasks` — 更新 tasks 表

---

## 14. 核心安全标准

### S1: Fail-Closed

对以下情况必须默认 **deny**：
- 未识别工具
- 类型错误请求
- 参数缺失请求
- capability 不足请求
- 非法路径
- 未授权网络 sink
- `unknown` 对象类

deny 时：
- 不发生真实副作用
- 留下审计日志

---

### S2: Protected-Path Integrity

没有明确写权限的主体，不能成功修改 `protected` 类对象（如 `/protected/**`）。

---

### S3: Secret Non-Exfiltration

带 `secret/high` 标签的数据，不能成功发送到 `external_untrusted` sink。

---

### S4: Logged Mutation

每一次成功的 world-state mutation（FS/DB 写入、网络发送），都必须对应一条审计事件。

若审计不可写，则 mutation 不应发生（fail closed）。

---

### S5: Capability Monotonicity

agent 不能因为一次 tool output 或普通请求，自动获得新的 capability。capability 只能来自 trusted setup 或明确的受控 delegation。

---

## 15. Wrapper Backend 的角色

Wrapper backend（`fs_wrapper.sh`、`network_wrapper.sh`、`sqlite_wrapper.sh`）在 B 线架构中的角色是：

- **纯执行后端**：只负责执行 VTRM 允许的操作
- **无 policy 决策权**：不能自行判断 allow/deny
- **严格无副作用 on deny**：deny 时不产生任何状态变更
- **无独立 capability 检查**：完全信任 VTRM 的决策

---

## 16. 与现有系统的关系

### 16.1 保留的现有能力
- VM 沙盒隔离
- Host / VM 解耦
- LLM bridge（通过共享目录）
- daemon workflow
- transcript / trace / task log

### 16.2 需要修改的现有能力
- `agent_runner.py`：需接入 VTRM + Request Frontend
- `fs_wrapper.sh`：移除独立 policy 决策，改为纯执行后端
- `network_wrapper.sh`：需接入 label 检查
- `sqlite_wrapper.sh`：需改为受限操作接口

### 16.3 暂不涉及的部分
- `shell_wrapper.sh`：B 线第一阶段不纳入 verified core
- 其他系统 wrapper（sys, proc, log, service, disk, cron）

---

## 17. NormalizedRequest 模型

LLM 输出的 JSON 是**候选动作描述**，不是��式请求。

系统必须在执行前完成：
1. parse
2. schema validation
3. runtime metadata injection（`task_id`, `request_id`, `subject`）
4. object classification（`target_object_class`, `sink_class`）
5. capability derivation（`required_capability`）
6. label derivation / propagation（`inferred_conf_label`）
7. normalized internal request construction

最终进入 VTRM 语义的对象是 `NormalizedRequest`：

```text
NormalizedRequest = {
  task_id,                    // runtime 注入
  request_id,                 // runtime 生成
  subject,                    // runtime 确定
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

## 18. Request Schema（高层）

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

**关键**：`capability_required` 和 `content_label` 应由系统推导，LLM 仅提供建议值。

---

## 19. 工程实施优先级

### P1（最高）
- 在 runner / VTRM 前端完成 schema validation
- 完成 runtime metadata injection
- 实现 path classifier（含 canonicalize）

### P2
- 把 path / sink / db classifier 做成单独模块
- 实现 capability deriver

### P3（OS 层）
- 逐步加入 no_new_privs
- seccomp
- readonly mount
- 适用时的 Landlock

### P4
- 把 db adapter 收口成 typed db ops

### P5
- 明确 audit append 的失败语义

---

## 20. 代码组织建议

```
agentos/
├── vtrm/
│   ├── __init__.py
│   ├── vtrm_core.py          # VTRM 核心（证明对象）
│   ├── policy.py             # 策略引擎
│   ├── path_classifier.py   # 路径分类器（含 canonicalize）
│   ├── label_model.py        # 内容标签模型
│   ├── db_ops.py             # 受限数据库操作
│   ├── db_classifier.py      # 数据库对象分类
│   ├── sink_classifier.py    # 网络 sink 分类
│   ├── capability_deriver.py # capability 推导
│   ├── request_normalizer.py # Layer 1: normalization
│   └── audit_logger.py       # 统一审计日志
├── docs/
│   ├── B1_SYSTEM_BOUNDARY.md  # 本文档
│   ├── B2_INVARIANTS.md      # 不变量定义
│   ├── B3_REQUEST_SCHEMA.md   # 请求 Schema
│   └── B4_ASSUMPTIONS.md     # 假设清单
├── tool_request_schema.json   # JSON Schema
└── agent_runner.py            # 接入 Layer 1 + VTRM
```

---

## 21. 文档引用

- [B2_INVARIANTS.md](./B2_INVARIANTS.md) — 状态不变量与 Theorems
- [B3_REQUEST_SCHEMA.md](./B3_REQUEST_SCHEMA.md) — Typed Request Schema
- [B4_ASSUMPTIONS.md](./B4_ASSUMPTIONS.md) — 假设清单
- [TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md](../agentos_top_level_design_docs/TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md) — 顶层设计
- [OBJECT_MODEL_AND_LABELS.md](../agentos_top_level_design_docs/OBJECT_MODEL_AND_LABELS.md) — 对象模型与标签
- [TRUST_BOUNDARY_AND_OS_GUARDRAILS.md](../agentos_top_level_design_docs/TRUST_BOUNDARY_AND_OS_GUARDRAILS.md) — 信任边界与 OS 护栏
- [INVARIANTS_THEOREMS_AND_PROOF_PLAN.md](../agentos_top_level_design_docs/INVARIANTS_THEOREMS_AND_PROOF_PLAN.md) — Theorems 与证明计划
- `tool_request_schema.json` — JSON Schema 定义
