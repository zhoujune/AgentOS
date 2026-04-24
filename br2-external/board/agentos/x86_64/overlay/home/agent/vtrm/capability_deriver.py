#!/usr/bin/env python3
"""
capability_deriver.py — Capability Deriver (Security-hardened version)

Responsibilities:
  - Derive required capability based on tool type and target object type
  - Return structured results instead of strings (distinguish ok / invalid / unknown)
  - Narrow capability namespace, do not explode by table name

Design Principles:
  - Deterministic: Same tool+args always returns same CapabilityRequirement
  - Consistent: Capability naming aligned with object class
  - Simple: Derivation rules are simple for formal verification
  - Fail-Closed: unknown/invalid object-action pair → derivation_status != "ok"

V1 capability namespace (hardened, not expanded):

## File System
- fs.read.workspace
- fs.read.readonly
- fs.read.secret
- fs.read.protected
- fs.write.workspace
- fs.write.protected
- fs.delete.workspace
- fs.delete.protected

## Network
- network.send.trusted_internal
- network.send.external

## Database
- db.read.readonly
- db.read.secret
- db.read.audit
- db.insert.mutable
- db.insert.audit
- db.update.mutable
- db.update.audit

## Note
The following are NOT valid grantable capabilities:
  - fs.write.readonly (readonly × write → invalid_object_action)
  - fs.write.unknown (unknown × write → invalid_object_action)
  - fs.read.unknown (unknown path → deny)
  - db.insert.foo, db.update.bar (explode by table name → reject, use db.*.mutable)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .path_classifier import FileClass
from .db_classifier import DBClass
from .sink_classifier import SinkClass


class DerivationStatus(Enum):
    """Capability derivation status"""
    OK = "ok"                          # Successfully derived valid capability
    INVALID_OBJECT_ACTION = "invalid_object_action"  # E.g.: readonly × write
    UNKNOWN_OBJECT_CLASS = "unknown_object_class"    # Cannot classify object
    UNKNOWN_SINK_CLASS = "unknown_sink_class"       # Cannot classify sink
    INVALID_TOOL = "invalid_tool"                    # Unknown tool


@dataclass
class CapabilityRequirement:
    """
    Capability derivation result struct
    
    Attributes:
      required: Required capability string. None if status != OK
      derivation_status: Derivation status
      reason: Status explanation (for logging/audit)
    """
    required: Optional[str]
    derivation_status: DerivationStatus
    reason: str = ""
    
    @property
    def is_valid(self) -> bool:
        """Whether derivation succeeded"""
        return self.derivation_status == DerivationStatus.OK and self.required is not None
    
    @property
    def is_absolute_deny(self) -> bool:
        """
        Whether this is absolutely prohibited (approval cannot override)
        
        Rules:
          - invalid_object_action: Yes (structural error)
          - unknown_object_class + write: Yes
          - unknown_sink_class: No (via approval_required)
        """
        if self.derivation_status == DerivationStatus.INVALID_OBJECT_ACTION:
            return True
        if self.derivation_status == DerivationStatus.UNKNOWN_OBJECT_CLASS:
            # unknown object class + write = absolute deny
            return "write" in self.reason.lower()
        return False


class CapabilityDeriver:
    """
    Capability deriver
    
    Usage:
        deriver = CapabilityDeriver()
        result = deriver.derive("fs.write", path_type=FileClass.WORKSPACE_WRITABLE)
        # result.required == "fs.write.workspace", result.derivation_status == DerivationStatus.OK
    """
    
    def __init__(self):
        pass
    
    def derive(
        self,
        tool: str,
        path_type: Optional[FileClass] = None,
        db_class: Optional[DBClass] = None,
        sink_class: Optional[SinkClass] = None,
        table: Optional[str] = None,
    ) -> CapabilityRequirement:
        """
        Derive required capability
        
        Parameters:
          - tool: Tool type (e.g. fs.read, db.insert)
          - path_type: Path type (for fs operations)
          - db_class: Database object type (for db operations)
          - sink_class: Sink type (for network operations)
          - table: Table name (for db operations, only for debug)
        
        Returns:
          CapabilityRequirement struct
        """
        # fs operations
        if tool.startswith("fs."):
            return self._derive_fs_capability(tool, path_type)
        
        # network operations
        if tool.startswith("network."):
            return self._derive_network_capability(tool, sink_class)
        
        # db operations
        if tool.startswith("db."):
            return self._derive_db_capability(tool, db_class)
        
        # Unknown tool
        return CapabilityRequirement(
            required=None,
            derivation_status=DerivationStatus.INVALID_TOOL,
            reason=f"Unknown tool: {tool}"
        )
    
    def _derive_fs_capability(
        self,
        tool: str,
        path_type: Optional[FileClass],
    ) -> CapabilityRequirement:
        """Derive capability for fs operations"""
        action = tool.split(".")[1]  # read or write

        if path_type is None or path_type == FileClass.UNKNOWN:
            # Unknown path: read via approval_required, write via absolute deny
            if action == "read":
                return CapabilityRequirement(
                    required=None,
                    derivation_status=DerivationStatus.UNKNOWN_OBJECT_CLASS,
                    reason="fs.read on unknown path"
                )
            else:
                return CapabilityRequirement(
                    required=None,
                    derivation_status=DerivationStatus.INVALID_OBJECT_ACTION,
                    reason=f"fs.{action} on unknown path is absolute deny"
                )

        # readonly class + write operation = invalid
        if path_type == FileClass.READONLY and action in {"write", "delete"}:
            return CapabilityRequirement(
                required=None,
                derivation_status=DerivationStatus.INVALID_OBJECT_ACTION,
                reason=f"fs.{action} on readonly path is invalid"
            )

        # SECRET_SOURCE / AUDIT_LOG class + write operation = invalid
        if path_type in (FileClass.SECRET_SOURCE, FileClass.AUDIT_LOG) and action in {"write", "delete"}:
            return CapabilityRequirement(
                required=None,
                derivation_status=DerivationStatus.INVALID_OBJECT_ACTION,
                reason=f"fs.{action} on {path_type.value} is invalid"
            )

        # Valid mapping (only keeping hardened capabilities)
        mapping = {
            FileClass.PROTECTED: {
                "read": "fs.read.protected",
                "write": "fs.write.protected",
                "delete": "fs.delete.protected",
            },
            FileClass.WORKSPACE_WRITABLE: {
                "read": "fs.read.workspace",
                "write": "fs.write.workspace",
                "delete": "fs.delete.workspace",
            },
            FileClass.READONLY: {
                "read": "fs.read.readonly",
            },
            FileClass.SECRET_SOURCE: {
                "read": "fs.read.secret",
            },
            FileClass.AUDIT_LOG: {
                # agent cannot read/write audit log
                "read": None,
            },
        }

        cap = mapping.get(path_type, {}).get(action)
        if cap:
            return CapabilityRequirement(
                required=cap,
                derivation_status=DerivationStatus.OK,
                reason=f"fs.{action} on {path_type.value}"
            )
        
        # Should not reach here (fallback deny)
        return CapabilityRequirement(
            required=None,
            derivation_status=DerivationStatus.INVALID_OBJECT_ACTION,
            reason=f"No valid capability for fs.{action} on {path_type.value}"
        )
    
    def _derive_network_capability(
        self,
        tool: str,
        sink_class: Optional[SinkClass],
    ) -> CapabilityRequirement:
        """Derive capability for network operations"""
        action = "send"  # Currently only send
        
        if sink_class is None:
            # Unknown sink → via approval_required
            return CapabilityRequirement(
                required=None,
                derivation_status=DerivationStatus.UNKNOWN_SINK_CLASS,
                reason="network.send to unknown sink"
            )
        
        mapping = {
            SinkClass.TRUSTED_INTERNAL: f"network.{action}.trusted_internal",
            SinkClass.EXTERNAL_UNTRUSTED: f"network.{action}.external",
        }
        
        cap = mapping.get(sink_class)
        if cap:
            return CapabilityRequirement(
                required=cap,
                derivation_status=DerivationStatus.OK,
                reason=f"network.{action} to {sink_class.value}"
            )
        
        return CapabilityRequirement(
            required=None,
            derivation_status=DerivationStatus.UNKNOWN_SINK_CLASS,
            reason=f"Unknown sink class: {sink_class}"
        )
    
    def _derive_db_capability(
        self,
        tool: str,
        db_class: Optional[DBClass],
    ) -> CapabilityRequirement:
        """Derive capability for db operations (hardened version: do not explode by table name)"""
        parts = tool.split(".")
        if len(parts) < 2:
            return CapabilityRequirement(
                required=None,
                derivation_status=DerivationStatus.INVALID_TOOL,
                reason=f"Invalid db tool: {tool}"
            )
        
        action = parts[1]  # read, insert, update, delete
        
        if db_class is None or db_class == DBClass.UNKNOWN:
            # Unknown table class
            if action == "read":
                return CapabilityRequirement(
                    required=None,
                    derivation_status=DerivationStatus.UNKNOWN_OBJECT_CLASS,
                    reason="db.read on unknown table class"
                )
            else:
                # Write to unknown table = absolute deny
                return CapabilityRequirement(
                    required=None,
                    derivation_status=DerivationStatus.INVALID_OBJECT_ACTION,
                    reason="db.write on unknown table class is absolute deny"
                )

        # Map by DBClass (hardened: do not explode by table name)
        mapping = {
            DBClass.SECRET_TABLE: {
                "read": "db.read.secret",
                "insert": None,  # Forbidden to write to secret table
                "update": None,  # Forbidden to update secret table
                "delete": None,
            },
            DBClass.AUDIT_TABLE: {
                "read": "db.read.audit",
                "insert": "db.insert.audit",  # audit table needs special capability
                "update": "db.update.audit",
                "delete": "db.delete.audit",
            },
            DBClass.READONLY_TABLE: {
                "read": "db.read.readonly",
                "insert": None,
                "update": None,
                "delete": None,
            },
            DBClass.MUTABLE_TABLE: {
                "read": "db.read.readonly",    # Read uses readonly capability
                "insert": "db.insert.mutable",
                "update": "db.update.mutable",
                "delete": "db.delete.mutable",
            },
        }

        cap = mapping.get(db_class, {}).get(action)
        if cap:
            return CapabilityRequirement(
                required=cap,
                derivation_status=DerivationStatus.OK,
                reason=f"db.{action} on {db_class.value}"
            )
        
        # cap is None means operation is invalid for this class
        return CapabilityRequirement(
            required=None,
            derivation_status=DerivationStatus.INVALID_OBJECT_ACTION,
            reason=f"db.{action} on {db_class.value} is not allowed"
        )


# Global default instance
_default_deriver: Optional[CapabilityDeriver] = None


def derive_capability(
    tool: str,
    path_type: Optional[FileClass] = None,
    db_class: Optional[DBClass] = None,
    sink_class: Optional[SinkClass] = None,
    table: Optional[str] = None,
) -> CapabilityRequirement:
    """
    Global derive_capability function
    
    Uses global default deriver
    """
    global _default_deriver
    if _default_deriver is None:
        _default_deriver = CapabilityDeriver()
    return _default_deriver.derive(
        tool=tool,
        path_type=path_type,
        db_class=db_class,
        sink_class=sink_class,
        table=table,
    )


def get_base_capability(tool: str) -> str:
    """Get base capability for tool (for compatibility)"""
    if tool == "fs.read":
        return "fs.read"
    if tool == "fs.write":
        return "fs.write"
    if tool == "network.send":
        return "network.send"
    if tool.startswith("db."):
        return tool
    return tool
