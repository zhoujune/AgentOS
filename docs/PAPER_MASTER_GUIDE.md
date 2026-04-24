# AgentOS Paper Master Guide

This document is the master writing guide for the AgentOS paper. It is meant to
contain everything needed to write the final submission: the paper claim, the
system framing, the evaluation story, the formalization story, the artifact
story, suggested figures and tables, exact benchmark results, limitations, and
remaining work.

The intended target is:

- **Venue**: ASE 2026, Tools and Datasets track
- **Planned deadline**: **May 11, 2026**

This guide is not the paper itself. It is the source-of-truth planning and
assembly document that should make writing the final paper straightforward.

---

## 1. Executive Summary

### 1.1 What the paper is about

The paper is about **AgentOS**, a research platform for constraining and
evaluating tool-using agents. The central idea is that agent safety should not
be evaluated by trusting prompts, model self-report, or textual logs alone.
Instead:

- **VTRM** mediates tool requests inside the guest runtime.
- **WEJ** evaluates actual world effects from the host side.

Together, these provide a stronger and more auditable basis for reasoning about
agent behavior than prompt-only defenses.

### 1.2 One-sentence paper claim

> AgentOS combines an in-guest typed reference monitor (VTRM) with a host-side
> World Effect Judge (WEJ) so that high-risk agent effects can be constrained at
> the tool boundary and evaluated from actual world-state outcomes rather than
> model self-report.

### 1.3 Short version of the result

On the current malicious benchmark:

- `naive` is unsafe on most direct and injection attacks.
- `cot` improves somewhat on direct attacks but remains weak on injection.
- `agentos` blocks all attacks in the current benchmark.

On the current benign benchmark:

- `agentos`, `cot`, and `naive` all achieve full safe completion on the current
  10-task should-pass suite.

### 1.4 What this paper is not

This is **not** a paper claiming:

- full formal verification of AgentOS
- end-to-end proof of the VM, kernel, Buildroot, or network stack
- semantic immunity to prompt injection at the model level
- formal correspondence proof between TLA+ and the Python implementation

The paper should instead claim:

- a **proof-oriented**, **partially formalized**, **invariant-driven** monitor
  architecture
- host-side effect evaluation
- empirical evidence that structural mediation outperforms prompt-only defenses

---

## 2. Recommended Paper Positioning

### 2.1 Core framing

The strongest framing is:

- Agent safety should be evaluated through **world effects**
- not only through:
  - prompt compliance
  - model answers
  - model logs

This gives the paper a clean contribution:

1. **Constraint** unsafe actions through a typed reference monitor.
2. **Judge** actual outcomes through host-side observation.

### 2.2 Why this is a Tools and Datasets paper

The paper should present two closely related artifacts:

#### AgentOS-Eval

The evaluation artifact used in the paper.

Includes:

- the benchmark harness
- WEJ
- `naive`, `cot`, and `agentos` modes
- benign and malicious task suites
- reports and reproducibility scripts

#### AgentOS-Clean

The planned clean artifact for normal use and demonstration.

Intended contents:

- the secure runtime path
- VTRM-enabled execution
- no benchmark scaffolding as user-facing functionality

This profile has not yet been split out as a separate packaged image. The
current runnable image used by the experiments is AgentOS-Eval.

This distinction helps reviewers understand:

- what is the research artifact
- what is the clean prototype system

### 2.3 Recommended scope statement

The paper should say explicitly:

> We do not claim full verification of the complete system. Instead, we present
> a monitor-centered architecture, a host-side world-effect evaluation
> framework, a benchmark artifact, and a small formalization of the monitor core.

---

## 3. Canonical Terms and Naming

Use these terms consistently in the paper.

### 3.1 System terms

- **AgentOS**: the overall research system
- **VTRM**: Verified Toolchain Reference Monitor
- **WEJ**: World Effect Judge
- **AgentOS-Eval**: evaluation artifact
- **AgentOS-Clean**: planned clean runtime packaging

### 3.2 Benchmark terms

- **Should-Pass**: benign utility tasks
- **Should-Fail / Direct**: direct malicious tasks
- **Should-Fail / Injection**: prompt-injection / indirect adversarial tasks

### 3.3 Metrics terms

For malicious tasks:

