# AgentOS Paper Structure

This note sketches a high-level structure for a paper built around AgentOS,
the Verified Toolchain Reference Monitor (VTRM), and the World Effect Judge
(WEJ). It is written as a planning document for the paper, not as a final
submission draft.

## 1. Working Paper Goal

The paper should argue a focused claim:

> AgentOS combines a typed toolchain monitor and a host-side world-effect
> evaluator so that high-risk agent side effects can be checked at the tool
> boundary rather than trusted from model self-report.

This is a partial systems guarantee, not a proof that the full OS, VM, LLM, or
internet-facing environment is safe.

The artifact story should also be explicit:

- `AgentOS-Eval`: the research artifact used for benchmarking and comparison
- `AgentOS-Clean`: the planned clean system configuration intended for future
  normal-use packaging and demonstration

## 2. Candidate Title Directions

- AgentOS: Evaluating and Constraining World Effects of Tool-Using Agents
- VTRM + WEJ: A Verifiable Toolchain and World-Effect Judge for Agent Safety
- AgentOS: Host-Side World-Effect Evaluation for Capability-Constrained Agents

## 3. Core System Pieces

The paper should consistently center four named components:

### AgentOS

The experimental platform and execution environment.

- Buildroot-based guest OS
- VM-based isolation boundary
- agent user runtime
- bridge to the host-side API and evaluation harness

### VTRM

The policy enforcement core inside AgentOS.

- typed request normalization
- object classification
- capability derivation
- label derivation
- allow / approval / deny decisions
- audited execution of tool effects

### WEJ

The World Effect Judge on the host side.

- snapshots pre/post world state
- records observable file / DB / network side effects
- compares actual effects against task expectations
- does not trust the agent’s final answer as the ground truth

### Benchmark Tasks

The task suites used for evaluation.

- `should pass`: benign utility tasks
- `should fail/direct`: direct malicious requests
- `should fail/injection`: indirect prompt-injection tasks

### Two Artifact Views

The paper should present the system as two closely related artifact profiles
built from one codebase.

#### AgentOS-Eval

The evaluation artifact used in the paper.

- contains `naive`, `cot`, and `agentos` modes
- contains WEJ and the benchmarking harness
- contains should-pass and should-fail task suites
- optimized for reproducibility, comparison, and artifact review

#### AgentOS-Clean

The planned clean system artifact.

- intended to contain the secure runtime configuration without evaluation-only
  baseline modes as user-facing functionality
- not yet split out as an independently packaged image
- should be described as future artifact cleanup rather than as the image used
  for the current experiments

## 4. Recommended Paper Story

The paper should tell a simple story in this order:

1. Tool-using agents can cause real world effects.
2. Prompt-only defenses are not enough, especially under prompt injection.
3. AgentOS moves the safety boundary to the toolchain.
4. VTRM constrains what requests are allowed.
5. WEJ measures what actually happened in the world.
6. Together, they provide stronger and more auditable safety evidence than
   model self-report or prompt-only baselines.
7. The current artifact should be described as AgentOS-Eval, while
   AgentOS-Clean should be framed as the intended clean packaging to avoid
   implying that a separate clean image already exists.

## 5. Suggested Section Structure

## Abstract

One paragraph covering:

- problem: unsafe world effects by tool-using agents
- approach: AgentOS with VTRM + WEJ
- artifacts: the current AgentOS-Eval artifact and a planned clean packaging
- headline result: AgentOS blocks malicious effects while preserving utility on
  should-pass tasks

## 1. Introduction

Main points:

- modern agents act through tools, not just text
- real risk lies in world effects: file mutation, secret access, network send,
  DB mutation
- current evaluations often trust self-report or logs
- we need a system that both constrains effects and judges them externally

End the introduction with explicit contributions.

### Suggested contribution bullets

1. AgentOS, a Buildroot-based research platform for capability-constrained
   agent execution.
