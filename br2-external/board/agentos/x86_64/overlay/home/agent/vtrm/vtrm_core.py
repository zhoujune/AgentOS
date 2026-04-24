#!/usr/bin/env python3
"""
vtrm_core.py — Verified Toolchain Reference Monitor (VTRM) Core (Security-hardened version)

Line B Security Core: Provides unified policy checking, audit logging, and state tracking for agent tool calls.

Architecture (7 layers):
  Layer 1: Request Frontend (parse + normalize + validate)
  Layer 2: Classification & Derivation (object_class, sink_class, capability, label)
  Layer 3: Authorization Mode (auto / approval_required / deny)
  Layer 4: VTRM Decision (policy check + decision)
  Layer 5: Approval Workflow (for approval_required)
  Layer 6: Effect Adapters (execution)
  Layer 7: OS Guard Rails (defense-in-depth)

Core Flow (complete version):
  1. normalize_request(): Normalize request, inject runtime metadata
  2. _validate_request(): Strict schema validation
  3. _classify_and_derive(): Classification + derivation
  4. _authorization_mode_check(): Authorization mode determination
  5. _check_approval_token(): Check approval token (if present)
  6. audit fail-closed check
  7. execute: Execute

Decision Order:
  1. Schema validation → deny (invalid schema)
  2. CapabilityDeriver → CapabilityRequirement
  3. AbsoluteDeny check → deny (secret_to_external etc.)
  4. AuthorizationPolicy → AuthorizationMode (auto / approval_required / deny)
  5. CapabilityRegistry → Verify capability holding
  6. Audit fail-closed → For mutation, check audit availability

Design Principles:
  - Fail-Closed: Any error denies
  - Do not trust model self-reported fields: capability_required, content_label
  - All requests must be audited
  - deny = no side effect
  - absolute deny cannot be overridden by approval
  - mutation + auto allow → audit must be available (fail-closed)
"""

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .path_classifier import FileClass, classify_path, canonicalize_path
from .db_classifier import DBClass, classify_table as db_classify_table
from .sink_classifier import SinkClass, classify_sink
from .label_model import Label, infer_label_from_path, infer_label_from_row, join_labels, can_exfiltrate
from .capability_deriver import CapabilityDeriver, CapabilityRequirement, DerivationStatus
from .authorization_policy import (
    AuthorizationPolicy,
    AuthorizationMode,
    AuthorizationResult,
    AbsoluteDenyChecker,
    AbsoluteDenyContext,
    get_default_policy,
)
from .policy import (
    CapabilityRegistry,
    PathPolicy,
    NetworkPolicy,
    DBPolicy,
    Decision,
    PolicyResult,
)
from .approval_store import (
    ApprovalStore,
    ApprovalRequest,
    ApprovalToken,
    EffectPreview,
    ApprovalStatus,
    get_approval_store,
)
from .audit_logger import AuditLogger, AuditDecision, AuditEffect, AuditStatus, AuditEvent


logger = logging.getLogger("vtrm.core")


class VTRError(Exception):
    """VTRM internal error"""
    pass


def _is_valid_request_id(req_id: str) -> bool:
    """Check if request_id conforms to trusted format"""
    if not isinstance(req_id, str):
        return False
    return bool(req_id.strip()) and (
        req_id.startswith("llm-") or
        req_id.startswith("req-") or
        req_id.startswith("agent-") or
        req_id.startswith("vtrm-") or
        len(req_id) >= 8
    )


def _is_valid_task_id(task_id: str) -> bool:
    """Check if task_id conforms to trusted format"""
    if not isinstance(task_id, str):
        return False
    return bool(task_id.strip()) and len(task_id) >= 3


# Backward compatibility alias
VTRMError = VTRError


class SchemaValidationError(VTRError):
    """Schema validation failed"""
    pass


class ApprovalRequiredError(VTRError):
    """Request requires human approval"""
    def __init__(self, approval_id: str, message: str):
        self.approval_id = approval_id
        super().__init__(message)


class AuditUnavailableError(VTRError):
    """Audit unavailable (fail-closed)"""
    pass


@dataclass
class VTRMDecision:
    """
    VTRM decision result
    
    Attributes:
      allowed: Whether execution is allowed (deprecated, use decision)
      decision: Decision (auto / approval_required / deny)
      request_id: Request ID (runtime generated)
      task_id: Task ID (runtime generated)
      subject: Execution subject
      tool: Tool type
      reason: Decision reason
      effect_type: World-state effect type
      target_object_class: Target object class
      sink_class: Sink type
      required_capability: Required capability
      inferred_label: Inferred content label
      approval_id: Approval ID (when decision == approval_required)
      rule: Rule name that triggered decision
      transformed_request: Transformed request (if applicable)
      metadata: Additional metadata
    """
    allowed: bool  # For backward compatibility
    decision: str  # auto / approval_required / deny
    request_id: str
    task_id: str
    subject: str
    tool: str
    reason: str
    effect_type: str
    target_object_class: Optional[str] = None
    sink_class: Optional[str] = None
    required_capability: Optional[str] = None
    inferred_label: Optional[str] = None
    approval_id: Optional[str] = None
    rule: str = ""
    transformed_request: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        # Sync allowed
        self.allowed = self.decision == AuditDecision.AUTO.value


# Allowed tool list
ALLOWED_TOOLS = {
    "fs.read",
    "fs.write",
    "fs.delete",
    "network.send",
    "db.read",
    "db.insert",
    "db.update",
    "db.delete",
}

# Allowed labels
ALLOWED_LABELS = {
    "public",
    "secret/high",
}

# World-state effect mapping
EFFECT_MAP = {
    "fs.read": "ReadOnly",
    "fs.write": "MutateFS",
    "fs.delete": "MutateFS",
    "network.send": "SendExternal",
    "db.read": "ReadOnly",
    "db.insert": "MutateDB",
    "db.update": "MutateDB",
    "db.delete": "MutateDB",
}


