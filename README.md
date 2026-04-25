# AgentOS

AgentOS is a sandboxed agent runtime for secure tool use. It runs an LLM-driven agent inside a Buildroot-based x86 guest and mediates all tool requests through the Verified Toolchain Reference Monitor (VTRM). The repository also includes a reproducible evaluation harness based on QEMU, a host-side LLM proxy, and a Streamlit interface for demos and benchmarks.

## Artefacts

AgentOS is organized around two runnable artefacts.

- `AgentOS-Prod`
  - Deployment-oriented runtime profile.
  - Reuses the same agent, wrappers, and VTRM enforcement logic as the evaluation build.
  - Packaged as `artifacts/images/rootfs.prod.ext2`.
- `AgentOS-Eval`
  - Reproducible evaluation profile used for the paper.
  - Runs in QEMU with host-managed reset, bridge directories, network observation, and world-state checking.
  - Packaged primarily as `artifacts/images/rootfs.eval.clean.ext2`.

The two profiles come from the same codebase. `Prod` prunes eval-only fixtures and test files, while `Eval` keeps the full benchmark environment.

## Repository Layout

- `artifacts/images/`
  - Built kernel and root filesystem images.
- `br2-external/`
  - Buildroot external tree with the guest overlay, runtime scripts, VTRM modules, and boot configuration.
- `judge/`
  - Evaluation harness, benchmark suites, reports, and the World Effect Judge.
- `host_ui/`
  - Host-side helpers used by the Streamlit interface.
- `scripts/build/`
  - Image preparation helpers such as `make_prod_image.sh`.
- `scripts/qemu/`
  - One-command QEMU launch scripts.
- `scripts/test/`
  - Smoke tests for built images.
- `streamlit_app.py`
  - Host UI for demos, benchmarks, and report browsing.
- `llm_proxy.py`
  - Host-side LLM proxy used by the guest runtime.

## Runtime Architecture

At a high level:

1. The guest agent runs inside a Buildroot-based x86 environment.
2. The guest writes structured LLM requests to a shared bridge directory.
3. The host-side `llm_proxy.py` forwards those requests to the configured model API.
4. The guest agent uses wrapper scripts under `/opt/sandbox/bin/`.
5. VTRM classifies requested effects and enforces policy before tool actions execute.
6. In evaluation mode, the host also records before/after state and checks outcomes with the World Effect Judge.

The evaluation profile uses a shared-folder bridge because it is convenient for orchestration and reproducibility. The production profile keeps the same runtime logic and is intended as the deployment-oriented image.

## Prerequisites

The typical host setup is:

- Ubuntu or another Linux environment capable of running:
  - `python3`
  - `qemu-system-x86_64`
  - `debugfs`
  - `e2fsck`
  - `make`
- this repository checked out locally as `agentos`

Important:

- this repository contains the `AgentOS/agentos` codebase and Buildroot external tree
- it does not include the full `buildroot-2026.02` source checkout
- if you want to rebuild the guest images, you must download or prepare a compatible Buildroot tree yourself and place it next to this repository

Expected rebuild layout:

- `agentos/`
  - this repository
- `buildroot-2026.02/`
  - separately obtained Buildroot source tree

For model access, create an API key file, for example:

```bash
mkdir -p ~/.config/agentos
printf '%s\n' 'YOUR_API_KEY_HERE' > ~/.config/agentos/api_key
chmod 600 ~/.config/agentos/api_key
```

The default UI configuration uses:

- model: `kimi-k2-0905-preview`
- API style: `openai`
- endpoint: `https://api.moonshot.cn/v1/chat/completions`
- temperature: `0.0`

You can also switch the UI and harness to OpenAI-compatible or Anthropic-native endpoints.

## Build the Images

If you only want to run the supplied artefacts, you do not need to rebuild anything. The prebuilt images are already under:

- `artifacts/images/bzImage`
- `artifacts/images/rootfs.eval.clean.ext2`
- `artifacts/images/rootfs.prod.ext2`

Rebuilding is only needed if you want to modify the guest runtime, wrappers, boot scripts, or VTRM implementation.

### 1. Prepare Buildroot separately

Before rebuilding, obtain a compatible Buildroot checkout yourself. This repository does not vendor the full Buildroot tree. The examples below assume that Buildroot has been placed at:

- `../buildroot-2026.02`

### 2. Rebuild the base Buildroot image

After the separate Buildroot tree is available, rebuild with:

```bash
cd ../buildroot-2026.02
env -i HOME="$HOME" TERM="$TERM" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin make
```

### 3. Refresh the AgentOS image copies

Then copy the rebuilt outputs into the AgentOS artefact locations:

```bash
cd agentos
cp --reflink=auto ../buildroot-2026.02/output/images/bzImage artifacts/images/bzImage
cp --reflink=auto ../buildroot-2026.02/output/images/rootfs.ext2 artifacts/images/rootfs.eval.clean.ext2
cp --reflink=auto artifacts/images/rootfs.eval.clean.ext2 runtime/rootfs.eval.ext2
```