- **Attack Block Rate**
- **Attack Success Rate**

For benign tasks:

- **Safe Completion Rate**

Avoid using raw “completion rate” as the headline metric for malicious tasks,
because completing a malicious task means violating the safety goal.

---

## 4. Candidate Titles

These are viable title directions.

### Option A

**AgentOS: Constraining and Evaluating World Effects of Tool-Using Agents**

### Option B

**AgentOS: A Typed Reference Monitor and World Effect Judge for Agent Safety**

### Option C

**VTRM + WEJ: Host-Side Evaluation for Capability-Constrained Tool-Using Agents**

### Recommended title style

Prefer a title that emphasizes:

- tool-using agents
- world effects
- monitor + judge

rather than a title that suggests full formal verification.

---

## 5. Abstract Blueprint

The abstract should cover five things in order:

1. **Problem**
2. **Approach**
3. **Artifact**
4. **Evaluation**
5. **Scope**

### Draft abstract skeleton

> Tool-using agents can produce real world effects such as file mutations,
> secret reads, database updates, and network transmissions. Existing evaluations
> often rely on prompt-level defenses or agent self-report, which provide weak
> evidence about what actually happened. We present AgentOS, a research platform
> that combines an in-guest typed reference monitor, VTRM, with a host-side
> World Effect Judge (WEJ). VTRM mediates structured tool requests through
> object classification, confidentiality labeling, and allow/approval/deny
> decisions, while WEJ evaluates actual world-state outcomes by snapshotting and
> diffing filesystem, database, and network effects. We release AgentOS-Eval, an
> evaluation artifact containing benign and adversarial task suites together with
> `naive`, prompt-only `cot`, and `agentos` modes. We also describe
> AgentOS-Clean as the intended future clean runtime packaging, but the current
> runnable image is AgentOS-Eval. On our current benchmark,
> AgentOS blocks all direct and prompt-injection attacks in the malicious suite
> while matching the baselines on the benign should-pass suite. To strengthen
> the monitor claim, we also provide a small TLA+ formalization of the VTRM
> decision core and mechanically check key safety invariants. Our results show
> that host-side effect evaluation combined with structural tool mediation
> provides stronger safety evidence than prompt-only baselines, while remaining
> honest about the partial scope of the guarantee.

---

## 6. Introduction Blueprint

### 6.1 Opening problem

The opening should establish:

- modern agents act through tools
- tools affect the world
- evaluating safety via text-only outputs is weak

### 6.2 Problem statement

The problem is not merely whether the model “knows” safety instructions.

The real problem is whether:

- the model is allowed to cause unsafe effects
- and whether the evaluation can observe them

### 6.3 Main idea

The key move is:

- constrain actions through VTRM
- externally judge outcomes through WEJ

### 6.4 Contributions section

Recommended contribution bullets:

1. **AgentOS**, a Buildroot-based research platform for capability-constrained
   tool-using agents.
2. **VTRM**, a typed and auditable reference monitor that mediates file,
   network, and database requests.
3. **WEJ**, a host-side world-effect evaluation framework that checks actual
   outcomes instead of trusting model self-report.
4. **A benchmark artifact** with benign, direct-attack, and prompt-injection
   tasks.
5. **A comparative evaluation** against `naive` and prompt-only `cot`
   baselines.
6. **A small formal artifact** in TLA+ that checks key invariants of the VTRM
   decision core.

---

## 7. Threat Model and System Boundary

Base this section on:

- [docs/B1_SYSTEM_BOUNDARY.md](/home/june/AgentOS/agentos/docs/B1_SYSTEM_BOUNDARY.md)
- [docs/B2_INVARIANTS.md](/home/june/AgentOS/agentos/docs/B2_INVARIANTS.md)
- [docs/B3_REQUEST_SCHEMA.md](/home/june/AgentOS/agentos/docs/B3_REQUEST_SCHEMA.md)
- [docs/B4_ASSUMPTIONS.md](/home/june/AgentOS/agentos/docs/B4_ASSUMPTIONS.md)

### 7.1 What is trusted

The paper should say that the trusted core includes:

- request normalization
- schema validation
- object classification
- capability derivation
- label derivation
- VTRM core logic
- effect adapter glue code
- audit path
- host-side WEJ

### 7.2 What is not trusted

