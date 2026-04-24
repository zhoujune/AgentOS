#!/usr/bin/env python3
"""
approval_store.py — Approval Store (Minimal Implementation)

Responsibilities:
  - Store pending approval requests
  - Store approved requests
  - Store used tokens
  - Support expiration checking
  - Support scope-bound token verification

Storage Structure (file-based):
  /var/lib/agentos/approvals/
    pending/      # Pending ApprovalRequest JSON
    approved/     # Approved but unused ApprovalRequest
    used/         # Used one-time tokens

ApprovalRequest Fields:
  - approval_id: Unique identifier
  - task_id: Task ID
  - request_id: Request ID
  - subject: Execution subject
  - tool: Tool type
  - normalized_args: Normalized arguments
  - object_class / sink_class / db_class
  - required_capability
  - inferred_label
  - risk_level: low / medium / high / critical
  - preview: Normalized effect preview
  - created_at: ISO timestamp
  - expires_at: ISO timestamp
  - status: pending / approved / denied / expired / used

Design Principles:
  - Minimal implementation, file-based for easy auditing
  - Support expiration time
  - Support scope-bound tokens
  - Support single-use tokens
  - Every status change generates an audit event
"""

import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger("vtrm.approval")


class ApprovalStatus(Enum):
    """Approval status"""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    USED = "used"


