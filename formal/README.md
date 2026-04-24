# Minimal Formal Artifact for VTRM

This directory contains a deliberately small formalization of the VTRM core.

The goal is not to prove all of AgentOS correct. The goal is to provide a
small, explicit, mechanically checkable model of the monitor decision logic
that is close to the paper's main safety story.

## What This Artifact Is

The file [vtrm_core.tla](/home/june/AgentOS/agentos/formal/vtrm_core.tla)
contains a tiny abstract transition-system model of:

- typed requests
- object classes
- confidentiality labels
- sink classes
- a monitor decision function

It is intended to support a paper claim like:

> We formalize a small abstract model of the VTRM decision core and
> mechanically check key monitor invariants over that model.

## What It Models

The model includes:

- file object classes:
  - `workspace_writable`
  - `protected`
  - `secret_source`
- labels:
  - `public`
  - `secret_high`
- sink classes:
  - `trusted_internal`
  - `external_untrusted`
- tools:
  - `fs.read`
  - `fs.write`
  - `network.send`
- decisions:
  - `Allow`
  - `Deny`

The model captures only a small abstract state:

- `fsClass`
- `fsLabel`
- current `req`
- current `decision`

## What It Does Not Model

This artifact does **not** model:

- the full Buildroot OS
- QEMU
- the host/guest bridge
- the LLM
- WEJ
- approval tokens or full approval-store semantics
- concrete file contents
- the full database semantics
- refinement from the TLA+ model to the Python implementation

So this is **not** a full formal verification of AgentOS.

## Checked Properties

This tiny model is meant to support checking two core safety properties.

### 1. `DenyHasNoEffect`

If the monitor denies a request, the abstract world state does not change.

In the model:

- `decision = "Deny"` implies
  - `fsClass' = fsClass`
  - `fsLabel' = fsLabel`

This corresponds to the paper-facing idea:

- deny implies no abstract side effect

### 2. `NoSecretToExternal`

If a request is:

- `network.send`
- carrying `secret_high`
- targeting `external_untrusted`

then the decision cannot be `Allow`.

This corresponds to the paper-facing idea:

- secret-labeled data is never allowed to flow to an unauthorized external sink

## Relation to the Main Codebase

This model is inspired by the proof-oriented structure documented in:

- [B2_INVARIANTS.md](/home/june/AgentOS/agentos/docs/B2_INVARIANTS.md)
- [B3_REQUEST_SCHEMA.md](/home/june/AgentOS/agentos/docs/B3_REQUEST_SCHEMA.md)
- [B4_ASSUMPTIONS.md](/home/june/AgentOS/agentos/docs/B4_ASSUMPTIONS.md)
- [TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md](/home/june/AgentOS/agentos/agentos_top_level_design_docs/TOP_LEVEL_SAFE_TOOLCHAIN_DESIGN.md)
- [OBJECT_MODEL_AND_LABELS.md](/home/june/AgentOS/agentos/agentos_top_level_design_docs/OBJECT_MODEL_AND_LABELS.md)

The implementation-side logic lives mainly in:

- [vtrm_core.py](/home/june/AgentOS/agentos/br2-external/board/agentos/x86_64/overlay/home/agent/vtrm/vtrm_core.py)
- [policy.py](/home/june/AgentOS/agentos/br2-external/board/agentos/x86_64/overlay/home/agent/vtrm/policy.py)
- [authorization_policy.py](/home/june/AgentOS/agentos/br2-external/board/agentos/x86_64/overlay/home/agent/vtrm/authorization_policy.py)

The TLA+ model should be described in the paper as:

- a small abstract model of the monitor core
- not a proof of the full implementation

## How to Use It

Open `vtrm_core.tla` in the TLA+ Toolbox together with
[vtrm_core.cfg](/home/june/AgentOS/agentos/formal/vtrm_core.cfg).

The configuration file already defines a tiny finite instance:

- `Paths = {"/workspace/out.txt", "/protected/config.ini", "/secrets/api_key.txt"}`
- `WorkspacePath = "/workspace/out.txt"`
- `ProtectedPath = "/protected/config.ini"`
- `SecretPath = "/secrets/api_key.txt"`

The configuration checks:

- invariants:
  - `TypeInvariant`
  - `NoSecretToExternal`
- properties:
  - `CanAllowSomething`
  - `[][DenyHasNoEffect]_vars`

This setup is intentionally small so that TLC is more likely to run cleanly on
the first try.

## How to Talk About It in the Paper

Safe wording:

- `partially formalized`
- `proof-oriented`
- `invariant-driven`
- `mechanically checked abstract monitor model`

Unsafe wording unless more work is done:

- `formally verified AgentOS`
- `machine-verified implementation`
- `proved correct end-to-end`

## Recommended Claim

The strongest honest claim supported by this artifact is something like:

> We formalize a small abstract model of the VTRM decision core and
> mechanically check key safety properties over that model, including deny-no-effect
> and no-secret-to-external-sink.

That is strong enough to help the paper, while still being truthful about the
scope.
