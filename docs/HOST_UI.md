# Host UI

This repository includes a host-side Streamlit UI for showcasing normal usage
and benchmark runs with the same underlying harness used in evaluation.

Main entrypoint:

- [streamlit_app.py](/home/june/AgentOS/agentos/streamlit_app.py)

## Install

```bash
python3 -m pip install -r /home/june/AgentOS/agentos/packages/requirements-streamlit-ui.txt
```

## Run

```bash
cd /home/june/AgentOS/agentos
python3 -m streamlit run /home/june/AgentOS/agentos/streamlit_app.py
```

## What It Does

- `Custom Task` tab:
  - creates a temporary one-off task JSON
  - runs it through `judge/run_vtrm_eval.py`
  - shows final task answer and report artifacts

- `Benchmark` tab:
  - runs an existing task suite such as:
    - `judge/tasks`
    - `judge/tasks_should_pass`
    - `judge/tasks_should_fail/direct`
    - `judge/tasks_should_fail/injection`
  - compares one or more modes (`agentos`, `cot`, `naive`)

- `Reports` tab:
  - browses recent report directories under `judge/reports`
  - displays `summary.json`, case rows, and `summary.md`

## Design Note

The UI intentionally reuses the existing judge harness rather than introducing
a separate execution path. That keeps demo results and paper results aligned.

The current runnable image is the AgentOS-Eval image. The harness resets it by
copying:

```bash
/home/june/AgentOS/agentos/artifacts/images/rootfs.eval.clean.ext2
```

to the mutable runtime image:

```bash
/home/june/AgentOS/agentos/runtime/rootfs.eval.ext2
```

so normal UI and benchmark runs do not need to rerun Buildroot `make`.

By default, the harness uses the repo-local host bridge directory:

```bash
/home/june/AgentOS/agentos/runtime/agent_bridge
```

with standard bridge subdirectories:

```bash
inbox/
outbox/
done/
error/
tasks/
```

Inside the guest VM this directory is still mounted as:

```bash
/mnt/agent_bridge
```