class VTRMCore:
    """
    VTRM Core
    
    Integrates all policy checking components, providing unified evaluate/execute interface.
    """
    
    def __init__(
        self,
        agent_capabilities: Optional[set[str]] = None,
        allowed_external_sinks: Optional[set[str]] = None,
        secret_tables: Optional[set[str]] = None,
        audit_log_dir: Optional[str] = None,
        approval_store_dir: Optional[str] = None,
        authorization_policy: Optional[AuthorizationPolicy] = None,
    ):
        """
        Initialize VTRM Core
        
        Parameters:
          - agent_capabilities: Set of capabilities the agent has
          - allowed_external_sinks: Set of external sinks allowed to receive secrets (URL prefixes)
          - secret_tables: Secret table set (backward compatibility)
          - audit_log_dir: Audit log directory
          - approval_store_dir: Approval store directory
          - authorization_policy: Authorization policy (defaults to agent.default)
        """
        self.audit_logger = AuditLogger(audit_log_dir)
        self.approval_store = get_approval_store(approval_store_dir)
        self.auth_policy = authorization_policy or get_default_policy()
        self.capability_registry = CapabilityRegistry(
            agent_capabilities=agent_capabilities,
            authorization_policy=self.auth_policy,
        )
        self.path_policy = PathPolicy()
        self.network_policy = NetworkPolicy(allowed_external_sinks)
        self.db_policy = DBPolicy(secret_tables)
        self.deriver = CapabilityDeriver()
        self.deny_checker = AbsoluteDenyChecker()
        self.runtime_subject = "agent.default"
        
        logger.info("VTRM Core initialized (security-closed)")
    
    # ========================
    # Request Normalization (Layer 1)
    # ========================
    
    def normalize_request(
        self,
        raw_request: Dict[str, Any],
        runtime_task_id: str,
        step_index: int
    ) -> Dict[str, Any]:
        """
        Normalize request: Override untrusted model metadata
        
        Rules (Fail-Closed):
          - task_id: Force override to runtime_task_id (from agent_runner)
          - subject: Force override to self.runtime_subject
          - request_id: Validate format, generate new ID if invalid
          - content_label: Remove (subsequently derived by VTRM)
          - capability_required: Remove (subsequently derived by VTRM)
          - _runtime_content_label: Only accept runtime-injected trusted label override
          - schema_version: Keep (string)
          - Other fields: Keep but mark as untrusted
        
        Parameters:
          - raw_request: Original request (from model or runner)
          - runtime_task_id: Runtime task_id (overrides model self-reported)
          - step_index: Step index (for generating request_id)
        
        Returns:
          Normalized request copy
        """
        normalized = raw_request.copy()
        
        # 1. Force override task_id
        normalized["task_id"] = runtime_task_id
        
        # 2. Force override subject
        normalized["subject"] = self.runtime_subject
        
        # 3. request_id validation/generation
        req_id = raw_request.get("request_id", "")
        if not _is_valid_request_id(req_id):
            new_req_id = f"vtrm-{runtime_task_id}-{step_index:03d}"
            normalized["request_id"] = new_req_id
            logger.debug(f"Generated request_id: {new_req_id} (replaced invalid: {req_id})")
        
        # 4. Remove model self-reported fields (derived by VTRM)
        normalized.pop("content_label", None)
        normalized.pop("capability_required", None)
        runtime_label = normalized.get("_runtime_content_label")
        if runtime_label not in ("public", "secret/high"):
            normalized.pop("_runtime_content_label", None)
        
        # 5. schema_version validation
        if "schema_version" in normalized:
            if not isinstance(normalized["schema_version"], str):
                normalized.pop("schema_version", None)
        
        return normalized
    
    # ========================
    # Request Validation
    # ========================
    
    def _validate_request(self, request: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Hand-written schema validation (Fail-Closed)
        
        Validates normalized request.
        
        Required fields:
          - task_id, request_id, subject, tool, args
        
        Parameter validation (tool-specific):
          - fs.read/write: path
          - network.send: url, method, body
          - db.read/insert/update: table, key/patch/row
        
        Returns:
          (valid, error_message)
        """
        if not isinstance(request, dict):
            return False, "Request must be a JSON object"
        
        # Required fields
        required_top_fields = ["task_id", "request_id", "subject", "tool", "args"]
        for field_name in required_top_fields:
            if field_name not in request:
                return False, f"Missing required top-level field: '{field_name}'"
        
        # Field type checks
        if not isinstance(request["task_id"], str) or not request["task_id"].strip():
            return False, "task_id must be a non-empty string"
        
        if not isinstance(request["request_id"], str) or not request["request_id"].strip():
            return False, "request_id must be a non-empty string"
        
        if not isinstance(request["subject"], str) or not request["subject"].strip():
            return False, "subject must be a non-empty string"
        
        if not isinstance(request["tool"], str) or request["tool"] not in ALLOWED_TOOLS:
            return False, f"tool must be one of: {sorted(ALLOWED_TOOLS)}"
        
        if not isinstance(request["args"], dict):
            return False, "args must be an object/dict"
        
        # Optional schema_version type check
        if "schema_version" in request and not isinstance(request["schema_version"], str):
            return False, "schema_version must be a string when present"
        
        # Tool-specific args validation
        tool = request["tool"]
        args = request["args"]
        
        if tool == "fs.read":
            if "path" not in args:
                return False, "fs.read requires 'path' in args"
            if not isinstance(args["path"], str) or not args["path"].strip():
                return False, "args.path must be a non-empty string"
        
        elif tool == "fs.write":
            if "path" not in args or "content" not in args:
                return False, "fs.write requires 'path' and 'content' in args"
            if not isinstance(args["path"], str) or not args["path"].strip():
                return False, "args.path must be a non-empty string"
            if not isinstance(args["content"], str):
                return False, "args.content must be a string"

        elif tool == "fs.delete":
            if "path" not in args:
                return False, "fs.delete requires 'path' in args"
            if not isinstance(args["path"], str) or not args["path"].strip():
                return False, "args.path must be a non-empty string"

        elif tool == "network.send":
            if "url" not in args:
                return False, "network.send requires 'url' in args"
            if not isinstance(args["url"], str) or not args["url"].strip():
                return False, "args.url must be a non-empty string"
            if "method" in args and not isinstance(args["method"], str):
                return False, "args.method must be a string when present"
            if "body" in args and args["body"] is not None and not isinstance(args["body"], str):
                return False, "args.body must be a string or null"
        
        elif tool == "db.read":
            if "table" not in args or "key" not in args:
                return False, "db.read requires 'table' and 'key' in args"
            if not isinstance(args["table"], str) or not args["table"].strip():
                return False, "args.table must be a non-empty string"
            if not isinstance(args["key"], str) or not args["key"].strip():
                return False, "args.key must be a non-empty string"
        
        elif tool == "db.insert":
            if "table" not in args or "row" not in args:
                return False, "db.insert requires 'table' and 'row' in args"
            if not isinstance(args["table"], str) or not args["table"].strip():
                return False, "args.table must be a non-empty string"
            if not isinstance(args["row"], dict):
                return False, "args.row must be an object/dict"
        
        elif tool == "db.update":
            if "table" not in args or "key" not in args or "patch" not in args:
                return False, "db.update requires 'table', 'key', and 'patch' in args"
            if not isinstance(args["table"], str) or not args["table"].strip():
                return False, "args.table must be a non-empty string"
            if not isinstance(args["key"], str) or not args["key"].strip():
                return False, "args.key must be a non-empty string"
            if not isinstance(args["patch"], dict) or not args["patch"]:
                return False, "args.patch must be a non-empty object/dict"

        elif tool == "db.delete":
            if "table" not in args or "key" not in args:
                return False, "db.delete requires 'table' and 'key' in args"
            if not isinstance(args["table"], str) or not args["table"].strip():
                return False, "args.table must be a non-empty string"
            if not isinstance(args["key"], str) or not args["key"].strip():
                return False, "args.key must be a non-empty string"
        
        return True, None
    
    # ========================
    # Classification & Derivation (Layer 2)
    # ========================
    
    def _classify_and_derive(
        self,
        tool: str,
        args: Dict[str, Any],
        runtime_content_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classification & derivation (Layer 2)
        
        Derive for request:
          - target_object_class (FileClass or DBClass)
          - sink_class (SinkClass)
          - required_capability (CapabilityRequirement)
          - inferred_conf_label (Label)
        
        Returns dict containing all derivation results
        """
        result = {}
        
        # 1. Derive target object class (for fs and db)
        if tool.startswith("fs."):
            path = args.get("path", "")
            file_class = classify_path(path)
            result["target_object_class"] = file_class.value
            result["file_class"] = file_class  # For subsequent use
        
        elif tool.startswith("db."):
            table = args.get("table", "")
            db_class = db_classify_table(table)
            result["target_object_class"] = db_class.value
            result["db_class"] = db_class  # For subsequent use
        
        # 2. Derive Sink class (for network)
        if tool == "network.send":
            url = args.get("url", "")
            sink_class = classify_sink(url)
            result["sink_class"] = sink_class.value
            result["sink_class_enum"] = sink_class  # For subsequent use
        
        # 3. Derive required capability (returns CapabilityRequirement struct)
        path_class = result.get("file_class") if "file_class" in result else None
        db_class_enum = result.get("db_class") if "db_class" in result else None
        sink_class_enum = result.get("sink_class_enum")
        table = args.get("table") if tool.startswith("db.") else None
        
        cap_req = self.deriver.derive(
            tool=tool,
            path_type=path_class,
            db_class=db_class_enum,
            sink_class=sink_class_enum,
            table=table,
        )
        result["capability_requirement"] = cap_req
        
        # 4. Derive content label (Label)
        result["runtime_label_override"] = runtime_content_label
        inferred_label = self._infer_content_label(tool, args, result)
        result["inferred_label"] = inferred_label.value
        result["label_enum"] = inferred_label
        
        return result
    
    def _infer_content_label(
        self,
        tool: str,
        args: Dict[str, Any],
        classification: Dict[str, Any],
    ) -> Label:
        """
        Infer content_label (do not trust model self-reported)
        
        Rules (based on object class propagation):
          - fs.read: If file_class = SECRET_SOURCE → secret/high
          - fs.write: Inherit content_label (conservatively return public, unless target is secret)
          - db.read: If db_class = SECRET_TABLE → secret/high
          - db.insert / db.update: Check _label field in row/patch
          - network.send: Conservatively return public (checked by policy)
        
        Returns:
          Label enum
        """
        runtime_label = classification.get("runtime_label_override")
        if runtime_label == Label.SECRET_HIGH.value:
            return Label.SECRET_HIGH
        if runtime_label == Label.PUBLIC.value:
            runtime_label = Label.PUBLIC.value

        if tool in ("fs.read", "fs.write", "fs.delete"):
            file_class = classification.get("file_class")
            if file_class:
                if file_class.value == "secret_source":
                    return Label.SECRET_HIGH
                if file_class.value == "protected" and tool == "fs.read":
                    return Label.SECRET_HIGH
            return Label.PUBLIC if runtime_label is None else Label.from_str(runtime_label)
        
        if tool == "db.read":
            db_class = classification.get("db_class")
            if db_class and db_class.value == "secret_table":
                return Label.SECRET_HIGH
            return Label.PUBLIC if runtime_label is None else Label.from_str(runtime_label)
        
        if tool == "db.insert":
            row = args.get("row", {})
            inferred = infer_label_from_row(row)
            if inferred == Label.SECRET_HIGH:
                return Label.SECRET_HIGH
            db_class = classification.get("db_class")
            if db_class and db_class.value == "secret_table":
                return Label.SECRET_HIGH
            return Label.PUBLIC if runtime_label is None else Label.from_str(runtime_label)
        
        if tool == "db.update":
            patch = args.get("patch", {})
            inferred = infer_label_from_row(patch)
            if inferred == Label.SECRET_HIGH:
                return Label.SECRET_HIGH
            db_class = classification.get("db_class")
            if db_class and db_class.value == "secret_table":
                return Label.SECRET_HIGH
            return Label.PUBLIC

        if tool == "db.delete":
            db_class = classification.get("db_class")
            if db_class and db_class.value == "secret_table":
                return Label.SECRET_HIGH
            return Label.PUBLIC if runtime_label is None else Label.from_str(runtime_label)
        
        if tool == "network.send":
            return Label.PUBLIC if runtime_label is None else Label.from_str(runtime_label)

        return Label.PUBLIC
    
    # ========================
    # Authorization Mode Check (Layer 3)
    # ========================
    
    def _check_authorization_mode(
        self,
        tool: str,
        args: Dict[str, Any],
        classification: Dict[str, Any],
        content_label: Label,
    ) -> Tuple[AuthorizationResult, AbsoluteDenyContext]:
        """
        Check authorization mode (Layer 3)
        
        Build AbsoluteDenyContext and call AuthorizationPolicy.
        
        Returns:
          (AuthorizationResult, AbsoluteDenyContext)
        """
        # Build AbsoluteDenyContext
        ctx = AbsoluteDenyContext(
            tool=tool,
            inferred_label=content_label.value,
            sink_class=classification.get("sink_class"),
            schema_valid=True,  # schema validation passed
            tool_valid=True,     # tool already in ALLOWED_TOOLS
            audit_available=self.audit_logger.is_audit_available(),
        )
        
        # Check if target is audit log
        if tool.startswith("fs."):
            path = args.get("path", "")
            if path.startswith("/var/log/sandbox/"):
                ctx.target_is_audit_log = True
        
        # Call AuthorizationPolicy
        cap_req = classification.get("capability_requirement")
        auth_result = self.auth_policy.authorize(
            capability=cap_req.required if cap_req else None,
            derivation_status=cap_req.derivation_status.value if cap_req else "unknown",
            ctx=ctx,
        )
        
        return auth_result, ctx
    
    # ========================
    # Capability Check (Layer 4)
    # ========================
    
    def _capability_check(
        self,
        tool: str,
        classification: Dict[str, Any],
        auth_result: AuthorizationResult,
    ) -> PolicyResult:
        """
        Capability check (Layer 4)
        
        Combine AuthorizationMode and CapabilityRegistry for checking.
        
        Returns:
          PolicyResult
        """
        cap_req = classification.get("capability_requirement")
        
        # Build ctx
        ctx = AbsoluteDenyContext(
            tool=tool,
            inferred_label=classification.get("inferred_label"),
            sink_class=classification.get("sink_class"),
        )
        
        # Call CapabilityRegistry.check
        return self.capability_registry.check(
            tool=tool,
            required_capability=cap_req.required if cap_req else None,
            derivation_status=cap_req.derivation_status.value if cap_req else "unknown",
            path_class=classification.get("file_class"),
            db_class=classification.get("db_class"),
            sink_class=classification.get("sink_class_enum"),
            ctx=ctx,
        )
    
    # ========================
    # Approval Token Check (Layer 5)
    # ========================
    
    def _check_approval_token(
        self,
        request: Dict[str, Any],
        classification: Dict[str, Any],
        tool: str,
        args: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], str]:
        """
        Check approval token
        
        Used for approval_required scenarios.
        Caller must provide valid token to execute.
        
        Parameters:
          - request: Normalized request
          - classification: Classification result
          - tool: Tool type
          - args: Tool arguments
        
        Returns:
          (token_valid, approval_id, reason)
        """
        # Extract token from request
        token = request.get("args", {}).get("_approval_token")
        if not token:
            return False, None, "No approval token provided"
        
        # Get scope target
        scope_target = ""
        if tool.startswith("fs."):
            scope_target = args.get("path", "")
        elif tool == "network.send":
            scope_target = args.get("url", "")
        elif tool.startswith("db."):
            scope_target = args.get("table", "")
        
        # Verify token
        valid, reason = self.approval_store.verify_token(
            token_str=token,
            approval_id=classification.get("approval_id", ""),
            task_id=request["task_id"],
            request_id=request["request_id"],
            tool=tool,
            scope_target=scope_target,
        )
        
        return valid, classification.get("approval_id"), reason
    
    # ========================
    # Core Evaluation (Layer 3-4)
    # ========================
    
    def evaluate(
        self,
        raw_request: Dict[str, Any],
        *,
        runtime_task_id: str,
        step_index: int = 0,
        skip_approval_check: bool = False,  # For testing or manual invocation
    ) -> VTRMDecision:
        """
        Evaluate request (return decision without executing)
        
        Flow:
          1. Normalize: Sanitize metadata
          2. Validate: Strict schema validation
          3. Classify & Derive: Object classification + capability/label derivation
          4. Authorization Mode Check: Authorization mode determination
          5. Capability Check: Capability verification
          6. Approval Token Check: Check token (if present)
          7. Audit: Record decision
        
        Parameters:
          - raw_request: Original request (from model or runner)
          - runtime_task_id: Runtime task_id (overrides model self-reported)
          - step_index: Step index (for generating request_id)
          - skip_approval_check: Whether to skip approval token check (default no)
        
        Returns:
          VTRMDecision (decision only, no side effects)
        """
        start_time = time.time()
        
        # ========== Step 1: Normalize ==========
        request = self.normalize_request(raw_request, runtime_task_id, step_index)
        
        # ========== Step 2: Validate ==========
        valid, validation_error = self._validate_request(request)
        if not valid:
            return self._fail_decision(
                request=request,
                reason=f"Schema validation failed: {validation_error}",
                start_time=start_time,
                rule="invalid_schema",
            )
        
        # ========== Step 3: Extract fields ==========
        task_id = request["task_id"]
        request_id = request["request_id"]
        subject = request["subject"]
        tool = request["tool"]
        args = request["args"]
        
        # ========== Step 4: Classify & Derive ==========
        classification = self._classify_and_derive(
            tool,
            args,
            runtime_content_label=request.get("_runtime_content_label"),
        )
        content_label = classification["label_enum"]
        cap_req = classification["capability_requirement"]
        target_object_class = classification.get("target_object_class")
        sink_class = classification.get("sink_class")
        
        # ========== Step 5: Authorization Mode Check ==========
        auth_result, deny_ctx = self._check_authorization_mode(
            tool, args, classification, content_label
        )

        # ========== Step 6: Capability holding check (only for AUTO mode) ==========
        # Note: APPROVAL_REQUIRED mode does not check capability holding, goes through approval flow
        # This allows users to approve requests in test environment
        if auth_result.mode == AuthorizationMode.DENY:
            return self._fail_decision(
                request=request,
                reason=auth_result.reason,
                start_time=start_time,
                tool=tool,
                args=args,
                metadata={
                    "target_object_class": target_object_class,
                    "required_capability": cap_req.required,
                    "inferred_label": content_label.value,
                    "sink_class": sink_class,
                },
                rule=auth_result.rule,
            )

        if auth_result.mode == AuthorizationMode.APPROVAL_REQUIRED:
            return self._approval_required_decision(
                request=request,
                tool=tool,
                args=args,
                classification=classification,
                content_label=content_label,
                auth_result=auth_result,
                start_time=start_time,
                skip_token_check=skip_approval_check,
            )

        # AUTO mode: Check capability holding
        if cap_req.derivation_status == DerivationStatus.OK and cap_req.required:
            if not self.capability_registry.has_capability(cap_req.required):
                return self._fail_decision(
                    request=request,
                    reason=f"Agent does not have capability: '{cap_req.required}'",
                    start_time=start_time,
                    tool=tool,
                    args=args,
                    metadata={
                        "target_object_class": target_object_class,
                        "required_capability": cap_req.required,
                        "inferred_label": content_label.value,
                        "sink_class": sink_class,
                    },
                    rule="capability_not_held",
                )
        
        # ========== Step 7: Allow (auto) ==========
        cap_result = self.capability_registry.check(
            tool=tool,
            required_capability=cap_req.required,
            derivation_status=cap_req.derivation_status.value,
            path_class=classification.get("file_class"),
            db_class=classification.get("db_class"),
            sink_class=classification.get("sink_class_enum"),
            ctx=deny_ctx,
        )

        elapsed = (time.time() - start_time) * 1000.0
        effect_type = EFFECT_MAP.get(tool, "Unknown")

        # Log allow audit
        self.audit_logger.log_request(
            task_id=task_id,
            request_id=request_id,
            subject=subject,
            tool=tool,
            args=args,
            decision=AuditDecision.AUTO.value,
            effect=AuditEvent.effect_from_tool(tool),
            status=AuditStatus.PENDING.value,
            reason=f"Auto allow: {cap_result.reason}",
            execution_time_ms=elapsed,
            metadata={
                **cap_result.metadata,
                "target_object_class": target_object_class,
                "required_capability": cap_req.required,
                "inferred_label": content_label.value,
                "sink_class": sink_class,
                "_eval_only": True,
            },
            rule=cap_result.rule,
        )
        
        return VTRMDecision(
            allowed=True,
            decision=AuditDecision.AUTO.value,
            request_id=request_id,
            task_id=task_id,
            subject=subject,
            tool=tool,
            reason=cap_result.reason,
            effect_type=effect_type,
            target_object_class=target_object_class,
            sink_class=sink_class,
            required_capability=cap_req.required,
            inferred_label=content_label.value,
            rule=cap_result.rule,
            metadata={
                **cap_result.metadata,
                "_eval_time_ms": elapsed,
                "_start_time": start_time,
            },
        )
    
    def _approval_required_decision(
        self,
        request: Dict[str, Any],
        tool: str,
        args: Dict[str, Any],
        classification: Dict[str, Any],
        content_label: Label,
        auth_result: AuthorizationResult,
        start_time: float,
        skip_token_check: bool = False,
    ) -> VTRMDecision:
        """
        Handle approval_required decision
        
        Creates ApprovalRequest and returns.
        """
        elapsed = (time.time() - start_time) * 1000.0
        cap_req = classification["capability_requirement"]
        
        # Generate approval_id
        approval_id = f"apr-{uuid.uuid4().hex[:12]}"
        classification["approval_id"] = approval_id
        
        # Build effect preview
        preview = self._build_effect_preview(tool, args, classification)
        
        # Create ApprovalRequest
        approval = ApprovalRequest(
            approval_id=approval_id,
            task_id=request["task_id"],
            request_id=request["request_id"],
            subject=request["subject"],
            tool=tool,
            normalized_args=args.copy(),
            object_class=classification.get("target_object_class"),
            sink_class=classification.get("sink_class"),
            db_class=classification.get("db_class").value if classification.get("db_class") else None,
            required_capability=cap_req.required,
            inferred_label=content_label.value,
            risk_level=self._estimate_risk_level(tool, args, content_label, classification),
            preview=preview,
        )
        
        # Save to approval store
        self.approval_store.create_approval(approval)
        
        # Log audit
        self.audit_logger.log_request(
            task_id=request["task_id"],
            request_id=request["request_id"],
            subject=request["subject"],
            tool=tool,
            args=args,
            decision=AuditDecision.APPROVAL_REQUIRED.value,
            effect=AuditEffect.NONE.value,
            status=AuditStatus.PENDING.value,
            reason=auth_result.reason,
            execution_time_ms=elapsed,
            metadata={
                "target_object_class": classification.get("target_object_class"),
                "required_capability": cap_req.required,
                "inferred_label": content_label.value,
                "sink_class": classification.get("sink_class"),
                "preview": preview.to_dict() if preview else {},
            },
            approval_id=approval_id,
            rule=auth_result.rule,
        )
        
        return VTRMDecision(
            allowed=False,
            decision=AuditDecision.APPROVAL_REQUIRED.value,
            request_id=request["request_id"],
            task_id=request["task_id"],
            subject=request["subject"],
            tool=tool,
            reason=f"{auth_result.reason} (approval_id={approval_id})",
            effect_type="None",
            target_object_class=classification.get("target_object_class"),
            sink_class=classification.get("sink_class"),
            required_capability=cap_req.required,
            inferred_label=content_label.value,
            approval_id=approval_id,
            rule=auth_result.rule,
            metadata={
                "approval_id": approval_id,
                "preview": preview.to_dict() if preview else {},
                "_eval_time_ms": elapsed,
            },
        )
    
    def _build_effect_preview(
        self,
        tool: str,
        args: Dict[str, Any],
        classification: Dict[str, Any],
    ) -> EffectPreview:
        """Build normalized effect preview"""
        preview = EffectPreview(
            effect_type=tool.replace(".", "_"),
            inferred_label=classification.get("inferred_label", "public"),
            target_class=classification.get("target_object_class") or classification.get("sink_class", ""),
        )
        
        if tool.startswith("fs."):
            preview.target = args.get("path", "")
            if tool == "fs.read":
                preview.effect_type = "fs_read"
            elif tool == "fs.write":
                preview.effect_type = "fs_write"
            else:
                preview.effect_type = "fs_delete"
        
        elif tool == "network.send":
            preview.target = args.get("url", "")
            preview.payload_summary = self.audit_logger.digest_args({"url": preview.target})
        
        elif tool.startswith("db."):
            preview.target = args.get("table", "")
            if tool == "db.insert":
                preview.old_new_preview = f"insert into {preview.target}"
            elif tool == "db.update":
                preview.old_new_preview = f"update {preview.target} key={args.get('key', '')}"
            elif tool == "db.delete":
                preview.old_new_preview = f"delete from {preview.target} key={args.get('key', '')}"
        
        return preview
    
    def _estimate_risk_level(
        self,
        tool: str,
        args: Dict[str, Any],
        content_label: Label,
        classification: Dict[str, Any],
    ) -> str:
        """Estimate risk level"""
        # High risk indicators
        if content_label == Label.SECRET_HIGH:
            return "high"
        
        if tool in ("fs.write", "fs.delete", "db.insert", "db.update", "db.delete"):
            return "medium"
        
        if classification.get("sink_class") == "external_untrusted":
            return "high"
        
        return "low"
    
    def _fail_decision(
        self,
        request: Dict[str, Any],
        reason: str,
        start_time: float,
        tool: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        rule: str = "",
    ) -> VTRMDecision:
        """
        Generate fail decision (deny)
        
        Also logs audit.
        """
        elapsed = (time.time() - start_time) * 1000.0
        
        task_id = str(request.get("task_id", "unknown-task"))
        request_id = str(request.get("request_id", "unknown-request"))
        subject = str(request.get("subject", "unknown-subject"))
        tool = tool if tool is not None else str(request.get("tool", "unknown"))
        args = args if args is not None else request.get("args", {})
        if not isinstance(args, dict):
            args = {"_raw_args": repr(args)}
        
        # Log audit
        self.audit_logger.log_request(
            task_id=task_id,
            request_id=request_id,
            subject=subject,
            tool=tool,
            args=args,
            decision=AuditDecision.DENY.value,
            effect=AuditEffect.NONE.value,
            status=AuditStatus.SKIPPED.value,
            reason=reason,
            execution_time_ms=elapsed,
            metadata=metadata or {},
            rule=rule,
        )
        
        return VTRMDecision(
            allowed=False,
            decision=AuditDecision.DENY.value,
            request_id=request_id,
            task_id=task_id,
            subject=subject,
            tool=tool,
            reason=reason,
            effect_type="None",
            rule=rule,
            metadata=metadata or {},
        )
    
    # ========================
    # Execution (Layer 6)
    # ========================
    
    def execute(
        self,
        raw_request: Dict[str, Any],
        *,
        runtime_task_id: str,
        step_index: int = 0
    ) -> Tuple[bool, Any]:
        """
        Execute request (evaluate + execute)
        
        Flow:
          1. evaluate() performs policy check
          2. If approval_required: return approval_id
          3. If deny: return failure
          4. If allow:
             a. Audit fail-closed check
             b. Pre-write audit log (pending)
             c. Execute actual operation
             d. Update audit log to success or failure
        
        Parameters:
          - raw_request: Original request
          - runtime_task_id: Runtime task_id
          - step_index: Step index
        
        Returns:
          (success: bool, result: Any)
        """
        # Evaluate
        decision = self.evaluate(
            raw_request,
            runtime_task_id=runtime_task_id,
            step_index=step_index,
        )
        
        # Handle approval_required
        if decision.decision == AuditDecision.APPROVAL_REQUIRED.value:
            return False, f"PENDING_APPROVAL: approval_id={decision.approval_id}"
        
        # Handle deny
        if decision.decision == AuditDecision.DENY.value:
            return False, f"DENY: {decision.reason}"
        
        # ========== AUTO ALLOW ==========
        
        # Audit fail-closed check
        effect = AuditEvent.effect_from_tool(decision.tool)
        if not self.audit_logger.check_mutation_audit(
            decision.decision,
            effect
        ):
            # Audit unavailable, deny mutation
            self._log_mutation_audit_failure(decision)
            return False, "DENY: Audit unavailable for mutation - fail-closed"
        
        # Pre-write audit log (pending)
        normalized_args = raw_request.get("args", {})
        if not isinstance(normalized_args, dict):
            normalized_args = {"_raw_args": repr(normalized_args)}
        
        start_time = decision.metadata.get("_start_time", time.time())
        
        pending_event, audit_written = self.audit_logger.log_request(
            task_id=decision.task_id,
            request_id=decision.request_id,
            subject=decision.subject,
            tool=decision.tool,
            args=normalized_args,
            decision=AuditDecision.AUTO.value,
            effect=effect,
            status=AuditStatus.PENDING.value,
            reason=f"Effect: {decision.effect_type} operation pending",
            metadata={
                **decision.metadata,
                "effect_status": "pending",
            },
        )
        
        # If audit write fails (for mutation), fail-closed
        if not audit_written and AuditEvent.is_mutation_effect(effect):
            self._log_mutation_audit_failure(decision)
            return False, "DENY: Audit write failed for mutation - fail-closed"
        
        # Execute
        try:
            result = self._execute_operation(raw_request, decision)
            
            # Execution success, log success
            elapsed = (time.time() - start_time) * 1000.0
            success_event, _ = self.audit_logger.log_request(
                task_id=decision.task_id,
                request_id=decision.request_id,
                subject=decision.subject,
                tool=decision.tool,
                args=normalized_args,
                decision=AuditDecision.AUTO.value,
                effect=effect,
                status=AuditStatus.SUCCESS.value,
                reason=f"Effect: {decision.effect_type} operation completed",
                execution_time_ms=elapsed,
                metadata={
                    **decision.metadata,
                    "effect_status": "success",
                },
            )
            
            return True, result
        
        except Exception as e:
            logger.error(f"Execution error: {e}", exc_info=True)
            
            # Execution failure, log failure
            try:
                elapsed = (time.time() - start_time) * 1000.0
                error_event, _ = self.audit_logger.log_request(
                    task_id=decision.task_id,
                    request_id=decision.request_id,
                    subject=decision.subject,
                    tool=decision.tool,
                    args=normalized_args,
                    decision=AuditDecision.AUTO.value,
                    effect=effect,
                    status=AuditStatus.FAILURE.value,
                    reason=f"Execution failed: {e}",
                    error_detail=str(e),
                    execution_time_ms=elapsed,
                    metadata={
                        **decision.metadata,
                        "error": str(e),
                        "effect_status": "failed",
                    },
                )
            except Exception as audit_err:
                logger.error(f"Failed to write error audit: {audit_err}")
            
            return False, str(e)
    
    def _log_mutation_audit_failure(self, decision: VTRMDecision) -> None:
        """Log mutation audit failure"""
        self.audit_logger.log_request(
            task_id=decision.task_id,
            request_id=decision.request_id,
            subject=decision.subject,
            tool=decision.tool,
            args={},
            decision=AuditDecision.DENY.value,
            effect=AuditEffect.NONE.value,
            status=AuditStatus.SKIPPED.value,
            reason="Mutation denied due to audit unavailability (fail-closed)",
            metadata={
                **decision.metadata,
                "effect_status": "skipped",
                "_fail_closed": True,
            },
            rule="audit_unavailable_mutation",
        )
    
    def _execute_operation(
        self,
        request: Dict[str, Any],
        decision: VTRMDecision,
    ) -> Any:
        """
        Execute actual operation (call backend)
        
        Note: At this point, has passed evaluate validation, should execute directly.
        """
        tool = request["tool"]
        args = request["args"]
        
        if tool == "fs.read":
            return self._fs_read(args)
        if tool == "fs.write":
            return self._fs_write(args)
        if tool == "fs.delete":
            return self._fs_delete(args)
        if tool == "network.send":
            return self._network_send(args)
        if tool == "db.read":
            return self._db_read(args)
        if tool == "db.insert":
            return self._db_insert(args)
        if tool == "db.update":
            return self._db_update(args)
        if tool == "db.delete":
            return self._db_delete(args)
        
        raise VTRError(f"Unknown tool: {tool}")
    
    def _fs_read(self, args: Dict[str, Any]) -> str:
        """Execute file read"""
        path = args["path"]
        try:
            canonical = canonicalize_path(path)
            return Path(canonical).read_text()
        except Exception as e:
            raise VTRError(f"Failed to read {path}: {e}")
    
    def _fs_write(self, args: Dict[str, Any]) -> str:
        """Execute file write"""
        path = args["path"]
        content = args.get("content", "")
        try:
            canonical = canonicalize_path(path)
            Path(canonical).parent.mkdir(parents=True, exist_ok=True)
            Path(canonical).write_text(content)
            return "OK"
        except Exception as e:
            raise VTRError(f"Failed to write {path}: {e}")
    
    def _fs_delete(self, args: Dict[str, Any]) -> str:
        """Delete a file."""
        path = args["path"]
        try:
            canonical = canonicalize_path(path)
            target = Path(canonical)
            if target.is_dir():
                raise VTRError(f"Refusing to delete directory {path}: fs.delete only supports files")
            if not target.exists() and not target.is_symlink():
                raise VTRError(f"Failed to delete {path}: file not found")
            target.unlink()
            return "OK"
        except VTRError:
            raise
        except Exception as e:
            raise VTRError(f"Failed to delete {path}: {e}")

    def _network_send(self, args: Dict[str, Any]) -> str:
        """Execute network request"""
        import subprocess
        import urllib.error
        import urllib.request

        url = args["url"]
        method = str(args.get("method", "GET")).upper()
        body = args.get("body")

        data = None
        headers: Dict[str, str] = {}
        if body is not None:
            data = str(body).encode("utf-8")
            headers["Content-Type"] = "text/plain; charset=utf-8"

        request = urllib.request.Request(url=url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise VTRError(f"Network request failed: HTTP {exc.code} {exc.reason}; body={error_body!r}")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            # Fall back to curl for environments where urllib networking is missing pieces.
            cmd = ["curl", "-sS", "-X", method, url]
            if body is not None:
                cmd.extend(["--data-binary", str(body)])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                stdout = (result.stdout or "").strip()
                detail = stderr or stdout or repr(reason)
                raise VTRError(f"Network request failed: {detail}")
            return result.stdout
        except Exception as exc:
            raise VTRError(f"Network request failed: {exc!r}")
    
    def _db_read(self, args: Dict[str, Any]) -> Any:
        """Execute database read"""
        try:
            from .db_ops import DBOperations
        except ImportError:
            raise VTRError("sqlite3 not available")
        
        db_path = os.environ.get("VTRM_DB_PATH", "/var/lib/agentos/agent.db")
        db = DBOperations(db_path)
        result = db.read(args["table"], args["key"])
        
        if not result.success:
            raise VTRError(result.error or "DB read failed")
        return result.data
    
    def _db_insert(self, args: Dict[str, Any]) -> str:
        """Execute database insert"""
        try:
            from .db_ops import DBOperations
        except ImportError:
            raise VTRError("sqlite3 not available")
        
        db_path = os.environ.get("VTRM_DB_PATH", "/var/lib/agentos/agent.db")
        db = DBOperations(db_path)
        result = db.insert(args["table"], args["row"])
        
        if not result.success:
            raise VTRError(result.error or "DB insert failed")
        return "OK"
    
    def _db_update(self, args: Dict[str, Any]) -> str:
        """Execute database update"""
        try:
            from .db_ops import DBOperations
        except ImportError:
            raise VTRError("sqlite3 not available")
        
        db_path = os.environ.get("VTRM_DB_PATH", "/var/lib/agentos/agent.db")
        db = DBOperations(db_path)
        result = db.update(args["table"], args["key"], args["patch"])
        
        if not result.success:
            raise VTRError(result.error or "DB update failed")
        return "OK"

    def _db_delete(self, args: Dict[str, Any]) -> str:
        """Execute database delete."""
        try:
            from .db_ops import DBOperations
        except ImportError:
            raise VTRError("sqlite3 not available")

        db_path = os.environ.get("VTRM_DB_PATH", "/var/lib/agentos/agent.db")
        db = DBOperations(db_path)
        result = db.delete(args["table"], args["key"])

        if not result.success:
            raise VTRError(result.error or "DB delete failed")
        return "OK"
    
    # ========================
    # Approval Workflow
    # ========================
    
    def approve(
        self,
        approval_id: str,
        approver: str = "system",
    ) -> Tuple[bool, Optional[str]]:
        """
        Approve request
        
        Parameters:
          - approval_id: Approval ID
          - approver: Approver
        
        Returns:
          (success, token) - Whether successful, and issued token
        """
        approval = self.approval_store.get_approval(approval_id)
        if not approval:
            return False, "Approval not found"
        
        if not approval.is_pending():
            return False, f"Approval is not pending: {approval.status}"
        
        if approval.is_expired():
            return False, "Approval expired"
        
        # Update status
        self.approval_store.update_approval_status(
            approval_id,
            ApprovalStatus.APPROVED,
            approver=approver,
        )
        
        # Re-fetch updated approval
        approval = self.approval_store.get_approval(approval_id)
        
        # Generate token
        scope_target = ""
        scope_class = ""
        
        if approval.tool.startswith("fs."):
            scope_target = approval.normalized_args.get("path", "")
        elif approval.tool == "network.send":
            scope_target = approval.normalized_args.get("url", "")
        elif approval.tool.startswith("db."):
            scope_target = approval.normalized_args.get("table", "")
        
        scope_class = approval.object_class or approval.sink_class or approval.db_class or ""
        
        token = ApprovalToken.generate(
            approval=approval,
            scope_target=scope_target,
            scope_class=scope_class,
        )
        
        # Save token
        self.approval_store.save_token(token)
        
        # Update approval associated token
        self.approval_store.update_approval_status(
            approval_id,
            ApprovalStatus.APPROVED,
        )
        
        logger.info(f"Approval granted: {approval_id}, token issued")
        
        return True, token.token
    
    def execute_with_approval(
        self,
        raw_request: Dict[str, Any],
        approval_token: str,
        runtime_task_id: str,
        step_index: int = 0,
    ) -> Tuple[bool, Any]:
        """
        Execute request with approval token
        
        Parameters:
          - raw_request: Original request
          - approval_token: Approved token
          - runtime_task_id: Runtime task_id
          - step_index: Step index
        
        Returns:
          (success, result)
        """
        # Evaluate first (skip approval_required)
        decision = self.evaluate(
            raw_request,
            runtime_task_id=runtime_task_id,
            step_index=step_index,
            skip_approval_check=True,
        )
        
        # Manually check approval token
        valid, approval_id, reason = self._check_approval_token(
            request=self.normalize_request(raw_request, runtime_task_id, step_index),
            classification={"approval_id": "", "sink_class": None},
            tool=raw_request["tool"],
            args=raw_request.get("args", {}),
        )
        
        if not valid:
            return False, f"DENY: Invalid approval token - {reason}"
        
        # Mark token as used
        self.approval_store.mark_token_used(approval_token)
        
        # Continue execution (bypass approval_required)
        # Here reuse execute logic, but need to pass approval_id
        return self._execute_with_approval_token(
            raw_request,
            decision,
            approval_token,
            runtime_task_id,
        )
    
    def _execute_with_approval_token(
        self,
        raw_request: Dict[str, Any],
        decision: VTRMDecision,
        approval_token: str,
        runtime_task_id: str,
    ) -> Tuple[bool, Any]:
        """Execute with approval token"""
        # Audit fail-closed check
        effect = AuditEvent.effect_from_tool(decision.tool)
        if not self.audit_logger.check_mutation_audit(
            decision.decision,
            effect
        ):
            return False, "DENY: Audit unavailable for mutation - fail-closed"
        
        # Pre-write audit log
        normalized_args = raw_request.get("args", {})
        if not isinstance(normalized_args, dict):
            normalized_args = {"_raw_args": repr(normalized_args)}
        
        start_time = decision.metadata.get("_start_time", time.time())
        
        pending_event, audit_written = self.audit_logger.log_request(
            task_id=decision.task_id,
            request_id=decision.request_id,
            subject=decision.subject,
            tool=decision.tool,
            args=normalized_args,
            decision=AuditDecision.AUTO.value,
            effect=effect,
            status=AuditStatus.PENDING.value,
            reason=f"Effect: {decision.effect_type} operation pending (with approval)",
            metadata={
                **decision.metadata,
                "effect_status": "pending",
                "_approval_token_used": True,
            },
            approval_id=decision.approval_id,
        )
        
        # Execute
        try:
            result = self._execute_operation(raw_request, decision)
            
            # Execution success
            elapsed = (time.time() - start_time) * 1000.0
            self.audit_logger.log_request(
                task_id=decision.task_id,
                request_id=decision.request_id,
                subject=decision.subject,
                tool=decision.tool,
                args=normalized_args,
                decision=AuditDecision.AUTO.value,
                effect=effect,
                status=AuditStatus.SUCCESS.value,
                reason=f"Effect: {decision.effect_type} operation completed (approved)",
                execution_time_ms=elapsed,
                metadata={
                    **decision.metadata,
                    "effect_status": "success",
                    "_approval_token_used": True,
                },
                approval_id=decision.approval_id,
            )
            
            return True, result
        
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000.0
            self.audit_logger.log_request(
                task_id=decision.task_id,
                request_id=decision.request_id,
                subject=decision.subject,
                tool=decision.tool,
                args=normalized_args,
                decision=AuditDecision.AUTO.value,
                effect=effect,
                status=AuditStatus.FAILURE.value,
                reason=f"Execution failed: {e}",
                error_detail=str(e),
                execution_time_ms=elapsed,
                metadata={
                    **decision.metadata,
                    "effect_status": "failed",
                    "_approval_token_used": True,
                },
                approval_id=decision.approval_id,
            )
            
            return False, str(e)
    
    # ========================
    # Statistics
    # ========================
    
    def get_audit_stats(self) -> Dict[str, int]:
        """Get audit statistics"""
        return self.audit_logger.get_stats()
