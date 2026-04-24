# AgentOS B 线 — Assumptions（核心假设）

**文档编号**: B4  
**版本**: 0.2  
**日期**: 2026-04-15  
**状态**: 对齐新版本设计

---

## 1. 概述

本文档列出 B 线安全架构成立的**全部前提假设**。

这些 assumptions 是 B 线验证核心成立的基础。如果任一假设被违反，则 B 线的 safety claims 不再有效。

**核心原则**：
- VTRM 决定"逻辑上允许什么"
- OS Guard Rails 负责"即使 monitor 有 bug，损失也尽量有限"
- 两者不能互相替代

---

## 2. 信任边界总览

### 2.1 明确信任（TCB 的一部分）

以下组件视为 trusted computing base：

| 组件 | 说明 |
|------|------|
| Request normalizer | 解析 LLM 输出，构建 NormalizedRequest |
| Schema validator | 验证请求格式 |
| Path / Sink / DB classifier | 分类推导 |
| Capability deriver | capability 推导 |
| Label engine | label 推导与传播 |
| VTRM core | 策略决策 |
| Effect adapter glue code | adapter 连接代码 |
| 审计日志最小写入链路 | 日志落盘 |

### 2.2 降低假设但不证明（环境依赖）

以下组件���环境依赖，但不纳入第一阶段证明：

| 组件 | 说明 |
|------|------|
| Linux kernel | 文件系统、网络栈 |
| Python runtime | VTRM 实现依赖 |
| SQLite 引擎 | 数据库引擎 |
| VM / hypervisor | 沙盒隔离 |
| Host / VM bridge | 通信机制 |

### 2.3 明确不信任

以下输入默认不可信：

| 输入 | 说明 |
|------|------|
| LLM 输出 | 仅作为候选请求 |
| 用户 task 描述 | 不可信输入 |
| 外部 HTTP 响应 | 不可信外部数据 |
| 模型自报的 task_id / request_id / subject | 必须以 runtime 为准 |
| 模型自报的 capability_required | 必须由系统推导 |
| 模型自报的 content_label | 必须由系统推导 |

---

## 3. 运行时假设

### ASSUM-RUNTIME-1: 所有高风险副作用必须经过 VTRM

**陈述**：所有 `fs / network / sqlite` 操作必须通过 `VTRM.evaluate()` 验证后才能执行。

**为什么关键**：
- VTRM 是唯一的 policy decision point
- 如果 agent 或外部代码绕过 VTRM，直接调用 wrapper，则整个 security model 崩溃

**验证方法**：
- 代码审查：`agent_runner.py` 中所有工具调用必须通过 `vtrm.evaluate()`
- 代码审查：`fs_wrapper.sh`、`network_wrapper.sh`、`sqlite_wrapper.sh` 只接受 VTRM 授权操作
- 测试：注入非法直接 wrapper 调用应失败

**潜在违反场景**：
- 未来添加新工具时未接入 VTRM
- shell 或 sys wrapper 绕过 VTRM

---

### ASSUM-RUNTIME-2: Effect Adapters 不得自行扩权

**陈述**：adapter 不能在执行阶段自行放宽 policy，不能包含独立 policy check。

**为什么关键**：
- B 线要求单一可信基（single TCB）
- 如果 adapter 自己做决策，则存在 VTRM 与 adapter policy 不一致的风险

**验证方法**：
- 代码审查：adapter 中不含 `policy_check` 函数
- 测试：直接调用 adapter 应执行但无 policy 保护（是 dumb 执行器）

**当前实现要求**：
- `fs_wrapper.sh v2`：移除独立 policy，只执行
- `network_wrapper.sh v2`：移除独立 policy，只执行（保留 label 检查为防御性）
- `sqlite_wrapper.sh v2`：移除任意 SQL，只提供 typed ops

---

### ASSUM-RUNTIME-3: VTRM 代码本身正确性

**陈述**：`vtrm/` 目录下的 Python 代码（`vtrm_core.py`、`policy.py`、`path_classifier.py`、`label_model.py`、`audit_logger.py`、`db_ops.py` 等）正确实现 specification。

