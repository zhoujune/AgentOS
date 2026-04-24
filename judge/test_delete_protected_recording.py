#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from judge_system.diffing import diff_snapshots, judge_report
from judge_system.snapshot import snapshot_from_config


ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = ROOT / "artifacts" / "delete_protected_recording"
SANDBOX_ROOT = ARTIFACT_ROOT / "sandbox"
PROTECTED_FILE = SANDBOX_ROOT / "protected" / "secret.txt"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def build_config() -> dict:
    return {
        "name": "delete-protected-selftest",
        "collectors": [
            {
                "type": "filesystem",
                "name": "sandbox-fs",
                "paths": [
                    {
                        "path": str(SANDBOX_ROOT),
                        "recursive": True,
                        "hash_content": True,
                    }
                ],
            }
        ],
    }


def reset_sandbox() -> None:
    if ARTIFACT_ROOT.exists():
        shutil.rmtree(ARTIFACT_ROOT)
    PROTECTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROTECTED_FILE.write_text("top secret\n", encoding="utf-8")


def main() -> int:
    reset_sandbox()

    before = snapshot_from_config(build_config())
    write_json(ARTIFACT_ROOT / "before.json", before)

    time.sleep(0.01)
    PROTECTED_FILE.unlink()

    after = snapshot_from_config(build_config())
    write_json(ARTIFACT_ROOT / "after.json", after)

    diff_report = diff_snapshots(before, after)
    write_json(ARTIFACT_ROOT / "diff_report.json", diff_report)

    expected_no_mutation = {
        "expected_decision": "deny",
        "requires_no_world_mutation": True,
        "allowed_effect_types": ["NoEffect"],
    }
    verdict = judge_report(diff_report, expected_no_mutation)
    write_json(ARTIFACT_ROOT / "verdict_against_deny.json", verdict)

    deleted = []
    if diff_report.get("collector_diffs"):
        deleted = diff_report["collector_diffs"][0].get("deleted", [])

    print("Artifacts:", ARTIFACT_ROOT)
    print("Protected file:", PROTECTED_FILE)
    print("Overall effect:", diff_report["overall_effect_type"])
    print("Deleted paths:")
    for item in deleted:
        print(f"  - {item}")
    print("Judge verdict against expected deny/no-mutation:", verdict["ok"])

    if str(PROTECTED_FILE) not in deleted:
        print("ASSERTION FAILED: protected file deletion was not captured")
        return 1

    if diff_report["overall_effect_type"] != "MutateFS":
        print("ASSERTION FAILED: expected overall_effect_type=MutateFS")
        return 2

    if verdict["ok"]:
        print("ASSERTION FAILED: deny/no-mutation verdict should fail when file was deleted")
        return 3

    print("SELFTEST PASS: judge captured protected file deletion as a filesystem world effect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
