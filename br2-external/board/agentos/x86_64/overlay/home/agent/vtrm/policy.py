#!/usr/bin/env python3
"""
policy.py — VTRM Policy Engine (Security-hardened version)

Responsibilities:
  1. Capability check (using CapabilityDeriver, returns CapabilityRequirement)
  2. Authorization Mode check (using AuthorizationPolicy)
  3. Absolute Deny check (using AbsoluteDenyChecker)
  4. Path/Network/Database policy check

Design Principles:
  - Deterministic: All decisions must clearly record audit events
  - Fail-Closed: Unknown situations default to deny
  - Absolute Deny has highest priority
  - Decision order: AbsoluteDeny → AuthorizationMode → Capability

Architecture Changes (this version):
  - Decision enum aligned with AuthorizationMode
  - CapabilityRegistry uses new CapabilityRequirement structure
  - AbsoluteDenyChecker as independent component
  - PolicyResult carries more metadata
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Set

from .path_classifier import FileClass, classify_path
from .label_model import Label, can_exfiltrate, join_labels
from .db_classifier import DBClass, classify_table
from .sink_classifier import SinkClass, classify_sink
from .capability_deriver import CapabilityDeriver, CapabilityRequirement, DerivationStatus, derive_capability
from .authorization_policy import (
    AuthorizationPolicy,
    AuthorizationMode,
    AuthorizationResult,
    AbsoluteDenyChecker,
    AbsoluteDenyContext,
    AbsoluteDenyRule,
    get_default_policy,
)


logger = logging.getLogger("vtrm.policy")


class Decision(Enum):
    """
    Policy decision result
    
    Aligned with AuthorizationMode:
      - ALLOW → AuthorizationMode.AUTO
      - APPROVAL_REQUIRED → AuthorizationMode.APPROVAL_REQUIRED
      - DENY → AuthorizationMode.DENY
    """
    ALLOW = "allow"           # Auto execute
    APPROVAL_REQUIRED = "approval_required"  # Requires approval
    DENY = "deny"             # Absolutely prohibited


@dataclass
class PolicyResult:
    """
    Policy check result
    
    Attributes:
      decision: Decision (allow / approval_required / deny)
      reason: Decision reason
      effect_type: world-state effect type
      metadata: Additional metadata
      # Approval related
      approval_id: Approval ID (when decision == APPROVAL_REQUIRED)
      rule: Rule name that triggered this decision
    """
    decision: Decision
    reason: str
    effect_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    approval_id: Optional[str] = None
    rule: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "decision": self.decision.value,
            "reason": self.reason,
            "effect_type": self.effect_type,
            "metadata": self.metadata,
        }
        if self.approval_id:
            d["approval_id"] = self.approval_id
        if self.rule:
            d["rule"] = self.rule
        return d
    
    @property
    def is_allowed(self) -> bool:
        return self.decision == Decision.ALLOW
    
    @property
    def is_approval_required(self) -> bool:
        return self.decision == Decision.APPROVAL_REQUIRED
    
    @property
    def is_denied(self) -> bool:
        return self.decision == Decision.DENY


class CapabilityRegistry:
    """
    Capability registry and management
    
    Responsible for:
      - Verifying if agent holds a capability
      - Deciding authorization mode based on AuthorizationPolicy
    """
    
    def __init__(
        self,
        agent_capabilities: Optional[Set[str]] = None,
        authorization_policy: Optional[AuthorizationPolicy] = None,
    ):
        """
        Initialize
        
        Parameters:
          - agent_capabilities: Set of capabilities the agent has
          - authorization_policy: Authorization policy, defaults to agent.default
        """
        self.agent_capabilities = agent_capabilities or set()
        self.deriver = CapabilityDeriver()
        self.auth_policy = authorization_policy or get_default_policy()
    
    def has_capability(self, capability: str) -> bool:
        """Check if agent has the specified capability"""
        return capability in self.agent_capabilities
    
    def derive_capability(
        self,
        tool: str,
        path_class: Optional[FileClass] = None,
        db_class: Optional[DBClass] = None,
        sink_class: Optional[SinkClass] = None,
        table: Optional[str] = None,
    ) -> CapabilityRequirement:
        """
        Derive required capability
        
        Uses new CapabilityDeriver, returns CapabilityRequirement structure.
        """
        return self.deriver.derive(
            tool=tool,
            path_type=path_class,
            db_class=db_class,
            sink_class=sink_class,
            table=table,
        )
    
    def check_capability(
        self,
        capability: str,
    ) -> tuple[bool, str]:
        """
        Check if agent has a capability
        
        Returns:
          (has_capability, reason)
        """
        if not self.has_capability(capability):
            return False, f"Agent does not have capability: '{capability}'"
        return True, "Capability check passed"
    
    def check(
        self,
        tool: str,
        required_capability: Optional[str],
        derivation_status: str,
        path_class: Optional[FileClass] = None,
        db_class: Optional[DBClass] = None,
        sink_class: Optional[SinkClass] = None,
        table: Optional[str] = None,
        ctx: Optional[AbsoluteDenyContext] = None,
    ) -> PolicyResult:
        """
        Check capability + authorization mode
        
        Flow:
          1. AbsoluteDeny check
          2. derivation status check
          3. AuthorizationPolicy decides mode
          4. CapabilityRegistry verifies holding
        
        Parameters:
          - tool: Tool type
          - required_capability: Required capability derived by VTRM
          - derivation_status: Derivation status from CapabilityDeriver
          - path_class: Path object class (optional)
          - db_class: Database object class (optional)
          - sink_class: Sink type (optional)
          - table: Table name (optional)
          - ctx: AbsoluteDenyContext (optional)
        
        Returns:
          PolicyResult
        """
        # 1. Build AbsoluteDenyContext
        if ctx is None:
            ctx = AbsoluteDenyContext(
                tool=tool,
                inferred_label=None,
                sink_class=sink_class.value if sink_class else None,
            )
        
        # 2. AbsoluteDeny check (highest priority)
        deny_checker = AbsoluteDenyChecker()
        absolute_deny = deny_checker.check(ctx)
        if absolute_deny is not None:
            return PolicyResult(
                decision=Decision.DENY,
                reason=absolute_deny.reason,
                effect_type="None",
                rule=absolute_deny.rule,
            )
        
        # 3. Check derivation status
        if derivation_status != DerivationStatus.OK.value:
            return PolicyResult(
                decision=Decision.DENY,
                reason=f"Capability derivation failed: {derivation_status}",
                effect_type="None",
                rule="derivation_failed",
            )
        
        # 4. Check if required_capability is valid
        if required_capability is None:
            return PolicyResult(
                decision=Decision.DENY,
                reason="No valid capability derived",
                effect_type="None",
                rule="no_capability",
            )
        
        # 5. AuthorizationPolicy decides mode
        auth_result = self.auth_policy.authorize(
            capability=required_capability,
            derivation_status=derivation_status,
            ctx=ctx,
        )
        
        if auth_result.mode == AuthorizationMode.DENY:
            return PolicyResult(
                decision=Decision.DENY,
                reason=auth_result.reason,
                effect_type="None",
                rule=auth_result.rule,
            )
        
        if auth_result.mode == AuthorizationMode.APPROVAL_REQUIRED:
            return PolicyResult(
                decision=Decision.APPROVAL_REQUIRED,
                reason=auth_result.reason,
                effect_type=self._get_effect_type(tool),
                rule=auth_result.rule,
                metadata={"preview": auth_result.preview} if auth_result.preview else {},
            )
        
        # 6. AUTO mode: Verify capability holding
        has_cap, cap_reason = self.check_capability(required_capability)
        if not has_cap:
            return PolicyResult(
                decision=Decision.DENY,
                reason=cap_reason,
                effect_type="None",
                rule="capability_not_held",
            )
        
        # 7. Passed all checks
        return PolicyResult(
            decision=Decision.ALLOW,
            reason=f"Capability '{required_capability}' authorized for auto execution",
            effect_type=self._get_effect_type(tool),
            rule="auto_authorized",
            metadata={"capability": required_capability},
        )
    
    @staticmethod
    def _get_effect_type(tool: str) -> str:
        """Get world-state effect type for tool"""
        effect_map = {
            "fs.read": "ReadOnly",
            "fs.write": "MutateFS",
            "network.send": "SendExternal",
            "db.read": "ReadOnly",
            "db.insert": "MutateDB",
            "db.update": "MutateDB"
        }
        return effect_map.get(tool, "Unknown")


class PathPolicy:
    """
    Path policy checker
    
    Checks:
      - Whether file object class allows the operation
      - Whether write operations are on allowed classes
    """
    
    @staticmethod
    def check(tool: str, path: str, action: str) -> PolicyResult:
        """
        Check path permissions
        
        Parameters:
          - tool: Tool type (fs.*)
          - path: Target path
          - action: Action type (read / write)
        
        Returns:
          PolicyResult (deny: effect_type="None")
        """
        file_class = classify_path(path)
        
        # UNKNOWN defaults to deny
        if file_class == FileClass.UNKNOWN:
            return PolicyResult(
                decision=Decision.DENY,
                reason=f"Path not allowed: {path} (object class={file_class.value})",
                effect_type="None",
                rule="unknown_path",
            )
        
        # Read check
        if action == "read":
            if not PathPolicy._is_readable(file_class):
                return PolicyResult(
                    decision=Decision.DENY,
                    reason=f"Path '{path}' (class={file_class.value}) is not readable",
                    effect_type="None",
                    rule="path_not_readable",
                )
        
        # Write check
        elif action == "write":
            if not PathPolicy._is_writable(file_class):
                return PolicyResult(
                    decision=Decision.DENY,
                    reason=f"Path '{path}' (class={file_class.value}) is not writable",
                    effect_type="None",
                    rule="path_not_writable",
                )
        
        else:
            return PolicyResult(
                decision=Decision.DENY,
                reason=f"Unknown action: {action}",
                effect_type="None",
                rule="unknown_action",
            )
        
        effect_type = "MutateFS" if action == "write" else "ReadOnly"
        return PolicyResult(
            decision=Decision.ALLOW,
            reason=f"Path policy check passed: {path} (class={file_class.value})",
            effect_type=effect_type,
            rule="path_allowed",
            metadata={"object_class": file_class.value}
        )
    
    @staticmethod
    def _is_readable(file_class: FileClass) -> bool:
        """Check if object class is readable"""
        readable_classes = {
            FileClass.PROTECTED,
            FileClass.WORKSPACE_WRITABLE,
            FileClass.READONLY,
            FileClass.SECRET_SOURCE,
        }
        return file_class in readable_classes
    
    @staticmethod
    def _is_writable(file_class: FileClass) -> bool:
        """Check if object class is writable"""
        return file_class == FileClass.WORKSPACE_WRITABLE


class NetworkPolicy:
    """
    Network policy checker
    
    Checks:
      - Whether secret data can be sent to target URL
      - Returns PolicyResult with APPROVAL_REQUIRED / DENY
    """
    
    def __init__(self, allowed_external_sinks: Optional[Set[str]] = None):
        """
        Initialize
        
        Parameters:
          - allowed_external_sinks: Set of external sinks allowed to receive secrets (URL prefixes)
        """
        self.allowed_sinks = allowed_external_sinks or set()
        self.deny_checker = AbsoluteDenyChecker()
    
    def check(
        self,
        url: str,
        content_label: Label,
        sink_class: Optional[SinkClass] = None,
    ) -> PolicyResult:
        """
        Check network send
        
        Rules:
          - public data → allow external (via approval_required)
          - secret/high data → only to trusted_internal
          - secret/high → external_untrusted = ABSOLUTE DENY
        
        Parameters:
          - url: Target URL
          - content_label: Data label
          - sink_class: SinkClass (if already classified)
        
        Returns:
          PolicyResult
        """
        # Auto-classify sink (if not provided)
        if sink_class is None:
            sink_class = classify_sink(url)
        
        # Construct AbsoluteDenyContext
        ctx = AbsoluteDenyContext(
            tool="network.send",
            inferred_label=content_label.value,
            sink_class=sink_class.value,
        )
        
        # AbsoluteDeny check (checks secret/high → external_untrusted)
        absolute_deny = self.deny_checker.check(ctx)
        if absolute_deny is not None:
            return PolicyResult(
                decision=Decision.DENY,
                reason=absolute_deny.reason,
                effect_type="None",
                rule=absolute_deny.rule,
            )
        
        # Use can_exfiltrate check
        if not can_exfiltrate(content_label, sink_class):
            # secret/high data cannot be exfiltrated, return approval_required (agent may need manual authorization)
            if content_label == Label.SECRET_HIGH:
                return PolicyResult(
                    decision=Decision.APPROVAL_REQUIRED,
                    reason=f"Secret data cannot be sent to {sink_class.value} sink without approval",
                    effect_type="SendExternal",
                    rule="secret_to_external_requires_approval",
                    metadata={"url": url, "label": content_label.value, "sink_class": sink_class.value}
                )
            else:
                return PolicyResult(
                    decision=Decision.DENY,
                    reason=f"Label '{content_label}' not allowed to sink {sink_class.value}",
                    effect_type="None",
                    rule="label_sink_mismatch",
                    metadata={"url": url, "label": content_label.value, "sink_class": sink_class.value}
                )
        
        # Allow
        return PolicyResult(
            decision=Decision.ALLOW,
            reason=f"Network send allowed: {content_label} data to {sink_class.value} sink",
            effect_type="SendExternal",
            rule="label_sink_compatible",
            metadata={
                "url": url,
                "label": content_label.value,
                "sink_class": sink_class.value
            }
        )


class DBPolicy:
    """
    Database policy checker
    
    Checks:
      - Whether table object class allows the operation
      - Whether write operations target mutable_table
    """
    
    def __init__(self, secret_tables: Optional[Set[str]] = None):
        """
        Initialize
        
        Parameters:
          - secret_tables: Set of tables containing sensitive data (for legacy compatibility)
        """
        self.secret_tables = secret_tables or {"secrets", "credentials"}
        self._classifier = None
        self.deny_checker = AbsoluteDenyChecker()
    
    def _get_classifier(self):
        """Get DBClassifier instance"""
        if self._classifier is None:
            from .db_classifier import DBClassifier
            self._classifier = DBClassifier(secret_tables=self.secret_tables)
        return self._classifier
    
    def check_read(
        self,
        table: str,
        key: Optional[str] = None,
    ) -> PolicyResult:
        """
        Check database read operation
        
        Rules:
          - Any table is allowed to read
          - Secret table returns approval_required
          - Returned label needs to be set based on table type
        
        Parameters:
          - table: Table name
          - key: Primary key (optional)
        
        Returns:
          PolicyResult, metadata contains label
        """
        db_class = self._get_classifier().classify_table(table)
        
        # Read operation check
        if db_class == DBClass.SECRET_TABLE:
            # Secret table read requires approval
            return PolicyResult(
                decision=Decision.APPROVAL_REQUIRED,
                reason=f"DB read requires approval for secret table '{table}' (class={db_class.value})",
                effect_type="ReadOnly",
                rule="secret_table_requires_approval",
                metadata={
                    "table": table,
                    "key": key,
                    "label": Label.SECRET_HIGH.value,
                    "db_class": db_class.value,
                }
            )
        
        # Public table allows read
        return PolicyResult(
            decision=Decision.ALLOW,
            reason=f"DB read allowed for table '{table}' (class={db_class.value})",
            effect_type="ReadOnly",
            rule="read_allowed",
            metadata={
                "table": table,
                "key": key,
                "label": Label.PUBLIC.value,
                "db_class": db_class.value,
            }
        )
    
    def check_insert(
        self,
        table: str,
        row: Dict[str, Any],
        content_label: Label,
    ) -> PolicyResult:
        """
        Check database insert operation
        
        Rules:
          - Only MUTABLE_TABLE allows insert (via approval_required)
          - SECRET_TABLE / AUDIT_TABLE / READONLY_TABLE denied
          - UNKNOWN denied
        
        Parameters:
          - table: Table name
          - row: Row data
          - content_label: Content label
        
        Returns:
          PolicyResult
        """
        db_class = self._get_classifier().classify_table(table)
        
        # AbsoluteDeny check
        ctx = AbsoluteDenyContext(
            tool="db.insert",
            inferred_label=content_label.value,
        )
        
        absolute_deny = self.deny_checker.check(ctx)
        if absolute_deny is not None:
            return PolicyResult(
                decision=Decision.DENY,
                reason=absolute_deny.reason,
                effect_type="None",
                rule=absolute_deny.rule,
            )
        
        # Table type check
        if db_class == DBClass.MUTABLE_TABLE:
            return PolicyResult(
                decision=Decision.APPROVAL_REQUIRED,
                reason=f"DB insert requires approval for mutable table '{table}'",
                effect_type="MutateDB",
                rule="mutable_table_requires_approval",
                metadata={
                    "table": table,
                    "db_class": db_class.value,
                    "label": content_label.value,
                }
            )
        
        # Other table types denied
        return PolicyResult(
            decision=Decision.DENY,
            reason=f"Insert denied for table '{table}' (class={db_class.value})",
            effect_type="None",
            rule="table_type_deny",
        )
    
    def check_update(
        self,
        table: str,
        key: str,
        patch: Dict[str, Any],
        content_label: Label,
    ) -> PolicyResult:
        """
        Check database update operation
        
        Rules:
          - Only MUTABLE_TABLE allows update (via approval_required)
          - SECRET_TABLE / AUDIT_TABLE / READONLY_TABLE denied
        
        Parameters:
          - table: Table name
          - key: Primary key
          - patch: Update fields
          - content_label: Content label
        
        Returns:
          PolicyResult
        """
        db_class = self._get_classifier().classify_table(table)
        
        # AbsoluteDeny check
        ctx = AbsoluteDenyContext(
            tool="db.update",
            inferred_label=content_label.value,
        )
        
        absolute_deny = self.deny_checker.check(ctx)
        if absolute_deny is not None:
            return PolicyResult(
                decision=Decision.DENY,
                reason=absolute_deny.reason,
                effect_type="None",
                rule=absolute_deny.rule,
            )
        
        # Table type check
        if db_class == DBClass.MUTABLE_TABLE:
            return PolicyResult(
                decision=Decision.APPROVAL_REQUIRED,
                reason=f"DB update requires approval for mutable table '{table}'",
                effect_type="MutateDB",
                rule="mutable_table_requires_approval",
                metadata={
                    "table": table,
                    "key": key,
                    "db_class": db_class.value,
                    "label": content_label.value,
                }
            )
        
        # Other table types denied
        return PolicyResult(
            decision=Decision.DENY,
            reason=f"Update denied for table '{table}' (class={db_class.value})",
            effect_type="None",
            rule="table_type_deny",
        )