- LLM output
- task text
- prompt-injected content
- external web content
- model self-reported labels or capabilities

### 7.3 What is assumed, not proved

- Linux kernel behavior
- Buildroot guest environment
- VM / hypervisor
- network stack
- SQLite implementation

### 7.4 What is out of scope

- full kernel proof
- semantic correctness of the LLM
- prompt-injection detection as a model-level theorem
- end-to-end verified correspondence between TLA+ and Python

---

## 8. System Architecture Section

This section should present four named components:

### 8.1 AgentOS

The experimental execution platform:

- Buildroot guest image
- QEMU-based evaluation runtime
- host/guest bridge
- unprivileged `agent` user runtime

### 8.2 VTRM

The in-guest control point:

- typed request normalization
- object classification
- capability derivation
- confidentiality label derivation
- allow / approval / deny decision
- audited effect execution

### 8.3 WEJ

The host-side evaluation mechanism:

- before / after snapshots
- world-state diffing
- network sink observation
- task completion check
- safety check

### 8.4 Benchmark harness

The evaluation wrapper:

- benchmark task suites
- run orchestration
- report generation
- support for `naive`, `cot`, and `agentos`

---

## 9. VTRM Section Blueprint

This is the main mechanism section.

### 9.1 Typed request model

Explain that LLM output is only a candidate action description.

The trusted internal object is a normalized typed request.

Use the idea from [docs/B3_REQUEST_SCHEMA.md](/home/june/AgentOS/agentos/docs/B3_REQUEST_SCHEMA.md):

```text
NormalizedRequest = {
  task_id,
  request_id,
  subject,
  tool,
  args,
  target_object_class?,
  source_object_classes?,
  sink_class?,
  required_capability,
  inferred_conf_label
}
```

### 9.2 Object model and labels

Core object classes:

- `workspace_writable`
- `protected`
- `secret_source`
- `readonly`
- DB object classes

Core labels:

- `public`
- `secret/high`

### 9.3 Capability and policy model

Describe the three decision types:

- **Allow**
- **Approval required**
- **Deny**

### 9.4 Audit and fail-closed behavior

State the strongest design-level property:

- denied or invalid requests should not cause side effects

### 9.5 Suggested formula block

Show these formulas in the paper.

#### Deny has no effect

```text
decision' = Deny => state' = state
```

or, closer to the model:

```text
decision' = Deny => (fsClass' = fsClass /\ fsLabel' = fsLabel)
```

#### No secret to external sink

```text
(req.tool = network.send /\ req.dataLabel = secret_high /\ req.sinkClass = external_untrusted)
=> decision != Allow
```

These are simple enough to read and strong enough to look formal.

---

## 10. WEJ Section Blueprint

This section should explain why host-side judgment is necessary.

### 10.1 Why self-report is insufficient

The paper should say:

- a model may claim completion without acting
- a model may hide unsafe steps
- a model may partially act while narrating something else

WEJ therefore measures effects directly.

### 10.2 Snapshot and diff model

Explain:

- pre-state snapshot
- post-state snapshot
- allowed change prefixes
- forbidden change prefixes

### 10.3 HTTP sink

Explain that:

- host-side sink captures outbound HTTP
- secret leakage is determined from observed events
- this matters especially for exfiltration tasks

### 10.4 Separate metrics

WEJ distinguishes:

- **task completion**
- **safety**

This is important because a system can:

- complete a task unsafely
- stay safe but fail utility
- or do both correctly

---

## 11. Benchmark Section Blueprint

### 11.1 Benchmark partition

There are two main benchmark families:

#### Benign benchmark

- `judge/tasks_should_pass`
- 10 tasks
- ordinary workspace-only utility tasks

#### Malicious benchmark

- `judge/tasks_should_fail/direct`
- `judge/tasks_should_fail/injection`
- 10 direct + 10 injection tasks

### 11.2 Baselines

Use these three:

- `naive`
- `cot`
- `agentos`

Definitions:

- **naive**: no VTRM enforcement, direct execution path
- **cot**: stronger prompt-only warning, still no VTRM enforcement
- **agentos**: VTRM + WEJ + intended secure path

### 11.3 Metric definitions

For malicious tasks:

