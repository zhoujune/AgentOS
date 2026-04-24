# Should-Pass Task Suite

This directory contains benign utility tasks that should complete successfully
without causing any forbidden world effects.

Intended use:

- compare benign completion across `naive`, `cot`, and `agentos`
- pair with `judge/tasks_should_fail` for a utility-vs-safety evaluation

Recommended run commands:

```bash
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode naive --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode cot --reset-between-cases
python3 judge/run_vtrm_eval.py --tasks-dir judge/tasks_should_pass --agent-mode agentos --reset-between-cases
```
