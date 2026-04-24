#!/usr/bin/env python3
"""
Unified VTRM audit logging.

Records allow/deny/approval decisions and execution outcomes in JSONL form.
Mutation requests fail closed when audit logging is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger("vtrm.audit")


class AuditDecision(Enum):
    AUTO = "auto"
    APPROVAL_REQUIRED = "approval_required"
    DENY = "deny"


class AuditEffect(Enum):
    NONE = "none"
    FS_READ = "fs_read"
    FS_WRITE = "fs_write"
    FS_DELETE = "fs_delete"
    NETWORK_SEND = "network_send"
    DB_INSERT = "db_insert"
    DB_UPDATE = "db_update"
    DB_DELETE = "db_delete"


class AuditStatus(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass
class AuditEvent:
    task_id: str
    request_id: str
    subject: str
    tool: str
    decision: str
    effect: str
    status: str
    reason: str
    timestamp: str
    args_digest: str
    execution_time_ms: Optional[float] = None
    error_detail: Optional[str] = None
    approval_id: Optional[str] = None
    rule: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        filtered = {k: v for k, v in data.items() if v is not None}
        return cls(**filtered)

    @staticmethod
    def effect_from_tool(tool: str) -> str:
        mapping = {
            "fs.read": AuditEffect.FS_READ.value,
            "fs.write": AuditEffect.FS_WRITE.value,
            "fs.delete": AuditEffect.FS_DELETE.value,
            "network.send": AuditEffect.NETWORK_SEND.value,
            "db.read": AuditEffect.FS_READ.value,
            "db.insert": AuditEffect.DB_INSERT.value,
            "db.update": AuditEffect.DB_UPDATE.value,
            "db.delete": AuditEffect.DB_DELETE.value,
        }
        return mapping.get(tool, AuditEffect.NONE.value)

    @staticmethod
    def is_mutation_effect(effect: str) -> bool:
        return effect in {
            AuditEffect.FS_WRITE.value,
            AuditEffect.FS_DELETE.value,
            AuditEffect.NETWORK_SEND.value,
            AuditEffect.DB_INSERT.value,
            AuditEffect.DB_UPDATE.value,
            AuditEffect.DB_DELETE.value,
        }


class AuditLogger:
    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = Path(log_dir or os.environ.get("VTRM_AUDIT_LOG_DIR", "/var/log/sandbox/vtrm"))
        self._ensure_dirs()

        self.audit_log = self.log_dir / "vtrm_audit.jsonl"
        self.deny_log = self.log_dir / "vtrm_deny.jsonl"
        self.approval_log = self.log_dir / "vtrm_approval.jsonl"

        self.stats = {
            "total_requests": 0,
            "auto_allowed": 0,
            "approval_required": 0,
            "denied": 0,
            "errors": 0,
        }

        self._audit_available = self._check_audit_available()

    def _ensure_dirs(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Failed to create log dir %s: %s", self.log_dir, exc)

    def _check_audit_available(self) -> bool:
        try:
            test_path = self.log_dir / ".audit_test"
            test_path.write_text("test", encoding="utf-8")
            test_path.unlink()
            return True
        except OSError:
            return False

    def is_audit_available(self) -> bool:
        return self._audit_available

    @staticmethod
    def digest_args(args: Dict[str, Any]) -> str:
        payload = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _log_path_for_decision(self, decision: str) -> Path:
        if decision == AuditDecision.DENY.value:
            return self.deny_log
        if decision == AuditDecision.APPROVAL_REQUIRED.value:
            return self.approval_log
        return self.audit_log

    def write_event(self, event: AuditEvent) -> bool:
        path = self._log_path_for_decision(event.decision)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(event.to_jsonl())
                handle.write("\n")
            self.stats["total_requests"] += 1
            if event.decision == AuditDecision.AUTO.value:
                self.stats["auto_allowed"] += 1
            elif event.decision == AuditDecision.APPROVAL_REQUIRED.value:
                self.stats["approval_required"] += 1
            elif event.decision == AuditDecision.DENY.value:
                self.stats["denied"] += 1
            return True
        except OSError as exc:
            self.stats["errors"] += 1
            logger.error("Failed to write audit log to %s: %s", path, exc)
            return False

    def check_mutation_audit(self, decision: str, effect: str) -> bool:
        if decision != AuditDecision.AUTO.value:
            return True
        if not AuditEvent.is_mutation_effect(effect):
            return True
        return self.is_audit_available()

    def log_request(
        self,
        *,
        task_id: str,
        request_id: str,
        subject: str,
        tool: str,
        args: Dict[str, Any],
        decision: str,
        effect: str,
        status: str,
        reason: str,
        execution_time_ms: Optional[float] = None,
        error_detail: Optional[str] = None,
        approval_id: Optional[str] = None,
        rule: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[AuditEvent, bool]:
        event = AuditEvent(
            task_id=task_id,
            request_id=request_id,
            subject=subject,
            tool=tool,
            decision=decision,
            effect=effect,
            status=status,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            args_digest=self.digest_args(args),
            execution_time_ms=execution_time_ms,
            error_detail=error_detail,
            approval_id=approval_id,
            rule=rule,
            metadata=metadata or {},
        )
        written = self.write_event(event)
        return event, written

    def log_decision(
        self,
        *,
        task_id: str,
        request_id: str,
        subject: str,
        tool: str,
        args: Dict[str, Any],
        decision: str,
        reason: str,
        status: str,
        approval_id: Optional[str] = None,
        rule: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        effect = AuditEffect.NONE.value
        if decision == AuditDecision.AUTO.value and status != AuditStatus.PENDING.value:
            effect = AuditEvent.effect_from_tool(tool)
        _, written = self.log_request(
            task_id=task_id,
            request_id=request_id,
            subject=subject,
            tool=tool,
            args=args,
            decision=decision,
            effect=effect,
            status=status,
            reason=reason,
            approval_id=approval_id,
            rule=rule,
            metadata=metadata,
        )
        return written

    def log_execution_result(
        self,
        *,
        task_id: str,
        request_id: str,
        subject: str,
        tool: str,
        args: Dict[str, Any],
        success: bool,
        reason: str,
        execution_time_ms: Optional[float] = None,
        error_detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        _, written = self.log_request(
            task_id=task_id,
            request_id=request_id,
            subject=subject,
            tool=tool,
            args=args,
            decision=AuditDecision.AUTO.value,
            effect=AuditEvent.effect_from_tool(tool),
            status=AuditStatus.SUCCESS.value if success else AuditStatus.FAILURE.value,
            reason=reason,
            execution_time_ms=execution_time_ms,
            error_detail=error_detail,
            metadata=metadata,
        )
        return written

    def get_stats(self) -> Dict[str, int]:
        return dict(self.stats)
