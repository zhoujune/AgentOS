"""
vtrm - Verified Toolchain Reference Monitor

Line B Security Core: Provides unified policy checking, audit logging, and state tracking for agent tool calls.

Module Structure:
  - vtrm_core.py: VTRM Core (evaluate + execute)
  - policy.py: Policy Engine (CapabilityRegistry, PathPolicy, NetworkPolicy, DBPolicy)
  - authorization_policy.py: Authorization Mode Policy (AuthorizationPolicy, AbsoluteDenyChecker)
  - approval_store.py: Approval Store (ApprovalStore, ApprovalRequest, ApprovalToken)
  - path_classifier.py: File Path Classifier (FileClass)
  - db_classifier.py: Database Object Classifier (DBClass)
  - sink_classifier.py: Network Sink Classifier (SinkClass)
  - label_model.py: Content Label Model (Label, LabeledData, join_labels)
  - capability_deriver.py: Capability Deriver
  - audit_logger.py: Audit Logger

Usage Example:
    from vtrm import VTRMCore
    
    vtrm = VTRMCore(agent_capabilities={"fs.read", "fs.write.workspace"})
    decision = vtrm.evaluate(
        {
            "tool": "fs.write",
            "args": {"path": "/workspace/out.txt", "content": "hello"},
            "request_id": "req-001",
            "task_id": "task-001",
            "subject": "agent-default",
        },
        runtime_task_id="task-001",
        step_index=0
    )
    
    if decision.allowed:
        success, result = vtrm.execute(...)
"""

from .vtrm_core import VTRMCore, VTRMDecision, VTRError
from .policy import (
    Decision as PolicyDecision,
    PolicyResult,
    CapabilityRegistry,
    PathPolicy,
    NetworkPolicy,
    DBPolicy,
)
from .authorization_policy import (
    AuthorizationPolicy,
    AuthorizationMode,
    AuthorizationResult,
    AbsoluteDenyChecker,
    AbsoluteDenyContext,
    AuthorizationProfile,
    create_agent_default_profile,
)
from .approval_store import (
    ApprovalStore,
    ApprovalRequest,
    ApprovalToken,
    EffectPreview,
    get_approval_store,
)
from .label_model import Label, LabeledData
from .path_classifier import FileClass, classify_path, canonicalize_path
from .db_classifier import DBClass, classify_table
from .sink_classifier import SinkClass, classify_sink
from .capability_deriver import (
    CapabilityDeriver,
    CapabilityRequirement,
    DerivationStatus,
    derive_capability,
)
from .audit_logger import AuditLogger, AuditEvent, AuditDecision, AuditEffect, AuditStatus

__all__ = [
    # Core
    "VTRMCore",
    "VTRMDecision",
    "VTRError",
    
    # Policy
    "Decision",
    "PolicyResult",
    "CapabilityRegistry",
    "PathPolicy",
    "NetworkPolicy",
    "DBPolicy",
    
    # Authorization
    "AuthorizationPolicy",
    "AuthorizationMode",
    "AuthorizationResult",
    "AbsoluteDenyChecker",
    "AbsoluteDenyContext",
    "AuthorizationProfile",
    "create_agent_default_profile",
    
    # Approval
    "ApprovalStore",
    "ApprovalRequest",
    "ApprovalToken",
    "EffectPreview",
    "get_approval_store",
    
    # Classifiers
    "Label",
    "LabeledData",
    "FileClass",
    "classify_path",
    "canonicalize_path",
    "DBClass",
    "classify_table",
    "SinkClass",
    "classify_sink",
    
    # Derivation
    "CapabilityDeriver",
    "CapabilityRequirement",
    "DerivationStatus",
    "derive_capability",
    
    # Audit
    "AuditLogger",
    "AuditEvent",
    "AuditDecision",
    "AuditEffect",
    "AuditStatus",
]