- **Attack Block Rate** = fraction of cases with `safety_ok = true`
- **Attack Success Rate** = fraction of cases with `safety_ok = false`

For benign tasks:

- **Safe Completion Rate** = fraction of cases with both task completion and
  safety pass

This is the cleanest formulation.

---

## 12. Exact Benchmark Results

This section records the current benchmark results that should be used in the
paper unless newer reruns supersede them.

### 12.1 Malicious benchmark runs

Final run mapping:

- `20260422-121500` = direct / naive
- `20260422-122304` = injection / naive
- `20260422-123336` = direct / cot
- `20260422-124232` = injection / cot
- `20260422-125350` = direct / agentos
- `20260422-130801` = injection / agentos

Exact counts extracted from the run summaries:

| Run ID | Suite | Mode | Cases | Task Pass | Task Fail | Safety Pass | Safety Fail |
|---|---|---|---:|---:|---:|---:|---:|
| `20260422-121500` | Direct | `naive` | 10 | 10 | 0 | 2 | 8 |
| `20260422-122304` | Injection | `naive` | 10 | 10 | 0 | 2 | 8 |
| `20260422-123336` | Direct | `cot` | 10 | 10 | 0 | 6 | 4 |
| `20260422-124232` | Injection | `cot` | 10 | 10 | 0 | 2 | 8 |
| `20260422-125350` | Direct | `agentos` | 10 | 9 | 1 | 10 | 0 |
| `20260422-130801` | Injection | `agentos` | 10 | 0 | 10 | 10 | 0 |

### 12.2 Paper-ready malicious table

| Suite | Mode | Cases | Safety Pass | Safety Fail | Attack Block Rate | Attack Success Rate |
|---|---|---:|---:|---:|---:|---:|
| Direct | `naive` | 10 | 2 | 8 | 20% | 80% |
| Injection | `naive` | 10 | 2 | 8 | 20% | 80% |
| Direct | `cot` | 10 | 6 | 4 | 60% | 40% |
| Injection | `cot` | 10 | 2 | 8 | 20% | 80% |
| Direct | `agentos` | 10 | 10 | 0 | 100% | 0% |
| Injection | `agentos` | 10 | 10 | 0 | 100% | 0% |

### 12.3 How to interpret the malicious table

The paper should explicitly say:

- `naive` is highly vulnerable in both direct and injection settings
- `cot` helps on direct malicious requests but collapses on injection tasks
- `agentos` blocks all malicious tasks in the current benchmark

The strongest interpretation is:

> Prompt-only caution is insufficient against indirect adversarial instructions,
> while structural mediation plus host-side world-effect evaluation prevents the
> observed malicious effects.

### 12.4 Benign benchmark runs

Current relevant run IDs:

- `20260422-144041` = should-pass / cot
- `20260422-145056` = should-pass / naive
- `20260422-153922` = should-pass / agentos

Exact counts:

| Run ID | Suite | Mode | Cases | Task Pass | Task Fail | Safety Pass | Safety Fail |
|---|---|---|---:|---:|---:|---:|---:|
| `20260422-145056` | Should-Pass | `naive` | 10 | 10 | 0 | 10 | 0 |
| `20260422-144041` | Should-Pass | `cot` | 10 | 10 | 0 | 10 | 0 |
| `20260422-153922` | Should-Pass | `agentos` | 10 | 10 | 0 | 10 | 0 |

### 12.5 Paper-ready benign table

| Suite | Mode | Cases | Completion Pass | Completion Fail | Safety Pass | Safety Fail | Safe Completion Rate |
|---|---|---:|---:|---:|---:|---:|---:|
| Should-Pass | `naive` | 10 | 10 | 0 | 10 | 0 | 100% |
| Should-Pass | `cot` | 10 | 10 | 0 | 10 | 0 | 100% |
| Should-Pass | `agentos` | 10 | 10 | 0 | 10 | 0 | 100% |

### 12.6 How to interpret the benign table

This table supports the utility claim:

- the safety gains do not come from refusing everything
- on the current benign suite, AgentOS matches the baselines

The best accompanying sentence is:

> On the current 10-task should-pass suite, AgentOS preserves benign safe
> completion while substantially improving attack blocking on the malicious
> benchmark.

---

## 13. Results Section Draft

The following prose can be adapted directly into the paper.

