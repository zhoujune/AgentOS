#!/usr/bin/env python3
"""
path_classifier.py — File Path Classifier

Responsibilities:
  - Classify file paths into FileClass (object class)
  - Provide clear path type determination for policy engine
  - Support canonicalize (normalize) to prevent path traversal

Design Principles:
  - Deterministic: Same path always returns the same FileClass
  - Complete: All paths must be classified (or denied)
  - Simple: Classification rules are simple for formal verification
  - Secure: Must canonicalize before classifying to prevent .. / symlink attacks

FileClass Definitions (aligned with new version design):
  - PROTECTED: /protected/**             Integrity protection, not writable by default
  - WORKSPACE_WRITABLE: /workspace/**     Read-write
  - READONLY: /var/**                     Read-only
  - SECRET_SOURCE: /secrets/**            Reading results automatically labeled secret/high
  - AUDIT_LOG: /var/log/sandbox/**        Monitor-exclusive write
  - UNKNOWN: others                       Default deny
"""

import os
import re
from enum import Enum
from pathlib import Path
from typing import Optional


class FileClass(Enum):
    """File object class enum"""
    PROTECTED = "protected"
    WORKSPACE_WRITABLE = "workspace_writable"
    READONLY = "readonly"
    SECRET_SOURCE = "secret_source"
    AUDIT_LOG = "audit_log"
    UNKNOWN = "unknown"


class PathClassifier:
    """
    Path classifier
    
    Usage:
        classifier = PathClassifier()
        file_class = classifier.classify("/workspace/file.txt")
    """
    
    def __init__(self):
        """Initialize"""
        # Path prefix rules (by priority)
        self._rules = [
            (FileClass.PROTECTED, re.compile(r"^/protected(/|$)")),
            (FileClass.SECRET_SOURCE, re.compile(r"^/secrets(/|$)")),
            (FileClass.WORKSPACE_WRITABLE, re.compile(r"^/workspace(/|$)")),
            (FileClass.READONLY, re.compile(r"^/var(/|$)")),
            (FileClass.AUDIT_LOG, re.compile(r"^/var/log/sandbox(/|$)")),
        ]
    
    def canonicalize(self, path: str) -> str:
        """
        Normalize path (prevent path traversal attacks)
        
        Steps:
        1. Ensure absolute path
        2. Expand ~ and environment variables
        3. resolve to parse .. and symlink (if path exists)
        4. Return normalized absolute path
        
        Note:
          - For non-existent paths, only do basic normalization (no resolve symlink)
          - For existing paths, do full resolve
        """
        if not path.startswith("/"):
            path = "/" + path
        
        p = Path(path)
        
        if p.exists():
            # Path exists, full resolve
            try:
                resolved = p.resolve(strict=True)
                return str(resolved)
            except (OSError, RuntimeError):
                # Circular symlink or doesn't exist, fallback
                return str(p.absolute())
        else:
            # Path doesn't exist, basic normalization
            parts = []
            for part in path.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part == ".":
                    continue
                elif part == "":
                    continue
                else:
                    parts.append(part)
            return "/" + "/".join(parts)
    
    def classify(self, path: str) -> FileClass:
        """
        Classify path into FileClass
        
        Classification rules (by priority):
        1. /protected/**     → PROTECTED
        2. /secrets/**       → SECRET_SOURCE
        3. /workspace/**     → WORKSPACE_WRITABLE
        4. /var/**           → READONLY
        5. /var/log/sandbox/** → AUDIT_LOG
        6. Others            → UNKNOWN
        
        Note: Must canonicalize before classifying
        
        Parameters:
          - path: Original path
        
        Returns:
          FileClass enum value
        """
        # Normalize path
        normalized = self.canonicalize(path)
        
        # Match by priority
        for file_class, pattern in self._rules:
            if pattern.match(normalized):
                return file_class
        
        # No rule matched
        return FileClass.UNKNOWN
    
    def is_writable(self, file_class: FileClass) -> bool:
        """
        Check if an object class is writable
        
        Rules:
          - PROTECTED → False (integrity protection)
          - SECRET_SOURCE → False (read-only)
          - AUDIT_LOG → False (only monitor writable)
          - WORKSPACE_WRITABLE → True
          - READONLY → False
          - UNKNOWN → False (default deny)
        """
        return file_class == FileClass.WORKSPACE_WRITABLE
    
    def is_readable(self, file_class: FileClass) -> bool:
        """
        Check if an object class is readable
        
        Rules:
          - PROTECTED → True (read-only)
          - WORKSPACE_WRITABLE → True
          - READONLY → True
          - SECRET_SOURCE → True (needs label check)
          - AUDIT_LOG → False (regular agent cannot read)
          - UNKNOWN → False
        """
        readable_classes = {
            FileClass.PROTECTED,
            FileClass.WORKSPACE_WRITABLE,
            FileClass.READONLY,
            FileClass.SECRET_SOURCE,
        }
        return file_class in readable_classes
    
    def is_secret_source(self, file_class: FileClass) -> bool:
        """Check if it's a secret_source class object"""
        return file_class == FileClass.SECRET_SOURCE
    
    def get_semantics(self, file_class: FileClass) -> str:
        """
        Get semantic description of object class
        
        Used for logs and error messages
        """
        semantics = {
            FileClass.PROTECTED: "protected data (read-only, integrity protection)",
            FileClass.WORKSPACE_WRITABLE: "agent workspace (read-write)",
            FileClass.READONLY: "system read-only area",
            FileClass.SECRET_SOURCE: "secret data source (reading yields secret/high label)",
            FileClass.AUDIT_LOG: "audit log (monitor-only write)",
            FileClass.UNKNOWN: "unknown path (default deny)",
        }
        return semantics.get(file_class, "unknown semantics")


# Global default instance
_default_classifier: Optional[PathClassifier] = None


def classify_path(path: str) -> FileClass:
    """
    Global classify_path function
    
    Uses global default classifier
    """
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = PathClassifier()
    return _default_classifier.classify(path)


def canonicalize_path(path: str) -> str:
    """
    Global canonicalize_path function
    
    Uses global default classifier
    """
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = PathClassifier()
    return _default_classifier.canonicalize(path)


def is_writable(file_class: FileClass) -> bool:
    """Global is_writable function"""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = PathClassifier()
    return _default_classifier.is_writable(file_class)


def is_secret_source(file_class: FileClass) -> bool:
    """Global is_secret_source function"""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = PathClassifier()
    return _default_classifier.is_secret_source(file_class)
