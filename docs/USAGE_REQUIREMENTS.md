# AgentOS Usage Requirements

This document describes what a reviewer or collaborator needs in order to run
the current AgentOS artifact.

The current runnable artifact is **AgentOS-Eval**. It is the Buildroot/QEMU
evaluation image used by the World Effect Judge (WEJ), with VTRM enabled inside
the guest and benchmark support on the host. A separate **AgentOS-Clean** image
is part of the intended artifact structure, but it has not been split out as an
independent packaged image yet. Until that split is done, references to a
prebuilt image in this repository mean the AgentOS-Eval image.

---

## 1. Current Artifact Profile

### 1.1 AgentOS-Eval

`AgentOS-Eval` runs AgentOS inside QEMU and uses host-side infrastructure to
drive tasks, collect world-state snapshots, capture network effects, and
compare AgentOS against baseline modes.

It includes:

- Buildroot-based x86_64 guest image
- unprivileged `agent` runtime inside the guest
- typed tool requests
- VTRM-mediated file, network, and database effects
- QEMU boot orchestration
- repo-local host/guest bridge directory
- LLM proxy management
- baseline modes: `naive`, `cot`, and `agentos`
- WEJ snapshot and diff logic
- host-side HTTP sink for network exfiltration tests
- benchmark task suites and report generation
- optional Streamlit demonstration UI

The host-side bridge is repo-local by default:

```bash
/home/june/AgentOS/agentos/runtime/agent_bridge
```

Inside the guest, the same directory is mounted at:

```bash
/mnt/agent_bridge
```

### 1.2 Planned AgentOS-Clean Profile

`AgentOS-Clean` is the intended future secure runtime packaging: an AgentOS
image without WEJ benchmark scaffolding or baseline modes as user-facing
functionality. Conceptually, it should be able to run independently on x86_64
hardware or under QEMU, provided the deployment supplies an LLM connector path.

That clean profile is not the default packaged image today. The current
evaluation and demo commands use AgentOS-Eval.

---

## 2. Source Layout

Important paths:

| Path | Purpose |
|---|---|
| `/home/june/AgentOS/agentos` | AgentOS external tree, judge, docs, UI, formal model |
| `/home/june/AgentOS/agentos/artifacts/images/bzImage` | Packaged AgentOS-Eval kernel image |
| `/home/june/AgentOS/agentos/artifacts/images/rootfs.eval.clean.ext2` | Pristine AgentOS-Eval root filesystem used as reset source |
| `/home/june/AgentOS/agentos/runtime/rootfs.eval.ext2` | Mutable per-run root filesystem copied from the pristine image |
| `/home/june/AgentOS/agentos/runtime/agent_bridge` | Host-side bridge directory for evaluation |
| `/mnt/agent_bridge` | Guest-side mount point for the bridge inside AgentOS |
| `/home/june/AgentOS/buildroot-2026.02` | Buildroot tree, only needed for rebuilding or modifying the image |
| `/home/june/.config/agentos/api_key` | Default LLM API key file used by the evaluator |

---

## 3. Host Requirements

The recommended host environment is Linux or WSL2 with Ubuntu-like packages.

### 3.1 Required to Run AgentOS-Eval

To run the packaged evaluation artifact, reviewers need:

```bash
sudo apt-get update
sudo apt-get install -y python3 qemu-system-x86
```

The command-line evaluator mostly uses Python standard-library modules. It does
not require a large Python dependency stack.

The evaluator expects these packaged image files:

```bash
/home/june/AgentOS/agentos/artifacts/images/bzImage
/home/june/AgentOS/agentos/artifacts/images/rootfs.eval.clean.ext2
```

At the start of each evaluator run, the pristine root filesystem is copied to:

```bash
/home/june/AgentOS/agentos/runtime/rootfs.eval.ext2
```

This means ordinary benchmark resets do **not** require running Buildroot
`make`. Buildroot is only needed when rebuilding the OS image itself.

### 3.2 Required for Rebuilding the Image

If a reviewer wants to modify the guest OS and rebuild AgentOS-Eval from
source, they need the Buildroot host toolchain requirements:

```bash
sudo apt-get install -y \
  build-essential \
  git \
  make \
  gcc \
  g++ \
  patch \
  perl \
  python3 \
  python3-pip \
  rsync \
  unzip \
  bc \
  file \
  wget \
  cpio \
  gzip \
  bzip2 \
  xz-utils
```

Then rebuild from the Buildroot tree:

```bash
cd /home/june/AgentOS/buildroot-2026.02
env -i HOME="$HOME" TERM="$TERM" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin make
```

After rebuilding, refresh the packaged Eval image:

```bash
cd /home/june/AgentOS/agentos
mkdir -p artifacts/images runtime
cp /home/june/AgentOS/buildroot-2026.02/output/images/bzImage artifacts/images/bzImage
cp /home/june/AgentOS/buildroot-2026.02/output/images/rootfs.ext2 artifacts/images/rootfs.eval.clean.ext2
cp artifacts/images/rootfs.eval.clean.ext2 runtime/rootfs.eval.ext2
```

