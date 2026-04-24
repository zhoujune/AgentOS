from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BODY_PREVIEW_LIMIT = 512


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class SinkHandler(BaseHTTPRequestHandler):
    sink_file: Path | None = None

    def _write_event(self) -> None:
        assert self.sink_file is not None
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        body_preview = body[:BODY_PREVIEW_LIMIT]
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": self.command,
            "path": self.path,
            "headers": {key: value for key, value in self.headers.items()},
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_size": len(body),
            "body_preview_truncated": len(body) > BODY_PREVIEW_LIMIT,
        }
        try:
            payload["body_text_preview"] = body_preview.decode("utf-8")
        except UnicodeDecodeError:
            payload["body_hex_preview"] = body_preview.hex()
        with self.sink_file.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")

    def do_GET(self) -> None:  # noqa: N802
        self._write_event()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def do_POST(self) -> None:  # noqa: N802
        self._write_event()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def do_PUT(self) -> None:  # noqa: N802
        self.do_POST()

    def do_DELETE(self) -> None:  # noqa: N802
        self._write_event()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mock HTTP sink for World Effect Judge")
    parser.add_argument("--host", default="127.0.0.1", help="listen host")
    parser.add_argument("--port", type=int, default=18080, help="listen port")
    parser.add_argument("--output", required=True, help="JSONL event log path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sink_file = Path(args.output)
    sink_file.parent.mkdir(parents=True, exist_ok=True)
    SinkHandler.sink_file = sink_file

    try:
        server = ReusableThreadingHTTPServer((args.host, args.port), SinkHandler)
    except OSError as exc:
        print(f"[http_sink] failed to bind {args.host}:{args.port}: {exc}", file=sys.stderr, flush=True)
        return 1

    print(f"[http_sink] listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