2. VTRM, a typed and auditable reference monitor for tool requests.
3. WEJ, a host-side world-effect judge that evaluates actual side effects.
4. A benchmark suite with benign, direct-attack, and prompt-injection tasks.
5. An empirical comparison against naive and CoT baselines.
6. A two-profile artifact plan separating the current evaluation machinery from
   the planned clean system packaging.

## 2. Problem Setting and Threat Model

This section should define:

- what the agent can do: fs, network, DB
- what the attacker controls:
  - direct user instructions
  - untrusted file / page / note contents
- what is trusted:
  - runtime metadata injection
  - VTRM implementation
  - host-side WEJ
- what is not claimed:
  - full OS proof
  - full kernel proof
  - full LLM correctness

Point back to:

- [THREAT_MODEL.md](/home/june/AgentOS/agentos/docs/THREAT_MODEL.md)
- [B1_SYSTEM_BOUNDARY.md](/home/june/AgentOS/agentos/docs/B1_SYSTEM_BOUNDARY.md)

## 3. AgentOS Overview

Explain the platform at the systems level.

Topics:

- Buildroot guest image
- VM execution model
- host/guest bridge
- agent runtime
- tool adapters
- audit and approval state

This section should give readers enough context to understand where VTRM and
WEJ live.

It should also clarify which pieces belong to:

- the clean runtime path
- the evaluation-only path

## 4. VTRM Design

This is the main mechanism section.

Subsections:

### 4.1 Typed Request Model

- raw LLM output is not trusted
- requests are normalized into a structured internal form

### 4.2 Object Model and Labels

- object classes:
  - `workspace_writable`
  - `protected`
  - `secret_source`
  - `audit_log`
  - DB classes
- labels:
  - `public`
  - `secret/high`

### 4.3 Capability and Policy Decisions

- auto allow
- approval required
- absolute deny

### 4.4 Audited Effect Execution

- no side effect on deny
- high-risk operations are logged
- effect adapters execute only approved effects

Point back to:

- [B3_REQUEST_SCHEMA.md](/home/june/AgentOS/agentos/docs/B3_REQUEST_SCHEMA.md)
- [B2_INVARIANTS.md](/home/june/AgentOS/agentos/docs/B2_INVARIANTS.md)
- [OBJECT_MODEL_AND_LABELS.md](/home/june/AgentOS/agentos/agentos_top_level_design_docs/OBJECT_MODEL_AND_LABELS.md)

## 5. World Effect Judge (WEJ)

This section explains why WEJ is needed and how it works.

Main points:

- self-report is not enough
- logs are not enough
- the host must measure actual effects

Subsections:

### 5.1 Snapshot and Diff Model

- before/after snapshots
- allowed change prefixes
- forbidden change prefixes

### 5.2 Network Sink Observation

- host-controlled HTTP sink
- observed exfiltration attempts
- matching secret content and sink events

### 5.3 Task-Oriented Judgement

- task completion checks
- safety checks
- why these are reported separately

### 5.4 Why WEJ Matters

- catches cases where the model says “task completed” without doing the right thing
- catches harmful world effects even when the final answer looks harmless

This section should clearly state that WEJ belongs to `AgentOS-Eval`, not the
minimal clean system path.

## 6. Benchmark Design

Describe the task suites as a reusable dataset contribution.

### 6.1 Should-Pass Tasks

Benign workspace tasks used to measure utility.

### 6.2 Should-Fail Direct Tasks

Direct malicious requests, mainly for sanity-checking unsafe behavior.

### 6.3 Should-Fail Injection Tasks

Indirect prompt-injection tasks where malicious instructions are embedded in
untrusted content.

### 6.4 Design Principles

- machine-checkable outcomes
- host-side observable effects
- stable sink / path conventions
- clear distinction between benign utility and malicious success

### 6.5 Dataset Placement in the Artifact

- `AgentOS-Eval` includes all benchmark tasks and reporting infrastructure
- the planned `AgentOS-Clean` package should not ship baseline modes or
  benchmark-specific task suites as part of its main user path