### 3.3 Required for the Streamlit UI

The Streamlit UI is optional but useful for demonstration:

```bash
python3 -m pip install -r /home/june/AgentOS/agentos/packages/requirements-streamlit-ui.txt
```

Current UI requirement file:

```text
streamlit>=1.44,<2
```

### 3.4 Required for the TLA+ Formal Artifact

The TLA+ model requires Java and `tla2tools.jar`.

```bash
sudo apt-get install -y default-jre
```

The current repository stores the jar at:

```bash
/home/june/AgentOS/agentos/packages/tla2tools.jar
```

---

## 4. Prepare the Bridge Directory

The repository includes the bridge layout with `.gitkeep` placeholders, so a
fresh checkout already has the expected directories:

```bash
/home/june/AgentOS/agentos/runtime/agent_bridge/inbox
/home/june/AgentOS/agentos/runtime/agent_bridge/outbox
/home/june/AgentOS/agentos/runtime/agent_bridge/done
/home/june/AgentOS/agentos/runtime/agent_bridge/error
/home/june/AgentOS/agentos/runtime/agent_bridge/tasks
```

If the directory was removed, recreate it with:

```bash
cd /home/june/AgentOS/agentos
mkdir -p runtime/agent_bridge/{inbox,outbox,done,error,tasks}
```

The evaluator cleans transient files in these directories before each case.

---

## 5. Configure the LLM API Key

By default, the evaluator reads:

```bash
/home/june/.config/agentos/api_key
```

Create it with:

```bash
mkdir -p /home/june/.config/agentos
printf '%s\n' 'YOUR_API_KEY_HERE' > /home/june/.config/agentos/api_key
chmod 600 /home/june/.config/agentos/api_key
```

Alternatively, pass `--api-key-file` to `judge/run_vtrm_eval.py`.

---

## 6. Run AgentOS-Eval

### 6.1 Run a Single Task

```bash
cd /home/june/AgentOS/agentos
python3 judge/run_vtrm_eval.py \
  --tasks-dir judge/tasks \
  --task-id 001-workspace-hello \
  --agent-mode agentos
```

The evaluator uses image-copy reset by default:

```text
artifacts/images/rootfs.eval.clean.ext2 -> runtime/rootfs.eval.ext2
```

### 6.2 Run the Benign Benchmark

```bash
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode naive --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode cot --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode agentos --reset-between-cases
```

### 6.3 Run the Malicious Benchmark

```bash
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/direct --agent-mode naive --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/injection --agent-mode naive --reset-between-cases

python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/direct --agent-mode cot --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/injection --agent-mode cot --reset-between-cases

python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/direct --agent-mode agentos --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_fail/injection --agent-mode agentos --reset-between-cases
```

### 6.4 Run the Streamlit UI

```bash
cd /home/june/AgentOS/agentos
python3 -m streamlit run /home/june/AgentOS/agentos/streamlit_app.py
```

The UI provides custom one-off task execution, benchmark suite execution, and
report browsing. It calls the same evaluator used in the paper, so demo runs
and benchmark runs share the same execution path.

---

## 7. Run the TLA+ Model

The formal artifact is optional for using AgentOS, but is part of the research
artifact.

Run TLC:

```bash
java -cp /home/june/AgentOS/agentos/packages/tla2tools.jar tlc2.TLC \
  -config /home/june/AgentOS/agentos/formal/vtrm_core.cfg \
  /home/june/AgentOS/agentos/formal/vtrm_core.tla
```

Expected successful result includes:

```text
Model checking completed. No error has been found.
```

---

## 8. Minimal Package Checklist

Required to run the current AgentOS-Eval artifact:

- Linux or WSL2 host
- `python3`
- `qemu-system-x86`
- packaged Eval kernel and pristine root filesystem under `artifacts/images`
- writable repo-local bridge directory under `runtime/agent_bridge`
- LLM API key

Required only for optional image rebuilding:

- Buildroot host dependencies
- Buildroot tree at `/home/june/AgentOS/buildroot-2026.02`

Optional:

- `streamlit` for UI
- Java + `tla2tools.jar` for TLA+ model checking

---

## 9. Practical Notes

1. `AgentOS-Eval` is VM-based because WEJ needs a controlled resettable guest
   world state.
2. The evaluator resets by copying a pristine root filesystem image, not by
   rerunning Buildroot `make`.
3. `--reset-between-cases` should be used for benchmark suites to avoid
   cross-case contamination after each case.
4. A fresh evaluator run also starts by copying the pristine image, so the first
   case does not inherit a dirty runtime image.
5. The host-side bridge directory is repo-local by default, but the guest-side
   mount point remains `/mnt/agent_bridge`.
6. Network tests rely on QEMU user networking, where the guest reaches the host
   at `10.0.2.2`.
7. Network exfiltration tests use a fixed host sink port: `18080`.
8. The command-line evaluator is the source of truth. The Streamlit UI is a
   convenience wrapper around it.
