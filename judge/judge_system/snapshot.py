from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any, Dict, List

from .utils import sha256_file


def _filesystem_entry(path: Path, hash_content: bool) -> Dict[str, Any]:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return {"path": str(path), "exists": False}

    mode = stat.S_IMODE(st.st_mode)
    if path.is_symlink():
        kind = "symlink"
    elif path.is_dir():
        kind = "dir"
    elif path.is_file():
        kind = "file"
    else:
        kind = "other"

    entry: Dict[str, Any] = {
        "path": str(path),
        "exists": True,
        "kind": kind,
        "size": st.st_size,
        "mode": format(mode, "04o"),
        "mtime_ns": st.st_mtime_ns,
    }

    if kind == "symlink":
        try:
            entry["target"] = os.readlink(path)
        except OSError:
            entry["target"] = None

    if kind == "file" and hash_content:
        entry["sha256"] = sha256_file(path)

    return entry


def snapshot_filesystem(collector: Dict[str, Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for item in collector.get("paths", []):
        base = Path(item["path"])
        recursive = bool(item.get("recursive", False))
        hash_content = bool(item.get("hash_content", False))

        if recursive and base.exists() and base.is_dir():
            entries.append(_filesystem_entry(base, False))
            for child in sorted(base.rglob("*")):
                entries.append(_filesystem_entry(child, hash_content))
        else:
            entries.append(_filesystem_entry(base, hash_content))

    return {
        "type": "filesystem",
        "name": collector["name"],
        "entries": entries,
    }


def snapshot_sqlite(collector: Dict[str, Any]) -> Dict[str, Any]:
    db_path = Path(collector["path"])
    result: Dict[str, Any] = {
        "type": "sqlite",
        "name": collector["name"],
        "path": str(db_path),
        "exists": db_path.exists(),
    }
    if not db_path.exists():
        return result

    include_rows = bool(collector.get("include_rows", False))
    tables: List[Dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        names = [row[0] for row in cursor.fetchall()]
        for table_name in names:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            table_info: Dict[str, Any] = {
                "table": table_name,
                "row_count": count,
            }
            if include_rows:
                rows = conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
                table_info["rows"] = rows
            tables.append(table_info)

    result["tables"] = tables
    result["file_sha256"] = sha256_file(db_path)
    return result


def snapshot_http_sink(collector: Dict[str, Any]) -> Dict[str, Any]:
    sink_path = Path(collector["path"])
    events: List[Dict[str, Any]] = []
    if sink_path.exists():
        with sink_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return {
        "type": "http_sink",
        "name": collector["name"],
        "path": str(sink_path),
        "event_count": len(events),
        "events": events,
    }


def snapshot_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    collectors = []
    for collector in config.get("collectors", []):
        kind = collector["type"]
        if kind == "filesystem":
            collectors.append(snapshot_filesystem(collector))
        elif kind == "sqlite":
            collectors.append(snapshot_sqlite(collector))
        elif kind == "http_sink":
            collectors.append(snapshot_http_sink(collector))
        else:
            raise ValueError(f"Unsupported collector type: {kind}")

    return {
        "schema_version": "0.1",
        "name": config.get("name", "world-effect-judge"),
        "timestamp": time.time(),
        "collectors": collectors,
    }