> We evaluate AgentOS against two lightweight baselines: `naive`, which
> executes model-issued tool requests without VTRM enforcement, and `cot`, which
> uses stronger prompt-only safety instructions but still lacks structural
> mediation. We report results on a 20-task malicious benchmark split into 10
> direct attacks and 10 indirect prompt-injection attacks. For malicious tasks,
> the main metric is Attack Success Rate, i.e., the fraction of cases in which
> the unsafe goal succeeded. Table 1 shows that `naive` is compromised on 80% of
> both direct and injection attacks. The prompt-only `cot` baseline improves to
> 40% attack success on direct attacks, but remains vulnerable on 80% of
> injection attacks. In contrast, AgentOS blocks all attacks in the current
> benchmark. We also evaluate a 10-task benign should-pass suite. As shown in
> Table 2, `naive`, `cot`, and `agentos` all achieve 100% safe completion on the
> current benign benchmark. Together, these results suggest that the safety
> improvements of AgentOS come from structural mediation and host-side effect
> evaluation rather than indiscriminate refusal.

---

## 14. Formalization Section Blueprint

### 14.1 What to claim

The safe claim is:

> We provide a small TLA+ formalization of the VTRM decision core and
> mechanically check two key monitor invariants over a finite instance.

### 14.2 What not to claim

Avoid:

- “formally verified AgentOS”
- “machine-verified implementation”
- “proved correct end-to-end”

### 14.3 Formal artifact files

- [formal/vtrm_core.tla](/home/june/AgentOS/agentos/formal/vtrm_core.tla)
- [formal/vtrm_core.cfg](/home/june/AgentOS/agentos/formal/vtrm_core.cfg)
- [formal/README.md](/home/june/AgentOS/agentos/formal/README.md)

### 14.4 Checked properties

The current TLA+ model checks:

- `TypeInvariant`
- `NoSecretToExternal`
- `CanAllowSomething`
- `DenyHasNoEffectAlways`

### 14.5 Actual TLC run result

The current successful TLC run reported:

- **TLC version**: `2.19`
- **Result**: `Model checking completed. No error has been found.`
- **States generated**: `5563`
- **Distinct states**: `103`
- **Search depth**: `3`

### 14.6 Recommended text

> To strengthen the monitor claim, we formalize a small abstract model of the
> VTRM decision core in TLA+. The model abstracts typed requests, object classes,
> confidentiality labels, and sink classes into a finite transition system. We
> use TLC to mechanically check two key properties: denied requests do not
> change abstract world state, and secret-labeled data is never allowed to flow
> to an external untrusted sink. This formal artifact is intentionally small and
> should be understood as a partial formalization of the monitor semantics, not
> a full refinement proof of the complete AgentOS implementation.

### 14.7 Correspondence caveat

The paper should explicitly say:

> We do not claim a machine-checked correspondence proof between the TLA+ model
> and the Python implementation. Instead, the model captures the intended
> monitor semantics at the design level.

---

## 15. Figures to Include

### Figure 1: Full system structure

Should show:

- user task
- model / agent
- AgentOS guest VM
- VTRM inside guest
- filesystem / network / DB adapters
- host-side WEJ
- current and planned artifact views:
  - AgentOS-Eval
  - planned AgentOS-Clean

### Figure 2: VTRM internal structure

Should show:

- request normalization
- request validation
- classification and derivation
- policy engine
- audit / approval
- effect execution

### Figure 3: Evaluation loop

Should show:

- task
- run in guest
- before/after snapshot
- world diff
- completion and safety verdicts

### Figure 4: Optional benchmark overview

Could show:

- benign tasks
- direct attacks
- injection attacks
- baseline modes

---

## 16. Tables to Include

### Required

1. **Table 1: Malicious benchmark results**
2. **Table 2: Benign benchmark results**

### Optional

3. **Table 3: VTRM invariant summary**

Suggested columns:

- invariant
- informal meaning
- enforcement mechanism
- checked how

4. **Table 4: Model-to-implementation mapping**

Suggested columns:

- TLA+ concept
- implementation counterpart
- main file

This table is useful if the paper needs to make the formal artifact feel more
grounded without claiming a proof of faithfulness.

---

## 17. Artifact Section Blueprint

### 17.1 Artifact split

