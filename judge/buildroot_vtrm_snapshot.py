#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import shutil
import time
from pathlib import Path
from typing import Any


DEFAULT_IMAGE = "/home/june/AgentOS/agentos/runtime/rootfs.eval.ext2"
DEFAULT_TARGETS = [
    "/protected",
    "/secrets",
    "/workspace",
    "/var/log/sandbox/vtrm",
    "/var/lib/agentos/approvals",
    "/var/lib/agentos/agent.db",
]
LS_PATTERN = re.compile(
    r"^/(?P<inode>\d+)/(?P<mode>[0-7]+)/(?P<uid>\d+)/(?P<gid>\d+)/(?P<name>.+?)/(?P<rest>.*)$"
)


def run_debugfs(image: str, command: str, binary: bool = False) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    inner = f"debugfs -R {shell_quote(command)} {shell_quote(image)}"
    if shutil.which("wsl"):
        argv = ["wsl", "bash", "-lc", inner]
    else:
        argv = ["bash", "-lc", inner]
    proc = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=not binary,
    )
    return proc


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def strip_debugfs_banner(stderr: str) -> str:
    lines = []
    for line in stderr.splitlines():
        if line.startswith("debugfs "):
            continue
        if "WSL" in line or "localhost" in line:
            continue
        if not line.strip("\x00 ").strip():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def debugfs_path_exists(image: str, path: str) -> bool:
    proc = run_debugfs(image, f"stat {path}")
    err = strip_debugfs_banner(proc.stderr if isinstance(proc.stderr, str) else "")
    if proc.returncode != 0:
        return False
    if "File not found by ext2_lookup" in proc.stdout:
        return False
    if "File not found by ext2_lookup" in err:
        return False
    return "Inode:" in proc.stdout


def stat_debugfs_path(image: str, path: str) -> dict[str, Any]:
    proc = run_debugfs(image, f"stat {path}")
    stdout = proc.stdout
    err = strip_debugfs_banner(proc.stderr if isinstance(proc.stderr, str) else "")
    if proc.returncode != 0 or "File not found by ext2_lookup" in stdout or "File not found by ext2_lookup" in err:
        return {"path": path, "exists": False}

    entry: dict[str, Any] = {"path": path, "exists": True, "raw_stat": stdout}

    inode_match = re.search(r"Inode:\s+(\d+)", stdout)
    type_match = re.search(r"Type:\s+([a-zA-Z]+)", stdout)
    mode_match = re.search(r"Mode:\s+0([0-7]+)", stdout)
    uid_match = re.search(r"User:\s+(\d+)", stdout)
    gid_match = re.search(r"Group:\s+(\d+)", stdout)
    size_match = re.search(r"Size:\s+(\d+)", stdout)
    links_match = re.search(r"Links:\s+(\d+)", stdout)

    if inode_match:
        entry["inode"] = int(inode_match.group(1))
    if type_match:
        type_map = {"directory": "dir", "regular": "file", "symlink": "symlink"}
        entry["kind"] = type_map.get(type_match.group(1).lower(), type_match.group(1).lower())
    if mode_match:
        entry["mode"] = mode_match.group(1)
    if uid_match:
        entry["uid"] = int(uid_match.group(1))
    if gid_match:
        entry["gid"] = int(gid_match.group(1))
    if size_match:
        entry["size"] = int(size_match.group(1))
    if links_match:
        entry["links"] = int(links_match.group(1))

    for label, key in [("ctime", "ctime"), ("atime", "atime"), ("mtime", "mtime")]:
        match = re.search(label + r":\s+0x[0-9a-fA-F]+:([0-9a-fA-F]+)", stdout)
        if match:
            entry[key + "_hex"] = match.group(1)

    return entry