**为什么关键**：
- VTRM 是 reference monitor，其正确性是整个系统安全的前提
- 如果 VTRM 代码有 bug，可能导致错误的 allow/deny 决策

**验证策略**：
- **当前阶���**：代码审查 + 单元测试
- **未来阶段**：形式化验证（spec → code）

**需进行的检查**：
- `path_classifier.classify()` 对所有路径返回确定结果
- `canonicalize_path()` 正确处理路径穿越
- `policy.*` 所有 `check()` 方法在边界条件下行为正确
- `audit_logger` 不丢失日志

---

### ASSUM-RUNTIME-4: Classifier 实现正确

**陈述**：
- path 分类正确
- sink 分类正确
- capability derivation 正确
- label derivation / propagation 正确

**为什么关键**：
- classifier 是 proof 的基础输入
- 如果 classifier 错误，则 theorem 基于错误前提

**验证方法**：
- 单元测试：覆盖所有已知路径/sink 类型
- 测试：`unknown` 类型默认 deny

---

## 4. 环境假设

### ASSUM-ENV-1: Python 环境完整

**陈述**：VM 内 Python 3 可正常运行，且包含 `sqlite3`、`jsonschema` 模块。

**为什么关键**：
- VTRM 用 Python 实现
- `db_ops.py` 依赖 `sqlite3`
- schema 验证依赖 `jsonschema`

**验证方法**：
```bash
python3 -c "import jsonschema; import sqlite3; print('OK')"
```

**备选方案**：若 jsonschema 不可用，VTRM 应降级为最小 schema 检查（内联 fallback）。

---

### ASSUM-ENV-2: Wrapper 可执行

**陈述**：`/opt/sandbox/bin/*.sh` 脚本存在且可执行。

**为什么关键**：
- VTRM 执行操作时调用 adapter backend
- 如果 adapter 不可执行，操作失败

**验证方法**：
```bash
ls -l /opt/sandbox/bin/{fs,network,sqlite}_wrapper.sh
```

---

### ASSUM-ENV-3: 目录挂载正常

**陈述**：9P 共享目录 `/mnt/agent_bridge` 正常挂载，且 `inbox/outbox/done/error` 目录可访问。

**为什么关键**：
- agent_runner 通过 bridge 与宿主机通信
- 挂载失败则 LLM 请求无法进行

**验证方法**：
```bash
ls /mnt/agent_bridge/inbox
```

---

### ASSUM-ENV-4: Audit Append 可判定成败

**陈述**：系统必须能明确知道审计写入成功还是失败。

**为什么关键**：
- `Logged Mutation` 要求 mutation 必须有对应 audit
- 若 audit 不可写，则 mutation 必须 fail closed

**验证方法**：
- 测试：audit 写入失败时，mutation 请求被拒绝

---

## 5. 配置假设

### ASSUM-CONFIG-1: Agent Capability 配置正确

**陈述**：`agent_runner.py` 中的 `AGENT_CAPABILITIES` 集合与 VTRM 的 `agent_capabilities` 参数一致。

**为什么关键**：
- capability 不匹配导致合法请求被拒绝
- 或能力过多导致 agent 拥有超出预期的权限

**验证方法**：
- 单元测试：构造带有不同 capability_required 的请求，验证决策
- 审计日志检查：统计被 deny 的 capability 错误

---

### ASSUM-CONFIG-2: External Sink 配置正确

**陈述**：`ALLOWED_EXTERNAL_SINKS` 集合配置正确（至少包含授权的外发地址）。

**为什么关键**：
- secret data 外发检查依赖此配置
- 若为空，则所有 secret 外发都会被拒绝（可能过严但安全）

**验证方法**：
- 检查环境变量或代码中的 sink 列表
- 测试：使用 authorized sink URL 应 allow

---

### ASSUM-CONFIG-3: Object Classification 配置正确

**陈述**：classifier 的路径/sink/表配置正确标识所有关键对象类。