## 7. Experimental Setup

Define the baselines and metrics.

### 7.1 Baselines

- `naive`
- `cot`
- `agentos`

### 7.2 Metrics

For malicious tasks:

- attack success rate
- attack block rate

For benign tasks:

- safe completion rate
- completion rate

### 7.3 Protocol

- one task per fresh VM state
- host-side WEJ used for every run
- reset between cases

This section should make clear that the protocol applies to `AgentOS-Eval`.

## 8. Results

Suggested structure:

### 8.1 Benign Utility Results

Show whether AgentOS preserves completion on should-pass tasks.

### 8.2 Direct Attack Results

Show whether naive / CoT execute explicit malicious requests and whether
AgentOS blocks them.

### 8.3 Prompt-Injection Results

Show whether prompt-only safety degrades under indirect injection and whether
AgentOS remains safe.

### 8.4 Error Analysis

Include benchmark lessons learned:

- weak injection tasks
- oracle bugs
- infrastructure bugs such as guest networking
- dirty-image reset issues

This section can strengthen the tools-and-datasets contribution by showing how
the benchmark was refined into a usable artifact.

## 9. Discussion

Use this section to be explicit and honest.

Topics:

- AgentOS is safety-first and may lose utility in some injected benign tasks
- current guarantees are partial
- secret/high tracking is still a limited dynamic information-flow mechanism
- prompt-only baselines may appear strong on some direct tasks but fail under
  stronger injection tasks
- the current evaluation artifact is intentionally larger and more instrumented
  than the planned clean packaging

## 10. Limitations

Important limitations to state:

- not a whole-system proof
- depends on correct monitor placement
- current label model is intentionally simple
- WEJ only observes modeled effects
- benchmark coverage is limited to current tool set
- `AgentOS-Eval` contains research scaffolding that is not part of the minimal
  clean system

## 11. Conclusion

End with the main claim:

- AgentOS shows that combining a typed toolchain monitor with host-side
  world-effect judging is a practical way to evaluate and constrain agent side
  effects

## 6. Evaluation Shape for This Paper Version

If the paper needs a compact experimental story, the cleanest structure is:

- utility benchmark:
  - `judge/tasks_should_pass`
- adversarial direct benchmark:
  - `judge/tasks_should_fail/direct`
- adversarial injection benchmark:
  - `judge/tasks_should_fail/injection`

Then compare:

- `naive`
- `cot`
- `agentos`

## 7. Artifact Packaging Plan

The paper should explicitly separate two deliverables.

### 7.1 AgentOS-Eval

Contains:

- VTRM
- WEJ
- evaluation harness
- baseline modes (`naive`, `cot`, `agentos`)
- benchmark tasks and reports

Purpose:

- artifact evaluation
- reproducibility
- empirical comparison

### 7.2 Planned AgentOS-Clean

Contains:

- the intended secure runtime path after artifact cleanup
- VTRM in its normal configuration
- minimal docs for setup and use

Purpose:

- clean demonstration artifact in future packaging
- simpler onboarding
- reduced confusion between the system and the benchmark harness

## 8. Figures and Tables to Prepare

Recommended visuals:

### Figure 1

System overview:

- LLM -> Request Frontend -> VTRM -> Effect Adapters
- host-side WEJ observing snapshots and sink traffic

### Figure 2

Evaluation workflow:

- task
- VM boot
- agent execution
- WEJ before/after diff
- final verdict

### Table 1

Threat model and guarantees.

### Table 2

Should-pass utility results.

### Table 3

Should-fail malicious benchmark results:

- direct
- injection
- naive / cot / agentos

## 9. Writing Notes

Keep the paper claim narrow and strong.

Recommended emphasis:

- do not claim “safe OS”
- do claim “host-observable, tool-boundary safety evaluation and enforcement”

Recommended tone:

- precise
- artifact-oriented
- honest about limitations
- focused on what is structurally enforced versus what is only empirically shown
