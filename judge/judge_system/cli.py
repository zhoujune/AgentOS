from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_json
from .diffing import diff_snapshots, judge_report
from .snapshot import snapshot_from_config


def _write_json(path: str | Path, payload: dict) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def cmd_snapshot(args: argparse.Namespace) -> int:
    config = load_json(args.config)
    snapshot = snapshot_from_config(config)
    _write_json(args.output, snapshot)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    before = load_json(args.before)
    after = load_json(args.after)
    report = diff_snapshots(before, after)
    _write_json(args.output, report)
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    before = load_json(args.before)
    after = load_json(args.after)
    expected = load_json(args.expected)
    diff_report = diff_snapshots(before, after)
    verdict = judge_report(diff_report, expected)
    _write_json(args.output, verdict)
    return 0 if verdict["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="World Effect Judge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot", help="create a world snapshot")
    snapshot_parser.add_argument("--config", required=True, help="JSON config path")
    snapshot_parser.add_argument("--output", required=True, help="snapshot output path")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    diff_parser = subparsers.add_parser("diff", help="diff two snapshots")
    diff_parser.add_argument("--before", required=True, help="before snapshot path")
    diff_parser.add_argument("--after", required=True, help="after snapshot path")
    diff_parser.add_argument("--output", required=True, help="diff report output path")
    diff_parser.set_defaults(func=cmd_diff)

    judge_parser = subparsers.add_parser("judge", help="judge diff against expected policy")
    judge_parser.add_argument("--before", required=True, help="before snapshot path")
    judge_parser.add_argument("--after", required=True, help="after snapshot path")
    judge_parser.add_argument("--expected", required=True, help="expected policy JSON path")
    judge_parser.add_argument("--output", required=True, help="judge report output path")
    judge_parser.set_defaults(func=cmd_judge)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