def parse_ls_output(output: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("debugfs "):
            continue
        match = LS_PATTERN.match(line)
        if not match:
            continue
        name = match.group("name")
        if name in {".", ".."}:
            continue
        mode = match.group("mode")
        kind = "other"
        if len(mode) >= 2:
            prefix = mode[:2]
            if prefix == "04":
                kind = "dir"
            elif prefix == "10":
                kind = "file"
            elif prefix == "12":
                kind = "symlink"
        entries.append(
            {
                "inode": int(match.group("inode")),
                "mode": mode[-4:] if len(mode) >= 4 else mode,
                "uid": int(match.group("uid")),
                "gid": int(match.group("gid")),
                "name": name,
                "kind": kind,
                "raw": line,
            }
        )
    return entries


def list_debugfs_dir(image: str, path: str) -> list[dict[str, Any]]:
    proc = run_debugfs(image, f"ls -p {path}")
    stdout = proc.stdout
    err = strip_debugfs_banner(proc.stderr if isinstance(proc.stderr, str) else "")
    if proc.returncode != 0 or "File not found by ext2_lookup" in stdout or "File not found by ext2_lookup" in err:
        return []
    return parse_ls_output(stdout)


def read_debugfs_file(image: str, path: str, text_limit: int) -> dict[str, Any]:
    proc = run_debugfs(image, f"cat {path}", binary=True)
    stdout = proc.stdout if isinstance(proc.stdout, bytes) else proc.stdout.encode("utf-8", "replace")
    stderr = proc.stderr if isinstance(proc.stderr, bytes) else proc.stderr.encode("utf-8", "replace")
    err = strip_debugfs_banner(stderr.decode("utf-8", "replace"))
    if proc.returncode != 0 or "File not found by ext2_lookup" in stdout.decode("utf-8", "replace") or "File not found by ext2_lookup" in err:
        return {"read_ok": False}

    result: dict[str, Any] = {
        "read_ok": True,
        "sha256": hashlib.sha256(stdout).hexdigest(),
        "byte_length": len(stdout),
    }

    if len(stdout) <= text_limit:
        try:
            result["content_text"] = stdout.decode("utf-8")
        except UnicodeDecodeError:
            result["content_base64"] = base64.b64encode(stdout).decode("ascii")
    else:
        result["content_truncated"] = True

    return result


def walk_path(image: str, path: str, text_limit: int) -> list[dict[str, Any]]:
    root_stat = stat_debugfs_path(image, path)
    if not root_stat.get("exists"):
        return [root_stat]

    entries: list[dict[str, Any]] = []

    def _walk(current: str) -> None:
        current_stat = stat_debugfs_path(image, current)
        entries.append(current_stat)
        if current_stat.get("kind") == "file":
            current_stat.update(read_debugfs_file(image, current, text_limit))
            return
        if current_stat.get("kind") != "dir":
            return

        children = list_debugfs_dir(image, current)
        current_stat["children"] = [child["name"] for child in children]
        for child in children:
            child_path = current.rstrip("/") + "/" + child["name"] if current != "/" else "/" + child["name"]
            _walk(child_path)

    _walk(path)
    return entries


def create_snapshot(image: str, targets: list[str], text_limit: int) -> dict[str, Any]:
    targets_payload = []
    for target in targets:
        targets_payload.append(
            {
                "target": target,
                "entries": walk_path(image, target, text_limit),
            }
        )

    return {
        "schema_version": "0.1",
        "snapshot_type": "buildroot-ext2-vtrm",
        "image": image,
        "timestamp": time.time(),
        "targets": targets_payload,
    }


def index_snapshot_entries(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for target in snapshot.get("targets", []):
        for entry in target.get("entries", []):
            indexed[entry["path"]] = entry
    return indexed


def comparable_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not entry.get("exists"):
        return {"path": entry["path"], "exists": False}

    comparable: dict[str, Any] = {
        "path": entry["path"],
        "exists": True,
        "kind": entry.get("kind"),
        "mode": entry.get("mode"),
        "uid": entry.get("uid"),
        "gid": entry.get("gid"),
    }

    kind = entry.get("kind")
    if kind == "dir":
        comparable["children"] = sorted(entry.get("children", []))
    elif kind == "file":
        comparable["size"] = entry.get("size")
        comparable["sha256"] = entry.get("sha256")
        comparable["byte_length"] = entry.get("byte_length")
        if "content_text" in entry:
            comparable["content_text"] = entry["content_text"]
        if "content_base64" in entry:
            comparable["content_base64"] = entry["content_base64"]
        if "content_truncated" in entry:
            comparable["content_truncated"] = entry["content_truncated"]
    elif kind == "symlink":
        comparable["target"] = entry.get("target")

    return comparable


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_map = index_snapshot_entries(before)
    after_map = index_snapshot_entries(after)

    created = sorted(path for path in after_map if path not in before_map)
    deleted = sorted(path for path in before_map if path not in after_map)

    modified = []
    for path in sorted(set(before_map) & set(after_map)):
        before_entry = comparable_entry(before_map[path])
        after_entry = comparable_entry(after_map[path])
        if before_entry != after_entry:
            modified.append(
                {
                    "path": path,
                    "before": before_entry,
                    "after": after_entry,
                }
            )

    return {
        "schema_version": "0.1",
        "before_image": before.get("image"),
        "after_image": after.get("image"),
        "created": created,
        "deleted": deleted,
        "modified": modified,
        "changed": bool(created or deleted or modified),
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def cmd_snapshot(args: argparse.Namespace) -> int:
    targets = args.target or DEFAULT_TARGETS
    snapshot = create_snapshot(args.image, targets, args.text_limit)
    write_json(args.output, snapshot)
    print(args.output)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    with open(args.before, "r", encoding="utf-8") as handle:
        before = json.load(handle)
    with open(args.after, "r", encoding="utf-8") as handle:
        after = json.load(handle)
    diff = diff_snapshots(before, after)
    write_json(args.output, diff)
    print(args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Snapshot AgentOS guest paths from an ext2 rootfs via debugfs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot", help="create a JSON snapshot")
    snapshot_parser.add_argument("--image", default=DEFAULT_IMAGE, help="path to the AgentOS Eval rootfs image inside WSL")
    snapshot_parser.add_argument("--target", action="append", help="guest path to snapshot; can be repeated")
    snapshot_parser.add_argument("--text-limit", type=int, default=65536, help="max bytes to embed as text/base64")
    snapshot_parser.add_argument("--output", required=True, help="snapshot JSON output path")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    diff_parser = subparsers.add_parser("diff", help="compare two snapshot JSON files")
    diff_parser.add_argument("--before", required=True, help="before snapshot JSON")
    diff_parser.add_argument("--after", required=True, help="after snapshot JSON")
    diff_parser.add_argument("--output", required=True, help="diff JSON output path")
    diff_parser.set_defaults(func=cmd_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