### 4. Produce the deployment-oriented image

To derive `AgentOS-Prod` from the refreshed eval image:

```bash
cd agentos
./scripts/build/make_prod_image.sh
```

This creates:

- `artifacts/images/rootfs.prod.ext2`

## Validate the Images

Smoke-test the production image:

```bash
cd agentos
./scripts/test/test_prod_image.sh
```

Boot the production image manually:

```bash
cd agentos
./scripts/qemu/run_prod_vm.sh
```

## Run the Streamlit Host UI

The simplest way to demo the system is through the host UI:

```bash
cd agentos
python3 -m streamlit run streamlit_app.py
```

The UI supports:

- one-off custom tasks through the full QEMU + bridge + VTRM + WEJ path
- benchmark runs for `should_pass` and `should_fail` suites
- custom LLM providers and endpoints
- a `Test LLM Connection` button
- report browsing for completed runs

Suggested first-use workflow:

1. Open the Streamlit UI.
2. Confirm the API style, endpoint, model, and API key path in the sidebar.
3. Click `Test LLM Connection`.
4. Run a simple custom task in `agentos` mode.
5. Move on to benchmark suites once the smoke test succeeds.

## Run the Evaluation Harness Directly

### One benign task

```bash
cd agentos
python3 judge/run_vtrm_eval.py \
  --tasks-dir judge/tasks_should_pass \
  --agent-mode agentos \
  --reset-between-cases \
  --task-id 323-delete-nested-workspace-cache
```

### One should-fail task

```bash
cd agentos
python3 judge/run_vtrm_eval.py \
  --tasks-dir judge/tasks_should_fail/direct \
  --agent-mode agentos \
  --reset-between-cases \
  --task-id 121-direct-protected-file-delete
```

### Full benchmark suite through the harness

```bash
cd agentos
python3 judge/run_vtrm_eval.py \
  --tasks-dir judge/tasks_should_fail/injection \
  --agent-mode agentos \
  --reset-between-cases
```

Useful options:

- `--agent-mode agentos|cot|naive`
- `--model <name>`
- `--api-style openai|anthropic`
- `--api-endpoint <url>`
- `--temperature <value>`
- `--task-timeout <seconds>`
- `--vm-boot-timeout <seconds>`

## Common Workflows

### Custom demo through the UI

Use this when you want to show the system interactively:

- start Streamlit
- test the LLM connection
- create a one-off task
- run in `agentos` mode
- inspect the final answer and, if needed, open the report details

### Paper benchmark run

Use this when you want reproducible results:

- rebuild the image if the guest overlay changed
- refresh `artifacts/images/` and `runtime/rootfs.eval.ext2`
- run the benchmark through Streamlit or `judge/run_vtrm_eval.py`
- inspect `judge/reports/<run_id>/summary.json`

### Production image check

Use this when you want to verify the deployment-oriented profile:

- run `./scripts/build/make_prod_image.sh`
- run `./scripts/test/test_prod_image.sh`
- optionally boot with `./scripts/qemu/run_prod_vm.sh`

## Key Guest-Side Components

Important guest files include:

- `/home/agent/agent_runner.py`
  - main LLM-agent runtime
- `/home/agent/agent_main_loop.sh`
  - task pickup loop used by the evaluation path
- `/home/agent/vtrm/`
  - VTRM enforcement and classification logic
- `/opt/sandbox/bin/*.sh`
  - wrapper scripts for controlled file, shell, process, network, logging, SQLite, cron, and service operations

## Reports and Logs

Evaluation runs are written under:

- `judge/reports/`

Typical files of interest:

- `summary.json`
- `summary.md`
- `<task_id>/case_report.json`
- `<task_id>/qemu.log`
- `<task_id>/llm_proxy.log`

Inside the guest, common logs include:

- `/var/log/sandbox/agent/transcript.jsonl`
- `/var/log/sandbox/trace/trace.jsonl`
- `/var/log/sandbox/agent/judge_main_loop.log`

## Troubleshooting

### The UI says the LLM connection failed

Check:

- the API key file exists and is readable
- the selected API style matches the provider
- the endpoint is correct for that provider
- the model name is valid for the selected backend

### QEMU boots but no task is processed

Check:

- `runtime/rootfs.eval.ext2` was refreshed from `artifacts/images/rootfs.eval.clean.ext2`
- the shared bridge directory exists under `runtime/agent_bridge`
- the run report contains `qemu.log` and `llm_proxy.log`

### The prod image fails a smoke test after overlay changes

Rebuild and regenerate:

```bash
cd ../buildroot-2026.02
env -i HOME="$HOME" TERM="$TERM" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin make

cd ../agentos
cp --reflink=auto ../buildroot-2026.02/output/images/bzImage artifacts/images/bzImage
cp --reflink=auto ../buildroot-2026.02/output/images/rootfs.ext2 artifacts/images/rootfs.eval.clean.ext2
./scripts/build/make_prod_image.sh
./scripts/test/test_prod_image.sh
```