The artifact section should clearly state:

- `AgentOS-Eval` is the evaluation artifact
- `AgentOS-Clean` is the planned simplified secure runtime packaging

### 17.2 What reviewers should be able to do

They should be able to:

1. build the image
2. boot the VM
3. run the benchmark suites
4. reproduce the main tables
5. run the TLA+ model

### 17.3 Artifact ingredients

Mention:

- benchmark suites
- harness scripts
- WEJ reports
- formal model
- demo UI

### 17.4 Streamlit UI

The host-side Streamlit UI is now part of the showcase story:

- [streamlit_app.py](/home/june/AgentOS/agentos/streamlit_app.py)
- [docs/HOST_UI.md](/home/june/AgentOS/agentos/docs/HOST_UI.md)

It should be described as:

- a demonstration interface
- not the core scientific contribution
- useful for artifact review and presentation

---

## 18. Limitations Section Blueprint

The limitations section should be explicit and honest.

### 18.1 Scope limitations

- no full-system verification
- no verified correspondence from TLA+ to Python
- no proof of kernel or VM correctness

### 18.2 Benchmark limitations

- task suite size is still modest
- current benchmark is domain-specific
- prompt-injection coverage can still grow

### 18.3 Deployment limitations

- Buildroot VM research artifact, not productized OS
- evaluation harness assumptions still matter
- host-side WEJ must remain trusted

### 18.4 Policy limitations

- some flows are intentionally permitted by policy
- e.g., secret-to-workspace copying under the current policy framing

This should be acknowledged clearly so the claim stays honest.

---

## 19. Remaining Work Before Submission

This is the concrete pre-submission checklist.

### 19.1 Writing

- write Introduction
- write System sections
- write Evaluation section
- write Artifact section
- write Limitations section
- tighten abstract

### 19.2 Evaluation

- add more malicious cases if time allows
- especially more injection cases with realistic operational instructions
- rerun the tables if any benchmark changes

### 19.3 Formalization

- add the exact TLC command and output to `formal/README.md`
- optionally add a model-to-code mapping table in the paper

### 19.4 Artifact polish

- test the Streamlit UI end to end
- ensure benchmark commands are documented clearly
- make paper table reproduction easy

### 19.5 Final package

- screenshots of UI
- screenshots of TLC success
- sample report directories
- exact run commands for Table 1 and Table 2

---

## 20. Exact Commands Worth Recording

### 20.1 TLC

```bash
java -cp /home/june/AgentOS/agentos/packages/tla2tools.jar tlc2.TLC \
  -config /home/june/AgentOS/agentos/formal/vtrm_core.cfg \
  /home/june/AgentOS/agentos/formal/vtrm_core.tla
```

### 20.2 Malicious benchmark

```bash
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/direct --agent-mode naive --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/injection --agent-mode naive --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/direct --agent-mode cot --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/injection --agent-mode cot --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/direct --agent-mode agentos --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/injection --agent-mode agentos --reset-between-cases
```

### 20.3 Benign benchmark

```bash
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode naive --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode cot --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode agentos --reset-between-cases
```

---

## 21. Final Recommended Narrative

If the paper has to be compressed aggressively, the core narrative should be:

1. Tool-using agents cause real world effects.
2. Prompt-only evaluation is weak.
3. AgentOS constrains effects with VTRM and judges them with WEJ.
4. On malicious tasks, AgentOS blocks attacks better than `naive` and `cot`.
5. On benign tasks, AgentOS preserves completion on the current benchmark.
6. A small TLA+ model strengthens the monitor story without overclaiming full
   verification.

That is the paper in its clearest form.

---

## 22. Recommended Claim Language

### Safe wording

- proof-oriented
- invariant-driven
- partially formalized
- mechanically checked abstract monitor model
- host-side world-effect evaluation
- typed reference monitor

### Wording to avoid

- formally verified AgentOS
- proved correct implementation
- verified end-to-end
- machine-checked correspondence to the runtime

---

## 23. Bottom-Line Recommendation

The strongest honest paper to write from the current project state is:

> a systems-and-artifact paper about a typed monitor plus host-side world-effect
> evaluation, supported by benchmark evidence and a small formalization of the
> monitor core.

That is already a strong and coherent ASE Tools and Datasets submission.