class RiskLevel(Enum):
    """Risk level"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EffectPreview:
    """
    Normalized effect preview
    
    Used for display to approvers, not the model's original words.
    """
    effect_type: str = ""           # fs_write, network_send, db_insert, db_update
    target: str = ""                # Target path / URL / table
    target_class: str = ""          # object_class / sink_class / db_class
    old_new_preview: str = ""       # old/new preview (if achievable)
    payload_summary: str = ""       # Payload summary / hash
    inferred_label: str = "public"  # Data label
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalRequest:
    """
    Approval request
    
    Generated when request is determined as approval_required.
    """
    approval_id: str
    task_id: str
    request_id: str
    subject: str
    tool: str
    normalized_args: Dict[str, Any]
    # Classification info
    object_class: Optional[str] = None
    sink_class: Optional[str] = None
    db_class: Optional[str] = None
    # Derivation info
    required_capability: Optional[str] = None
    inferred_label: str = "public"
    # Risk and preview
    risk_level: str = RiskLevel.MEDIUM.value
    preview: Optional[EffectPreview] = None
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = field(default_factory=lambda: (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat())
    # Status
    status: str = ApprovalStatus.PENDING.value
    # Approval info
    approver: Optional[str] = None
    approved_at: Optional[str] = None
    denial_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.preview:
            d["preview"] = self.preview.to_dict()
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRequest":
        if "preview" in data and data["preview"]:
            data["preview"] = EffectPreview(**data["preview"])
        return cls(**data)
    
    def is_expired(self) -> bool:
        """Check if expired"""
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > expires
        except (ValueError, TypeError):
            return True  # Parse failure means expired
    
    def is_pending(self) -> bool:
        return self.status == ApprovalStatus.PENDING.value
    
    def is_approved(self) -> bool:
        return self.status == ApprovalStatus.APPROVED.value
    
    def is_used(self) -> bool:
        return self.status == ApprovalStatus.USED.value


@dataclass
class ApprovalToken:
    """
    One-time approval token
    
    Issued by system after approval.
    """
    token: str
    approval_id: str
    task_id: str
    request_id: str
    tool: str
    # scope: Operation scope bound to token
    scope_target: str           # Path / URL / table
    scope_class: str            # object_class / sink_class / db_class
    inferred_label: str
    # Timestamps
    issued_at: str
    expires_at: str
    # Status
    used: bool = False
    used_at: Optional[str] = None
    
    @classmethod
    def generate(cls, approval: ApprovalRequest, scope_target: str, scope_class: str) -> "ApprovalToken":
        """Generate new token"""
        issued = datetime.now(timezone.utc)
        expires = issued + timedelta(hours=24)
        
        return cls(
            token=secrets.token_urlsafe(32),
            approval_id=approval.approval_id,
            task_id=approval.task_id,
            request_id=approval.request_id,
            tool=approval.tool,
            scope_target=scope_target,
            scope_class=scope_class,
            inferred_label=approval.inferred_label,
            issued_at=issued.isoformat(),
            expires_at=expires.isoformat(),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalToken":
        return cls(**data)
    
    def is_expired(self) -> bool:
        """Check if expired"""
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > expires
        except (ValueError, TypeError):
            return True
    
    def is_valid_for(self, approval_id: str, task_id: str, request_id: str,
                    tool: str, scope_target: str) -> bool:
        """
        Verify if token is valid for current request
        
        Verification items:
          - Token not expired
          - Token not used
          - approval_id matches
          - task_id matches
          - request_id matches
          - tool matches
          - scope_target exact match
        """
        if self.is_expired():
            return False
        if self.used:
            return False
        if self.approval_id != approval_id:
            return False
        if self.task_id != task_id:
            return False
        if self.request_id != request_id:
            return False
        if self.tool != tool:
            return False
        if self.scope_target != scope_target:
            return False
        return True


class ApprovalStore:
    """
    Approval store (file-based implementation)
    
    Directory structure:
      {base_dir}/
        pending/       # Pending requests
        approved/      # Approved requests
        used/          # Used tokens
        tokens/        # Valid tokens
    
    File naming:
      pending/{approval_id}.json
      approved/{approval_id}.json
      used/{approval_id}.json
      tokens/{token_hash}.json  # Token hash as filename (secure)
    """
    
    def __init__(self, base_dir: Optional[str] = None):
        """
        Initialize
        
        Parameters:
          - base_dir: Approval store root directory, default /var/lib/agentos/approvals
        """
        self.base_dir = Path(base_dir or os.environ.get(
            "VTRM_APPROVAL_DIR",
            "/var/lib/agentos/approvals"
        ))
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """Ensure directories exist"""
        for subdir in ["pending", "approved", "used", "tokens"]:
            (self.base_dir / subdir).mkdir(parents=True, exist_ok=True)
    
    def _token_hash(self, token: str) -> str:
        """Hash token for use as filename"""
        return hashlib.sha256(token.encode()).hexdigest()[:32]
    
    # ========================
    # ApprovalRequest Management
    # ========================
    
    def create_approval(self, approval: ApprovalRequest) -> str:
        """
        Create pending approval request
        
        Parameters:
          - approval: ApprovalRequest object
        
        Returns:
          approval_id
        """
        path = self.base_dir / "pending" / f"{approval.approval_id}.json"
        
        with path.open("w") as f:
            json.dump(approval.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Created pending approval: {approval.approval_id}")
        return approval.approval_id
    
    def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Get approval request"""
        # Check pending first
        path = self.base_dir / "pending" / f"{approval_id}.json"
        if path.exists():
            return self._load_approval(path)
        
        # Then approved
        path = self.base_dir / "approved" / f"{approval_id}.json"
        if path.exists():
            return self._load_approval(path)
        
        # Then used
        path = self.base_dir / "used" / f"{approval_id}.json"
        if path.exists():
            return self._load_approval(path)
        
        return None
    
    def _load_approval(self, path: Path) -> Optional[ApprovalRequest]:
        """Load approval request"""
        try:
            with path.open("r") as f:
                data = json.load(f)
            return ApprovalRequest.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load approval from {path}: {e}")
            return None
    
    def update_approval_status(
        self,
        approval_id: str,
        new_status: ApprovalStatus,
        approver: Optional[str] = None,
        denial_reason: Optional[str] = None,
    ) -> bool:
        """
        Update approval status
        
        Parameters:
          - approval_id: Approval ID
          - new_status: New status
          - approver: Approver (when approved)
          - denial_reason: Denial reason (when denied)
        
        Returns:
          Whether successful
        """
        approval = self.get_approval(approval_id)
        if not approval:
            return False
        
        approval.status = new_status.value
        
        if new_status == ApprovalStatus.APPROVED:
            approval.approver = approver or "system"
            approval.approved_at = datetime.now(timezone.utc).isoformat()
        elif new_status == ApprovalStatus.DENIED:
            approval.denial_reason = denial_reason
        
        # Move to corresponding directory
        old_path = self._find_approval_path(approval_id)
        new_dir = self.base_dir / new_status.value
        
        if old_path and old_path.parent != new_dir:
            new_path = new_dir / old_path.name
            try:
                old_path.unlink()  # Delete old file
                with new_path.open("w") as f:
                    json.dump(approval.to_dict(), f, ensure_ascii=False, indent=2)
                logger.info(f"Approval {approval_id} moved to {new_status.value}")
            except OSError as e:
                logger.error(f"Failed to move approval {approval_id}: {e}")
                return False
        
        return True
    
    def _find_approval_path(self, approval_id: str) -> Optional[Path]:
        """Find approval request path"""
        for subdir in ["pending", "approved", "used"]:
            path = self.base_dir / subdir / f"{approval_id}.json"
            if path.exists():
                return path
        return None
    
    def list_pending(self) -> list[ApprovalRequest]:
        """List all pending approval requests"""
        results = []
        pending_dir = self.base_dir / "pending"
        
        for path in pending_dir.glob("*.json"):
            approval = self._load_approval(path)
            if approval:
                # Filter expired
                if not approval.is_expired():
                    results.append(approval)
                else:
                    # Mark as expired
                    self.update_approval_status(
                        approval.approval_id,
                        ApprovalStatus.EXPIRED
                    )
        
        return results
    
    # ========================
    # Token Management
    # ========================
    
    def save_token(self, token: ApprovalToken) -> str:
        """
        Save token
        
        Parameters:
          - token: ApprovalToken object
        
        Returns:
          Token hash (as file key)
        """
        token_hash = self._token_hash(token.token)
        path = self.base_dir / "tokens" / f"{token_hash}.json"
        
        with path.open("w") as f:
            json.dump(token.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved token for approval: {token.approval_id}")
        return token_hash
    
    def get_token(self, token_str: str) -> Optional[ApprovalToken]:
        """Get token"""
        token_hash = self._token_hash(token_str)
        path = self.base_dir / "tokens" / f"{token_hash}.json"
        
        if not path.exists():
            return None
        
        try:
            with path.open("r") as f:
                data = json.load(f)
            return ApprovalToken.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load token: {e}")
            return None
    
    def mark_token_used(self, token_str: str) -> bool:
        """
        Mark token as used
        
        Parameters:
          - token_str: Token string
        
        Returns:
          Whether successful
        """
        token = self.get_token(token_str)
        if not token:
            return False
        
        if token.used:
            logger.warning(f"Token already used: {token.approval_id}")
            return False
        
        # Update token status
        token.used = True
        token.used_at = datetime.now(timezone.utc).isoformat()
        
        # Save to used directory
        token_hash = self._token_hash(token_str)
        used_path = self.base_dir / "used" / f"{token_hash}.json"
        
        # Delete token from tokens directory
        tokens_path = self.base_dir / "tokens" / f"{token_hash}.json"
        if tokens_path.exists():
            tokens_path.unlink()
        
        # Save to used directory
        with used_path.open("w") as f:
            json.dump(token.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Update approval status
        self.update_approval_status(token.approval_id, ApprovalStatus.USED)
        
        logger.info(f"Token marked as used: {token.approval_id}")
        return True
    
    def verify_token(
        self,
        token_str: str,
        approval_id: str,
        task_id: str,
        request_id: str,
        tool: str,
        scope_target: str,
    ) -> tuple[bool, str]:
        """
        Verify if token is valid
        
        Returns:
          (is_valid, reason)
        """
        token = self.get_token(token_str)
        
        if not token:
            return False, "Token not found"
        
        if token.is_expired():
            return False, "Token expired"
        
        if token.used:
            return False, "Token already used"
        
        if not token.is_valid_for(approval_id, task_id, request_id, tool, scope_target):
            return False, "Token scope mismatch"
        
        return True, "Token valid"
    
    def cleanup_expired(self) -> int:
        """
        Clean up expired approvals and tokens
        
        Returns:
          Number of items cleaned
        """
        count = 0
        
        # Clean expired pending approvals
        for path in (self.base_dir / "pending").glob("*.json"):
            approval = self._load_approval(path)
            if approval and approval.is_expired():
                self.update_approval_status(approval.approval_id, ApprovalStatus.EXPIRED)
                count += 1
        
        # Clean expired tokens
        for path in (self.base_dir / "tokens").glob("*.json"):
            try:
                with path.open("r") as f:
                    data = json.load(f)
                token = ApprovalToken.from_dict(data)
                if token.is_expired():
                    path.unlink()
                    count += 1
            except (json.JSONDecodeError, KeyError, OSError):
                pass
        
        return count


# ========================
# Global Instance
# ========================

_default_store: Optional[ApprovalStore] = None


def get_approval_store(base_dir: Optional[str] = None) -> ApprovalStore:
    """Get global approval store"""
    global _default_store
    if _default_store is None:
        _default_store = ApprovalStore(base_dir)
    return _default_store


def reset_approval_store() -> None:
    """Reset global approval store (for testing)"""
    global _default_store
    _default_store = None
