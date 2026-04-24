#!/usr/bin/env python3
"""
label_model.py — Content Label Model

Responsibilities:
  - Define content sensitivity labels
  - Track label propagation through data flows
  - Support secret data tracking and checking
  - Support sink classification checking

Design Principles:
  - Labels are attributes of data flows, not of the operations themselves
  - Labels propagate based on data source
  - Labels use join rules when data is combined

Label Definitions:
  - public: Public data, freely exfiltratable
  - secret/high: Sensitive data, prohibited from exfiltrating to unauthorized sinks

Join Rules:
  join(public, public) = public
  join(public, secret/high) = secret/high
  join(secret/high, public) = secret/high
  join(secret/high, secret/high) = secret/high

Important: We do not perform content semantic analysis, relying instead on disciplined label propagation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from .sink_classifier import SinkClass


class Label(Enum):
    """Content label enum"""
    PUBLIC = "public"
    SECRET_HIGH = "secret/high"

    def __str__(self) -> str:
        return self.value

    @staticmethod
    def from_string(label_str: str) -> "Label":
        """Create Label from string"""
        if label_str == "public":
            return Label.PUBLIC
        if label_str in ("secret/high", "secret_high", "high"):
            return Label.SECRET_HIGH
        raise ValueError(f"Invalid label: {label_str}")

    @staticmethod
    def from_str(label_str: str) -> "Label":
        """Backward-compatible alias used by older VTRM call sites."""
        return Label.from_string(label_str)


@dataclass
class LabeledData:
    """
    Labeled data container
    
    Used for propagating label information in VTRM
    """
    data: Any
    label: Label
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.label is None:
            self.label = Label.PUBLIC


class LabelContext:
    """
    Label propagation context
    
    Tracks data label flow during tool execution
    """
    
    def __init__(self):
        self.source_trace: List[str] = []
        self._current_label: Label = Label.PUBLIC
    
    def set_source(self, source: str):
        """Record data source"""
        self.source_trace.append(source)
    
    def get_label(self) -> Label:
        """Get current label"""
        return self._current_label
    
    def set_label(self, label: Label):
        """Set current label (overwrites if more sensitive)"""
        if label == Label.SECRET_HIGH:
            self._current_label = Label.SECRET_HIGH
    
    def merge_label(self, other_label: Label):
        """
        Merge another label (take highest sensitivity)
        
        Rules:
          join(public, public) = public
          join(public, secret/high) = secret/high
          join(secret/high, public) = secret/high
          join(secret/high, secret/high) = secret/high
        """
        if other_label == Label.SECRET_HIGH:
            self._current_label = Label.SECRET_HIGH
    
    def clear(self):
        """Clear context (for new requests)"""
        self.source_trace.clear()
        self._current_label = Label.PUBLIC


def infer_label_from_path(path: str) -> Label:
    """
    Infer data label from path
    
    Rules:
      - From /protected/ or /secrets/ → secret/high
      - Other paths → public
    
    This is the entry point for label propagation
    """
    import re
    
    # Normalize path
    path = str(path) if path else ""
    
    if re.match(r"^/protected(/|$)", path):
        return Label.SECRET_HIGH
    
    if re.match(r"^/secrets(/|$)", path):
        return Label.SECRET_HIGH
    
    return Label.PUBLIC


def infer_label_from_table(table: str) -> Label:
    """
    Infer data label from table name
    
    Rules:
      - secrets, credentials, api_keys, tokens tables → secret/high
      - Other tables → public
    """
    SECRET_TABLES = {"secrets", "credentials", "api_keys", "tokens", "private", "passwords"}
    
    if table.lower() in SECRET_TABLES:
        return Label.SECRET_HIGH
    
    return Label.PUBLIC


def join_labels(*labels: Label) -> Label:
    """
    Merge multiple labels (take highest sensitivity)
    
    Rules:
      join(public, public) = public
      join(public, secret/high) = secret/high
      join(secret/high, public) = secret/high
      join(secret/high, secret/high) = secret/high
    
    Parameters:
      - labels: Multiple Label objects
    
    Returns:
      Merged Label
    """
    result = Label.PUBLIC
    for label in labels:
        if label == Label.SECRET_HIGH:
            return Label.SECRET_HIGH
    return result


def can_exfiltrate(label: Label, sink_class: SinkClass) -> bool:
    """
    Check if labeled data can be sent to a sink
    
    Rules:
      - If label = public → allowed to any sink
      - If label = secret/high → only to trusted_internal
      - Other labels → deny
    
    Parameters:
      - label: Data label
      - sink_class: SinkClass
    
    Returns:
      True if exfiltration allowed, False if prohibited
    """
    if label == Label.PUBLIC:
        return True
    
    if label == Label.SECRET_HIGH:
        return sink_class == SinkClass.TRUSTED_INTERNAL
    
    return False


def get_higher_label(label1: Label, label2: Label) -> Label:
    """
    Get the higher sensitivity of two labels
    
    Equivalent to join_labels(label1, label2)
    """
    return join_labels(label1, label2)


def infer_label_from_row(row: Dict[str, Any]) -> Label:
    """
    Infer label from database row/patch
    
    Rules:
      - Check if field values are dict containing "_label": "secret/high"
      - Otherwise return public
    
    This is designed for label propagation in db.insert and db.update
    """
    for k, v in row.items():
        if isinstance(v, dict):
            label_val = v.get("_label", "")
            if label_val == "secret/high" or label_val == Label.SECRET_HIGH.value:
                return Label.SECRET_HIGH
    return Label.PUBLIC


def is_valid_label(label_str: str) -> bool:
    """Check if string is a valid label"""
    try:
        Label.from_string(label_str)
        return True
    except ValueError:
        return False