**为什么关键**：
- `/protected/**` 必须正确分类为 `protected`
- `/secrets/**` 必须正确分类为 `secret_source`
- 若配置错误，则 invariant 不成立

**验证方法**：
- 代码审查：检查分类规则
- 测试：验证各路径/sink 的分类结果

---

## 6. LLM 行为假设

### ASSUM-LLM-1: LLM 输出符合 Schema

**陈述**：LLM 输出符合 `tool_request_schema.json` 的约束。

**为什么关键**：
- VTRM 依赖 schema 验证
- LLM 输出格式错误 → schema 验证失败 → request 被 deny

**缓解策略**：
- system prompt 中明确要求输出特定格式
- 设置 `temperature=0.2` 减少随机性
- agent_runner 重试机制：schema 失败时提示 LLM 重新输出

**验证方法**：
- 统计 schema validation error 在 audit log 中的频率
- 若过高，需改进 prompt 或增加 output parser

---

### ASSUM-LLM-2: Content Label 设置建议合理

**陈述**：LLM 为每个请求提供 `content_label` 建议。

**为什么关键**：
- LLM 的建议值仅供参考，最终由系统推导
- 若 LLM 错误地将 secret 数据标记为 `public`，系统应能通过 object classification 检测

**缓解策略**：
- 对 `secret_source` 类对象的读取，自动标记为 `secret/high`
- 对 `secret_table` 的读取，自动标记为 `secret/high`
- 不完全依赖 LLM 自报

**未来改进**：
- 自动 label inference：VTRM 根据数据来源自动推断 label，减少 LLM 负担

---

## 7. 安全假设

### ASSUM-SEC-1: VM 隔离有效

**陈述**：VM 沙盒隔离有效，agent 无法突破 VM 访问宿主机。

**为什么关键**：
- 如果 VM 隔离失败，agent 可直接破坏宿主机
- B 线的 VTRM 只在 VM 内有效，不负责 VM escape 防护

**验证方法**：
- 现有测试已验证 VM 隔离
- 但 B 线不依赖此假设作为 VTRM 正确性的一部分

---

### ASSUM-SEC-2: Host / VM Bridge 安全

**陈述**：`/mnt/agent_bridge` 挂载点安全，agent 不能破坏 bridge 协议。

**为什么关键**：
- bridge 是 LLM 请求的唯一通道
- 若 agent 能修改 bridge，可进行 LLM 注入攻击

**验证方法**：
- 文件权限检查：bridge 目录的 mount options
- 运行 agent 用户权限限制

---

### ASSUM-SEC-3: Effect Adapter 实现正确

**陈述**：adapter backend 实现正确，不引入新的安全漏洞。

**为什么关键**：
- VTRM 决策正确，但 adapter 执行出错仍会导致问题
- 例如：`fs_wrapper.sh` 路径遍历、`network_wrapper.sh` 命令注入

**验证方法**：
- 单元测试：对每个 adapter 进行边界测试
- 静态分析：检查 shell 脚本中的变量展开

**已知风险**：
- `fs_wrapper.sh` 中的 `path` 参数（但 VTRM 已验证路径分类 + canonicalize）
- `sqlite_wrapper.sh` 使用参数化查询，基本安全

---

## 8. OS Guard Rails 假设

### ASSUM-OS-1: no_new_privs 设置有效

**陈述**：agent 进程设置 `no_new_privs`，防止后续 execve 获得新特权。

**为什么关键**：
- 是"capability monotonicity"在 OS 层的一个辅助约束
- 能防止某些 exec-based privilege gain

**验证方法**：
- 检查进程状态：`cat /proc/self/status | grep NoNewPrivs`

---

### ASSUM-OS-2: seccomp 过滤有效

**陈述**：seccomp 过滤高风险 syscall 面。

**为什么关键**：
- 不能代替对象级策略，但可限制：
  - 明显不需要的系统调用
  - 任意命令执行带来的额外能力面
  - 某些危险 process / mount / namespace 操作

---

### ASSUM-OS-3: Readonly Mount 有效

