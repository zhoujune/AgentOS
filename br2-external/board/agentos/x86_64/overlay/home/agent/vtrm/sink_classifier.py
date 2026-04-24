#!/usr/bin/env python3
"""
sink_classifier.py — Network Sink Classifier

Responsibilities:
  - Classify network URLs into SinkClass
  - Support distinction between trusted_internal / external_untrusted
  - Provide clear sink type determination for network policy

Design Principles:
  - Deterministic: Same URL always returns the same SinkClass
  - Complete: All URLs must be classified
  - Simple: Classification rules are simple for formal verification

SinkClass Definitions:
  - TRUSTED_INTERNAL: Trusted internal sink (allows some secret/high data)
  - EXTERNAL_UNTRUSTED: External untrusted sink (prohibits secret/high data)

Note: V1 does not open TRUSTED_INTERNAL yet, reserved for architecture.
"""

from enum import Enum
from typing import Set, Optional
from urllib.parse import urlparse


class SinkClass(Enum):
    """Network Sink type enum"""
    TRUSTED_INTERNAL = "trusted_internal"
    EXTERNAL_UNTRUSTED = "external_untrusted"


# Default trusted internal address whitelist
DEFAULT_TRUSTED_PREFIXES: Set[str] = {
    "https://api.internal.example.com",
    "https://localhost",
    "https://127.0.0.1",
    # Note: V1 does not open any trusted internal yet
}


class SinkClassifier:
    """
    Network Sink Classifier
    
    Usage:
        classifier = SinkClassifier()
        sink_class = classifier.classify("https://api.example.com/data")
        # sink_class.value == "external_untrusted"
    """
    
    def __init__(
        self,
        trusted_prefixes: Optional[Set[str]] = None,
    ):
        """
        Initialize
        
        Parameters:
          - trusted_prefixes: Set of trusted URL prefixes
        """
        self.trusted_prefixes = trusted_prefixes or set()
    
    def classify(self, url: str) -> SinkClass:
        """
        Classify URL into SinkClass
        
        Classification rules:
        1. Check if URL starts with any trusted_prefix
        2. If matches any prefix → TRUSTED_INTERNAL
        3. Otherwise → EXTERNAL_UNTRUSTED
        
        Parameters:
          - url: Target URL
        
        Returns:
          SinkClass enum value
        """
        # URL normalization
        normalized = self._normalize_url(url)
        
        # Check whitelist
        for prefix in self.trusted_prefixes:
            if normalized.startswith(prefix):
                return SinkClass.TRUSTED_INTERNAL
        
        # Default external untrusted
        return SinkClass.EXTERNAL_UNTRUSTED
    
    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL
        
        Steps:
        1. Remove fragment (#...)
        2. Remove sensitive info from query params (optional)
        3. Convert to lowercase
        """
        try:
            parsed = urlparse(url)
            
            # Remove fragment
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            
            # Lowercase
            normalized = normalized.lower()
            
            return normalized
        except Exception:
            # Parse failed, return lowercased original URL
            return url.lower()
    
    def is_trusted(self, url: str) -> bool:
        """Check if URL is a trusted internal address"""
        return self.classify(url) == SinkClass.TRUSTED_INTERNAL
    
    def is_external(self, url: str) -> bool:
        """Check if URL is an external untrusted address"""
        return self.classify(url) == SinkClass.EXTERNAL_UNTRUSTED
    
    def get_trusted_domains(self) -> Set[str]:
        """Get set of trusted domains"""
        domains = set()
        for prefix in self.trusted_prefixes:
            try:
                parsed = urlparse(prefix)
                domains.add(parsed.netloc)
            except Exception:
                pass
        return domains


# Global default instance
_default_classifier: Optional[SinkClassifier] = None


def classify_sink(url: str) -> SinkClass:
    """
    Global classify_sink function
    
    Uses global default classifier
    """
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = SinkClassifier()
    return _default_classifier.classify(url)


def is_external_sink(url: str) -> bool:
    """Global is_external_sink function"""
    return classify_sink(url) == SinkClass.EXTERNAL_UNTRUSTED
