from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _index_entries(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {entry["path"]: entry for entry in entries}


def diff_filesystem(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_map = _index_entries(before.get("entries", []))
    after_map = _index_entries(after.get("entries", []))

    created: List[str] = []
    deleted: List[str] = []
    modified: List[Dict[str, Any]] = []

    for path, after_entry in after_map.items():
        if path not in before_map:
            created.append(path)
            continue
        before_entry = before_map[path]
        if before_entry != after_entry:
            modified.append(
                {
                    "path": path,
                    "before": before_entry,
                    "after": after_entry,
                }
            )

    for path in before_map:
        if path not in after_map:
            deleted.append(path)

    changed = bool(created or deleted or modified)
    return {
        "type": "filesystem",
        "name": after["name"],
        "changed": changed,
        "created": sorted(created),
        "deleted": sorted(deleted),
        "modified": modified,
        "effect_type": "MutateFS" if changed else "NoEffect",
    }


def diff_sqlite(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    if before.get("exists") != after.get("exists"):
        changed = True
    else:
        changed = before.get("file_sha256") != after.get("file_sha256")

    before_tables = {item["table"]: item for item in before.get("tables", [])}
    after_tables = {item["table"]: item for item in after.get("tables", [])}
    table_changes: List[Dict[str, Any]] = []
    for table_name in sorted(set(before_tables) | set(after_tables)):
        if before_tables.get(table_name) != after_tables.get(table_name):
            table_changes.append(
                {
                    "table": table_name,
                    "before": before_tables.get(table_name),
                    "after": after_tables.get(table_name),
                }
            )

    return {
        "type": "sqlite",
        "name": after["name"],
        "changed": changed,
        "table_changes": table_changes,
        "effect_type": "MutateDB" if changed else "NoEffect",
    }


def diff_http_sink(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_count = int(before.get("event_count", 0))
    after_count = int(after.get("event_count", 0))
    new_events = after.get("events", [])[before_count:]
    changed = after_count > before_count
    return {
        "type": "http_sink",
        "name": after["name"],
        "changed": changed,
        "new_event_count": max(0, after_count - before_count),
        "new_events": new_events,
        "effect_type": "SendNetwork" if changed else "NoEffect",
    }


def _overall_effect(kinds: List[str]) -> str:
    unique = {kind for kind in kinds if kind != "NoEffect"}
    if not unique:
        return "NoEffect"
    if len(unique) == 1:
        return next(iter(unique))
    return "CompositeEffect"


def diff_snapshots(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_collectors = {(c["type"], c["name"]): c for c in before.get("collectors", [])}
    after_collectors = {(c["type"], c["name"]): c for c in after.get("collectors", [])}

    collector_diffs: List[Dict[str, Any]] = []
    effect_kinds: List[str] = []

    for key, after_collector in after_collectors.items():
        before_collector = before_collectors.get(key)
        if before_collector is None:
            raise ValueError(f"Collector missing in before snapshot: {key}")

        collector_type, _ = key
        if collector_type == "filesystem":
            result = diff_filesystem(before_collector, after_collector)
        elif collector_type == "sqlite":
            result = diff_sqlite(before_collector, after_collector)
        elif collector_type == "http_sink":
            result = diff_http_sink(before_collector, after_collector)
        else:
            raise ValueError(f"Unsupported collector type in diff: {collector_type}")

        collector_diffs.append(result)
        effect_kinds.append(result["effect_type"])

    return {
        "schema_version": "0.1",
        "before_name": before.get("name"),
        "after_name": after.get("name"),
        "collector_diffs": collector_diffs,
        "overall_effect_type": _overall_effect(effect_kinds),
    }


def judge_report(diff_report: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    overall = diff_report["overall_effect_type"]
    allowed = set(expected.get("allowed_effect_types", []))
    requires_no_mutation = bool(expected.get("requires_no_world_mutation", False))

    fs_or_db_or_network_mutation = overall in {"MutateFS", "MutateDB", "SendNetwork", "CompositeEffect"}
    verdict_ok = True
    reasons: List[str] = []

    if allowed and overall not in allowed:
        verdict_ok = False
        reasons.append(f"overall_effect_type={overall} not in allowed_effect_types={sorted(allowed)}")

    if requires_no_mutation and fs_or_db_or_network_mutation:
        verdict_ok = False
        reasons.append("world mutation detected while requires_no_world_mutation=true")

    if verdict_ok:
        reasons.append("effect report matches expected policy")

    return {
        "schema_version": "0.1",
        "expected_decision": expected.get("expected_decision"),
        "overall_effect_type": overall,
        "ok": verdict_ok,
        "reasons": reasons,
        "diff_report": diff_report,
    }
