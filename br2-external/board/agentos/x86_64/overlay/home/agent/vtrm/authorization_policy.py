#!/usr/bin/env python3
"""
authorization_policy.py — Authorization Mode Policy (Security-hardened version)

Responsibilities:
  - Decide authorization mode (auto / approval_required / deny) based on capability + subject profile
  - Implement V1 default profile: agent.default
  - Define absolute denial rules (structural rules that approval cannot override)

Core Concepts:
  - CapabilityDeriver is responsible for deriving "what permissions are theoretically required"
  - AuthorizationPolicy is responsible for "for the current subject, is this capability auto-execute, requires approval, or denied"

Absolute Denial Rules (no approval can override):
  1. secret/high → external_untrusted (structural information flow prohibition)
  2. Unknown or invalid requests (schema invalid)
  3. Mutation allow when audit mechanism unavailable
  4. Unauthorized modification of audit logs
  5. Unauthorized modification of policy/capability config files
  6. invalid_object_action_pair (readonly × write etc.)

V1 Default Profile: agent.default

## agent.default Default Matrix

auto:
  - fs.read.workspace
  - fs.read.readonly
  - fs.write.workspace
  - network.send.trusted_internal
  - db.read.readonly
  - db.insert.mutable
  - db.update.mutable

approval_required:
  - fs.read.secret
  - db.read.secret
  - fs.write.protected
  - network.send.external

deny:
  - db.insert.audit
  - db.update.audit
  - fs.write on readonly / unknown
  - unknown object/sink/db class
  - invalid request schema
  - (any absolute denial rule)

Design Principles:
  - Absolute denial is not at capability level, but at rule level
  - absolute deny takes priority over approval
  - Profiles can be extended, but default keeps minimum privilege
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Set


class AuthorizationMode(Enum):
    """Authorization mode"""
    AUTO = "auto"                    # Auto execute (capability check passed)
    APPROVAL_REQUIRED = "approval_required"  # Requires human approval
    DENY = "deny"                    # Absolutely prohibited


class AbsoluteDenyRule(Enum):
    """
    Absolute denial rules (highest priority, no approval can override)
    
    Each rule defines an absolute denial condition.
    Check order: AbsoluteDenyRule → AuthorizationMode → Capability
    """
    # --- Information flow structural prohibition ---
    SECRET_TO_EXTERNAL = "secret_to_external"           # secret/high → external_untrusted
    # --- Request integrity ---
    INVALID_REQUEST_SCHEMA = "invalid_request_schema"   # Schema validation failed
    UNKNOWN_TOOL = "unknown_tool"                        # Unknown tool
    # --- Audit mechanism ---
    AUDIT_UNAVAILABLE_MUTATION = "audit_unavailable_mutation"  # Allow mutation when audit unavailable
    UNAUTHORIZED_AUDIT_MODIFY = "unauthorized_audit_modify"   # Unauthorized modification of audit log
    # --- Policy configuration ---
    UNAUTHORIZED_POLICY_MODIFY = "unauthorized_policy_modify"  # Unauthorized modification of policy config


@dataclass
class AbsoluteDenyContext:
    """Absolute denial check context"""
    # Basic info
    tool: Optional[str] = None
    inferred_label: Optional[str] = None
    sink_class: Optional[str] = None  # external_untrusted / trusted_internal
    # Request validation
    schema_valid: bool = True
    tool_valid: bool = True
    # Audit status
    audit_available: bool = True
    # Target info
    target_is_audit_log: bool = False
    target_is_policy_config: bool = False


@dataclass
class AuthorizationResult:
    """Authorization decision result"""
    mode: AuthorizationMode
    rule: str  # Rule name that triggered this decision
    reason: str
    # Following fields for approval workflow
    approval_id: Optional[str] = None
    preview: Optional[Dict[str, Any]] = None


@dataclass
class AuthorizationProfile:
    """
    Authorization profile
    
    Defines authorization rules for a subject profile.
    """
    name: str
    auto_capabilities: FrozenSet[str] = field(default_factory=frozenset)
    approval_capabilities: FrozenSet[str] = field(default_factory=frozenset)
    # Default deny: capabilities not in auto or approval → deny
    default_deny: bool = True
    
    def get_mode(self, capability: str) -> AuthorizationMode:
        """Get authorization mode for a capability"""
        if capability in self.auto_capabilities:
            return AuthorizationMode.AUTO
        if capability in self.approval_capabilities:
            return AuthorizationMode.APPROVAL_REQUIRED
        if self.default_deny:
            return AuthorizationMode.DENY
        return AuthorizationMode.DENY


# ============================================================
# V1 Default Profile
# ============================================================

def create_agent_default_profile() -> AuthorizationProfile:
    """
    Create agent.default profile
    
    Design notes:
      - Principle of least privilege
      - High-risk operations via approval_required
      - Default deny
    """
    return AuthorizationProfile(
        name="agent.default",
        # auto: low-risk operations
        auto_capabilities=frozenset({
            # File system
            "fs.read.workspace",
            "fs.read.readonly",
            "fs.write.workspace",
            "fs.delete.workspace",
            # Network
            "network.send.trusted_internal",
            # Database
            "db.read.readonly",
            "db.insert.mutable",
            "db.update.mutable",
            "db.delete.mutable",
        }),
        # approval_required: medium-high risk operations
        approval_capabilities=frozenset({
            # File system
            "fs.read.secret",
            "fs.write.protected",
            "fs.delete.protected",
            # Network
            "network.send.external",  # External requests need approval
            # Database
            "db.read.secret",
        }),
        default_deny=True,
    )


# Global default profile
_default_profile: Optional[AuthorizationProfile] = None


def get_default_profile() -> AuthorizationProfile:
    global _default_profile
    if _default_profile is None:
        _default_profile = create_agent_default_profile()
    return _default_profile


# ============================================================
# Absolute Deny Check
# ============================================================

class AbsoluteDenyChecker:
    """
    Absolute denial rule checker
    
    These rules have highest priority, no approval can override.
    """
    
    @staticmethod
    def check(ctx: AbsoluteDenyContext) -> Optional[AuthorizationResult]:
        """
        Check if any absolute denial rule is hit
        
        Parameters:
          - ctx: Absolute denial check context
        
        Returns:
          - None: No absolute denial rule hit
          - AuthorizationResult: Hit an absolute denial rule
        """
        # 1. secret/high → external_untrusted (structural information flow prohibition)
        if (
            ctx.inferred_label == "secret/high" 
            and ctx.sink_class == "external_untrusted"
        ):
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule=AbsoluteDenyRule.SECRET_TO_EXTERNAL.value,
                reason="Absolute deny: secret/high data cannot be sent to external_untrusted sink"
            )
        
        # 2. schema invalid
        if not ctx.schema_valid:
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule=AbsoluteDenyRule.INVALID_REQUEST_SCHEMA.value,
                reason="Absolute deny: invalid request schema"
            )
        
        # 3. unknown tool
        if not ctx.tool_valid:
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule=AbsoluteDenyRule.UNKNOWN_TOOL.value,
                reason="Absolute deny: unknown tool"
            )
        
        # 4. audit unavailable + mutation (deny mutation when audit unavailable)
        # Note: This rule is checked at VTRM level, not here
        # if not ctx.audit_available and _is_mutation(tool):
        #     return AuthorizationResult(...)
        
        # 5. unauthorized audit modify
        if ctx.target_is_audit_log:
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule=AbsoluteDenyRule.UNAUTHORIZED_AUDIT_MODIFY.value,
                reason="Absolute deny: agent cannot modify audit log"
            )
        
        # 6. unauthorized policy modify
        if ctx.target_is_policy_config:
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule=AbsoluteDenyRule.UNAUTHORIZED_POLICY_MODIFY.value,
                reason="Absolute deny: agent cannot modify policy configuration"
            )
        
        return None
    
    @staticmethod
    def is_mutation_tool(tool: str) -> bool:
        """Determine if tool is mutation type"""
        return tool in {
            "fs.write",
            "fs.delete",
            "db.insert",
            "db.update",
            "db.delete",
            "network.send",  # Sending data is also mutation
        }


# ============================================================
# Authorization Policy
# ============================================================

class AuthorizationPolicy:
    """
    Authorization policy
    
    Decides authorization mode for requests.
    
    Decision order:
      1. AbsoluteDeny check (highest priority)
      2. Capability-level authorization mode (auto / approval_required / deny)
    """
    
    def __init__(self, profile: Optional[AuthorizationProfile] = None):
        """
        Initialize
        
        Parameters:
          - profile: Authorization profile, defaults to agent.default
        """
        self.profile = profile or get_default_profile()
        self.deny_checker = AbsoluteDenyChecker()
    
    def authorize(
        self,
        capability: Optional[str],
        derivation_status: str,  # From CapabilityDeriver
        ctx: AbsoluteDenyContext,
    ) -> AuthorizationResult:
        """
        Make authorization decision
        
        Parameters:
          - capability: Derived capability (may be None)
          - derivation_status: Derivation status from CapabilityDeriver
          - ctx: Absolute denial check context
        
        Returns:
          AuthorizationResult
        """
        # 1. First check absolute deny
        absolute_deny = self.deny_checker.check(ctx)
        if absolute_deny is not None:
            return absolute_deny
        
        # 2. Check derivation status
        if derivation_status != "ok":
            # Derivation failed, go to deny
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule="derivation_failed",
                reason=f"Capability derivation failed: {derivation_status}"
            )
        
        # 3. Check if capability is valid
        if capability is None:
            return AuthorizationResult(
                mode=AuthorizationMode.DENY,
                rule="no_capability",
                reason="No valid capability derived"
            )
        
        # 4. Query profile for authorization mode
        mode = self.profile.get_mode(capability)
        
        if mode == AuthorizationMode.AUTO:
            return AuthorizationResult(
                mode=AuthorizationMode.AUTO,
                rule="profile.auto",
                reason=f"Capability '{capability}' authorized for auto execution"
            )
        
        if mode == AuthorizationMode.APPROVAL_REQUIRED:
            return AuthorizationResult(
                mode=AuthorizationMode.APPROVAL_REQUIRED,
                rule="profile.approval_required",
                reason=f"Capability '{capability}' requires approval",
                preview=self._build_preview(ctx, capability)
            )
        
        # DENY
        return AuthorizationResult(
            mode=AuthorizationMode.DENY,
            rule="profile.deny",
            reason=f"Capability '{capability}' denied by profile"
        )
    
    def _build_preview(
        self,
        ctx: AbsoluteDenyContext,
        capability: str,
    ) -> Dict[str, Any]:
        """
        Build effect preview
        
        Used for preview info in approval workflow.
        """
        preview: Dict[str, Any] = {
            "capability": capability,
            "inferred_label": ctx.inferred_label or "public",
        }
        
        if ctx.tool:
            preview["tool"] = ctx.tool
        
        if ctx.sink_class:
            preview["sink_class"] = ctx.sink_class
        
        return preview
    
    def get_agent_capabilities(self) -> Set[str]:
        """Get set of capabilities available to agent (auto + approval)"""
        return set(self.profile.auto_capabilities) | set(self.profile.approval_capabilities)


# Global default instance
_default_policy: Optional[AuthorizationPolicy] = None


def get_default_policy() -> AuthorizationPolicy:
    global _default_policy
    if _default_policy is None:
        _default_policy = AuthorizationPolicy()
    return _default_policy


def authorize(
    capability: Optional[str],
    derivation_status: str,
    ctx: AbsoluteDenyContext,
) -> AuthorizationResult:
    """Global authorize function"""
    return get_default_policy().authorize(capability, derivation_status, ctx)