**陈述**：
- `/protected` 挂成只读
- 审计目录由 monitor 专属写入
- `/workspace` 作为主要工作输出区

**为什么关键**：
- 配合 VTRM 的逻辑安全，形成 defense-in-depth

---

### ASSUM-OS-4: Landlock 限制（如适用）

**陈述**：Linux Landlock（如可用）补充对象级访问约束。

**为什么关键**：
- Landlock 规则聚焦于 kernel objects 的访问控制
- 与 VTRM 的 object class 语义契合

---

## 9. 不变量依赖的假设

以下假设是 invariants / theorems 成立的前提：

| Invariant / Theorem | 依赖的 Assumption |
|---------------------|------------------|
| INV-VTRM-1 (Fail-Closed) | ASSUM-RUNTIME-1, ASSUM-RUNTIME-3 |
| INV-VTRM-2 (Capability Monotonicity) | ASSUM-RUNTIME-1, ASSUM-CONFIG-1 |
| INV-FS-1 (Protected-Path) | ASSUM-RUNTIME-2, ASSUM-CONFIG-3, ASSUM-OS-3 |
| INV-NET-1 (Secret Non-Exfil) | ASSUM-CONFIG-2, ASSUM-LLM-2 |
| INV-DB-1 (Typed Ops Only) | ASSUM-RUNTIME-2 |
| INV-LOG-1 (Logged Mutation) | ASSUM-RUNTIME-1, ASSUM-ENV-4 |
| T1 (Protected Path Safety) | INV-FS-1, INV-FS-3 |
| T2 (No Secret to Unauthorized Sink) | INV-NET-1, INV-NET-3 |
| T3 (Mutation Implies Audit) | INV-LOG-1 |
| T4 (Deny No Side Effect) | INV-VTRM-1, INV-WRAP-2 |

---

## 10. 未来需要形式化验证的部分

随着系统演进，以下内容应纳入正式验证：

| 组件 | 待验证属性 | 当前状态 |
|------|-----------|----------|
| `path_classifier` | 分类函数是 total function | 手动审查 |
| `path_classifier` | canonicalize 正确处理路径穿越 | 单元测试 |
| `sink_classifier` | 分类函数是 total function | 手动审查 |
| `capability_deriver` | 推导与 object class 一致 | 单元测试 |
| `label_engine` | 标签传播单调性 | 待测试 |
| `policy.py` | Fail-Closed 性质 | 单元测试 |
| `vtrm_core.py` | evaluate() 决策逻辑正确性 | 集成测试 |
| `audit_logger` | 审计日志完整性 | 代码审查 |

---

## 11. 假设变更管理

任何对上述假设的修改（例如：扩展 capability 集合、修改 classifier 规则、添加新工具）必须：

1. 更新本文档
2. 重新评估受影响 invariants / theorems
3. 更新测试用例
4. 进行代码审查

---

## 12. 安全声明写法

请避免写：
- fully safe
- guaranteed safe whole system
- cannot be bypassed under all conditions
- provably safe sandbox

建议写：
- capability-constrained
- auditable
- partially verified monitor
- invariant-preserving toolchain core
- defense-in-depth sandboxed environment

---

## 13. 文档引用

- [B1_SYSTEM_BOUNDARY.md](./B1_SYSTEM_BOUNDARY.md) — 系统边界与分层架构
- [B2_INVARIANTS.md](./B2_INVARIANTS.md) — 不变量与 Theorems
- [B3_REQUEST_SCHEMA.md](./B3_REQUEST_SCHEMA.md) — 请求 Schema
- [TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md](../agentos_top_level_design_docs/TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md)
- [TRUST_BOUNDARY_AND_OS_GUARDRAILS.md](../agentos_top_level_design_docs/TRUST_BOUNDARY_AND_OS_GUARDRAILS.md)
- [OBJECT_MODEL_AND_LABELS.md](../agentos_top_level_design_docs/OBJECT_MODEL_AND_LABELS.md)
- `tool_request_schema.json`
