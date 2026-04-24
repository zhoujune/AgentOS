#!/usr/bin/env python3
"""
Direct API-level tests for the unfinished part of test_vtrm.sh.

This script is intentionally separate from test_vtrm.sh so we can debug the
remaining VTRM behaviors without going through agent_runner or the bridge LLM.

Design goals:
- no cleanup of existing files or logs
- use the same global VTRM output locations as the existing tests
- keep sample payload files isolated under a unique workspace subdirectory
- keep output simple and grep-friendly
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


RUN_ID = time.strftime("%Y%m%d-%H%M%S")
SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = SCRIPT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from vtrm import Label, NetworkPolicy, VTRMCore  # noqa: E402


WORKSPACE_DIR = Path("/workspace")
SECRETS_DIR = Path("/secrets")
PROTECTED_DIR = Path("/protected")
ARTIFACT_ROOT = WORKSPACE_DIR / "vtrm_remaining_artifacts" / RUN_ID

VTRM_LOG_DIR = Path(os.environ.get("VTRM_LOG_DIR", "/var/log/sandbox/vtrm"))
VTRM_APPROVAL_DIR = Path(os.environ.get("VTRM_APPROVAL_DIR", "/var/lib/agentos/approvals"))
VTRM_DB_PATH = Path(os.environ.get("VTRM_DB_PATH", "/var/lib/agentos/agent.db"))

SECRET_FILE_READ_TASK_ID = "test-vtrm-remaining-secret-read-001"
DB_SECRET_READ_TASK_ID = "test-vtrm-remaining-db-secret-read-001"
ABS_DENY_SECRET_EXTERNAL_TASK_ID = "test-vtrm-remaining-abs-deny-secret-external-001"
SCHEMA_MISSING_ARGS_TASK_ID = "test-vtrm-remaining-schema-missing-args-001"
SCHEMA_MISSING_PATH_TASK_ID = "test-vtrm-remaining-schema-missing-path-001"
SCHEMA_WRONG_TYPE_TASK_ID = "test-vtrm-remaining-schema-wrong-type-001"
SCHEMA_UNKNOWN_TOOL_TASK_ID = "test-vtrm-remaining-schema-unknown-tool-001"
AUDIT_FAIL_CLOSED_TASK_ID = "test-vtrm-remaining-audit-fail-001"

AGENT_CAPABILITIES = {
    "fs.read.workspace",
    "fs.read.readonly",
    "fs.read.secret",
    "fs.read.protected",
    "fs.write.workspace",
    "network.send.trusted_internal",
    "network.send.external",
    "db.read.readonly",
    "db.read.secret",
    "db.read.audit",
    "db.insert.mutable",
    "db.update.mutable",
}


def print_section(title: str) -> None:
    print()
    print("=" * 20, title, "=" * 20)


def pass_msg(name: str, detail: str = "") -> bool:
    line = f"[PASS] {name}"
    if detail:
        line += f" - {detail}"
    print(line)
    return True


def fail_msg(name: str, detail: str) -> bool:
    print(f"[FAIL] {name}: {detail}")
    return False


def setup_dirs() -> None:
    for path in (
        WORKSPACE_DIR,
        SECRETS_DIR,
        PROTECTED_DIR,
        ARTIFACT_ROOT,
        VTRM_LOG_DIR,
        VTRM_APPROVAL_DIR / "pending",
        VTRM_APPROVAL_DIR / "approved",
        VTRM_APPROVAL_DIR / "used",
        VTRM_APPROVAL_DIR / "tokens",
        VTRM_DB_PATH.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)


def create_vtrm(
    *,
    audit_dir: Path = VTRM_LOG_DIR,
    approval_dir: Path = VTRM_APPROVAL_DIR,
    db_path: Path = VTRM_DB_PATH,
    capabilities: Optional[Set[str]] = None,
) -> VTRMCore:
    os.environ["VTRM_DB_PATH"] = str(db_path)
    return VTRMCore(
        agent_capabilities=capabilities or AGENT_CAPABILITIES,
        allowed_external_sinks=set(),
        audit_log_dir=str(audit_dir),
        approval_store_dir=str(approval_dir),
    )


def make_request(tool: str, args: Dict[str, Any], task_id: str, request_id: str) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "request_id": request_id,
        "subject": "agent.default",
        "tool": tool,
        "args": args,
    }


def iter_audit_events(task_id: str, audit_dir: Path = VTRM_LOG_DIR) -> Iterable[Dict[str, Any]]:
    for path in sorted(audit_dir.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("task_id") == task_id:
                        yield event
        except OSError:
            continue


def require_event(
    task_id: str,
    name: str,
    predicate: Callable[[Dict[str, Any]], bool],
    audit_dir: Path = VTRM_LOG_DIR,
) -> bool:
    for event in iter_audit_events(task_id, audit_dir):
        if predicate(event):
            return True
    return fail_msg(name, f"missing expected audit event for task_id={task_id}")


def test_secret_file_read_requires_approval(vtrm: VTRMCore) -> bool:
    name = "B1 secret file read -> approval_required"
    secret_path = SECRETS_DIR / f"remaining-secret-read-{RUN_ID}.txt"
    secret_path.write_text("secret material for approval", encoding="utf-8")

    request = make_request(
        "fs.read",
        {"path": str(secret_path)},
        SECRET_FILE_READ_TASK_ID,
        "req-secret-read-001",
    )
    decision = vtrm.evaluate(request, runtime_task_id=SECRET_FILE_READ_TASK_ID, step_index=1)

    if decision.decision != "approval_required":
        return fail_msg(name, f"expected approval_required, got {decision.decision} ({decision.reason})")
    if not decision.approval_id:
        return fail_msg(name, "decision is missing approval_id")
    if decision.inferred_label != "secret/high":
        return fail_msg(name, f"expected inferred_label=secret/high, got {decision.inferred_label}")

    pending_path = VTRM_APPROVAL_DIR / "pending" / f"{decision.approval_id}.json"
    if not pending_path.exists():
        return fail_msg(name, f"missing pending approval file: {pending_path}")

    if require_event(
        SECRET_FILE_READ_TASK_ID,
        name,
        lambda event: event.get("decision") == "approval_required"
        and event.get("status") == "pending"
        and event.get("tool") == "fs.read"
        and event.get("approval_id") == decision.approval_id,
    ) is not True:
        return False

    return pass_msg(name, f"approval_id={decision.approval_id}")


def test_db_secret_read_requires_approval(vtrm: VTRMCore) -> bool:
    name = "C1 db.read secret -> approval_required"
    VTRM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import sqlite3
    except ImportError:
        return pass_msg(name, "SKIPPED (sqlite3 not available)")

    with sqlite3.connect(VTRM_DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS secrets (id TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO secrets (id, value) VALUES (?, ?)",
            ("remaining-secret-key", "db secret value"),
        )
        conn.commit()

    request = make_request(
        "db.read",
        {"table": "secrets", "key": "remaining-secret-key"},
        DB_SECRET_READ_TASK_ID,
        "req-db-secret-read-001",
    )
    decision = vtrm.evaluate(request, runtime_task_id=DB_SECRET_READ_TASK_ID, step_index=1)

    if decision.decision != "approval_required":
        return fail_msg(name, f"expected approval_required, got {decision.decision} ({decision.reason})")
    if not decision.approval_id:
        return fail_msg(name, "decision is missing approval_id")
    if decision.inferred_label != "secret/high":
        return fail_msg(name, f"expected inferred_label=secret/high, got {decision.inferred_label}")

    if require_event(
        DB_SECRET_READ_TASK_ID,
        name,
        lambda event: event.get("decision") == "approval_required"
        and event.get("status") == "pending"
        and event.get("tool") == "db.read",
    ) is not True:
        return False

    return pass_msg(name, f"approval_id={decision.approval_id}")


def test_secret_to_external_absolute_deny() -> bool:
    name = "E secret/high -> external_untrusted absolute deny"
    network_policy = NetworkPolicy()
    result = network_policy.check(
        url="https://evil.example/collect",
        content_label=Label.SECRET_HIGH,
    )

    if result.decision.value != "deny":
        return fail_msg(name, f"expected deny, got {result.decision.value} ({result.reason})")
    if result.rule != "secret_to_external":
        return fail_msg(name, f"expected rule=secret_to_external, got {result.rule}")

    return pass_msg(name, result.reason)


def test_schema_invalid_cases(vtrm: VTRMCore) -> List[Tuple[str, bool]]:
    cases: List[Tuple[str, Dict[str, Any], str]] = [
        (
            "F1 schema invalid missing args",
            {
                "task_id": SCHEMA_MISSING_ARGS_TASK_ID,
                "request_id": "req-schema-missing-args-001",
                "subject": "agent.default",
                "tool": "fs.read",
            },
            SCHEMA_MISSING_ARGS_TASK_ID,
        ),
        (
            "F2 schema invalid missing path",
            make_request("fs.read", {}, SCHEMA_MISSING_PATH_TASK_ID, "req-schema-missing-path-001"),
            SCHEMA_MISSING_PATH_TASK_ID,
        ),
        (
            "F3 schema invalid wrong args type",
            {
                "task_id": SCHEMA_WRONG_TYPE_TASK_ID,
                "request_id": "req-schema-wrong-type-001",
                "subject": "agent.default",
                "tool": "fs.read",
                "args": "not-a-dict",
            },
            SCHEMA_WRONG_TYPE_TASK_ID,
        ),
        (
            "F4 schema invalid unknown tool",
            make_request("unknown.tool", {}, SCHEMA_UNKNOWN_TOOL_TASK_ID, "req-schema-unknown-tool-001"),
            SCHEMA_UNKNOWN_TOOL_TASK_ID,
        ),
    ]

    results: List[Tuple[str, bool]] = []
    for name, request, task_id in cases:
        decision = vtrm.evaluate(request, runtime_task_id=task_id, step_index=1)
        if decision.decision != "deny":
            results.append((name, fail_msg(name, f"expected deny, got {decision.decision} ({decision.reason})")))
            continue

        if require_event(
            task_id,
            name,
            lambda event: event.get("decision") == "deny" and event.get("status") == "skipped",
        ) is not True:
            results.append((name, False))
            continue

        results.append((name, pass_msg(name, decision.reason)))

    return results


def test_audit_fail_closed() -> bool:
    name = "G audit fail-closed for mutation"
    fail_closed_vtrm = create_vtrm(
        audit_dir=VTRM_LOG_DIR,
        approval_dir=VTRM_APPROVAL_DIR,
        db_path=VTRM_DB_PATH,
    )
    fail_closed_vtrm.audit_logger._audit_available = False
    target_path = WORKSPACE_DIR / f"remaining-audit-fail-closed-{RUN_ID}.txt"
    request = make_request(
        "fs.write",
        {"path": str(target_path), "content": "should-not-be-written"},
        AUDIT_FAIL_CLOSED_TASK_ID,
        "req-audit-fail-001",
    )

    success, result = fail_closed_vtrm.execute(
        request,
        runtime_task_id=AUDIT_FAIL_CLOSED_TASK_ID,
        step_index=1,
    )

    if success:
        return fail_msg(name, f"expected failure, got success result={result}")
    if "fail-closed" not in str(result):
        return fail_msg(name, f"expected fail-closed error, got {result}")
    if target_path.exists():
        return fail_msg(name, f"mutation unexpectedly created {target_path}")

    return pass_msg(name, str(result))


def run_tests() -> bool:
    setup_dirs()
    vtrm = create_vtrm()

    print_section("Artifacts")
    print(f"RUN_ID={RUN_ID}")
    print(f"ARTIFACT_ROOT={ARTIFACT_ROOT}")
    print(f"VTRM_LOG_DIR={VTRM_LOG_DIR}")
    print(f"VTRM_APPROVAL_DIR={VTRM_APPROVAL_DIR}")
    print(f"VTRM_DB_PATH={VTRM_DB_PATH}")

    results: List[Tuple[str, bool]] = []

    print_section("Approval")
    results.append(("B1", test_secret_file_read_requires_approval(vtrm)))
    results.append(("C1", test_db_secret_read_requires_approval(vtrm)))

    print_section("Absolute Deny")
    results.append(("E", test_secret_to_external_absolute_deny()))

    print_section("Schema Invalid")
    results.extend(test_schema_invalid_cases(vtrm))

    print_section("Fail Closed")
    results.append(("G", test_audit_fail_closed()))

    print_section("Summary")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"Passed {passed}/{total}")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
