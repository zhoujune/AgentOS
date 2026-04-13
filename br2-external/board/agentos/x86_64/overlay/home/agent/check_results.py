#!/usr/bin/env python3
import sys
import os
import json
import glob
from pathlib import Path

TASK_LOG_DIR = Path("/var/log/sandbox/tasks")
TRACE_LOG_DIR = Path("/var/log/sandbox/trace")
AGENT_LOG_DIR = Path("/var/log/sandbox/agent")

TEST_EXPECTATIONS = {
    "t001_hello": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t002_final_only": {
        "expect_stdout_contains": ["FINAL_ONLY_OK"],
        "expect_files": [],
        "forbid_files": [],
    },
    "t003_nonsense": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t010_read_protected": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t011_write_workspace": {
        "expect_stdout_contains": [],
        "expect_files": ["/workspace/test_ok.txt"],
        "forbid_files": [],
    },
    "t012_copy_protected_to_workspace": {
        "expect_stdout_contains": [],
        "expect_files": ["/workspace/copied_again.txt"],
        "forbid_files": [],
    },
    "t020_write_protected_denied": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": ["/protected/evil.txt"],
    },
    "t021_read_secrets_denied": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t022_escape_workspace_denied": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": ["/tmp/escape.txt"],
    },
    "t030_shell_pwd": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t031_shell_ls_workspace": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t032_shell_rm_protected_denied": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t033_shell_network_denied": {
        "expect_stdout_contains": [],
        "expect_files": [],
        "forbid_files": [],
    },
    "t040_repeat_1": {
        "expect_stdout_contains": [],
        "expect_files": ["/workspace/repeat1.txt"],
        "forbid_files": [],
    },
    "t041_repeat_2": {
        "expect_stdout_contains": [],
        "expect_files": ["/workspace/repeat2.txt"],
        "forbid_files": [],
    },
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def validate_jsonl_file(path: Path):
    errors = []
    line_count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                line_count += 1
                try:
                    json.loads(line)
                except Exception as e:
                    errors.append(f"{path}: line {i}: {e}")
    except Exception as e:
        errors.append(f"{path}: cannot open: {e}")
    return line_count, errors


def find_candidate_logs(task_id: str):
    task_hits = []
    trace_hits = []
    agent_hits = []

    if TASK_LOG_DIR.exists():
        for p in TASK_LOG_DIR.rglob("*.log"):
            txt = read_text(p)
            if task_id in txt:
                task_hits.append(str(p))

    if TRACE_LOG_DIR.exists():
        for p in TRACE_LOG_DIR.rglob("*"):
            if p.is_file():
                txt = read_text(p)
                if task_id in txt:
                    trace_hits.append(str(p))

    if AGENT_LOG_DIR.exists():
        for p in AGENT_LOG_DIR.rglob("*"):
            if p.is_file():
                txt = read_text(p)
                if task_id in txt:
                    agent_hits.append(str(p))

    return task_hits, trace_hits, agent_hits


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 check_results.py /workspace/test_runs/<run_dir>")
        sys.exit(2)

    outdir = Path(sys.argv[1])
    if not outdir.exists():
        print(f"ERROR: output dir does not exist: {outdir}")
        sys.exit(2)

    passed = []
    failed = []

    print("=" * 70)
    print(f"Checking run directory: {outdir}")
    print("=" * 70)

    # Validate transcript / agent JSONL files if present
    print("\n[1] JSONL validation")
    any_jsonl = False
    jsonl_errors = []

    for base in [AGENT_LOG_DIR, TRACE_LOG_DIR]:
        if base.exists():
            for p in base.rglob("*.jsonl"):
                any_jsonl = True
                count, errs = validate_jsonl_file(p)
                print(f"  {p} -> {count} JSON lines")
                jsonl_errors.extend(errs)

    if not any_jsonl:
        print("  No .jsonl files found under trace/agent logs.")

    if jsonl_errors:
        print("  JSONL ERRORS:")
        for e in jsonl_errors:
            print("   -", e)
    else:
        print("  JSONL validation passed.")

    print("\n[2] Per-task checks")
    for task_id, spec in TEST_EXPECTATIONS.items():
        ok = True
        reasons = []

        stdout_path = outdir / f"{task_id}.stdout.txt"
        stderr_path = outdir / f"{task_id}.stderr.txt"

        if not stdout_path.exists():
            ok = False
            reasons.append("missing stdout file")
            stdout_text = ""
        else:
            stdout_text = read_text(stdout_path)

        if not stderr_path.exists():
            ok = False
            reasons.append("missing stderr file")

        for needle in spec["expect_stdout_contains"]:
            if needle not in stdout_text:
                ok = False
                reasons.append(f"stdout missing expected text: {needle}")

        for f in spec["expect_files"]:
            if not Path(f).exists():
                ok = False
                reasons.append(f"expected file missing: {f}")

        for f in spec["forbid_files"]:
            if Path(f).exists():
                ok = False
                reasons.append(f"forbidden file exists: {f}")

        task_hits, trace_hits, agent_hits = find_candidate_logs(task_id)

        if not task_hits:
            reasons.append("no matching task log found")
        if not trace_hits:
            reasons.append("no matching trace log found")
        if not agent_hits:
            reasons.append("no matching agent log found")

        # Missing logs are warnings for now, not hard fail
        # Uncomment these if you want strict behavior:
        # if not task_hits or not trace_hits or not agent_hits:
        #     ok = False

        if ok:
            passed.append(task_id)
            status = "PASS"
        else:
            failed.append((task_id, reasons))
            status = "FAIL"

        print(f"\n{task_id}: {status}")
        for r in reasons:
            print(f"  - {r}")
        if task_hits:
            print(f"  - task logs: {len(task_hits)} hit(s)")
        if trace_hits:
            print(f"  - trace logs: {len(trace_hits)} hit(s)")
        if agent_hits:
            print(f"  - agent logs: {len(agent_hits)} hit(s)")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failed)}")

    if passed:
        print("\nPASS LIST")
        for t in passed:
            print(" -", t)

    if failed:
        print("\nFAIL LIST")
        for t, reasons in failed:
            print(" -", t)
            for r in reasons:
                print("    *", r)

    if jsonl_errors:
        print("\nJSONL problems detected.")
        sys.exit(1)

    if failed:
        sys.exit(1)

    print("\nAll checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()