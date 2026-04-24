#!/usr/bin/env python3
"""
db_classifier.py — Database Object Classifier

Responsibilities:
  - Classify database tables into DBClass
  - Support distinction between secret_table / mutable_table / readonly_table / audit_table
  - Provide clear table type determination for policy engine

Design Principles:
  - Deterministic: Same table name always returns the same DBClass
  - Complete: All tables must be classified (or denied)
  - Simple: Classification rules are simple for formal verification

DBClass Definitions:
  - SECRET_TABLE: secrets / credentials etc. (reading returns secret/high label)
  - MUTABLE_TABLE: Mutable tables (updated by capability)
  - READONLY_TABLE: Read-only tables (agent cannot write)
  - AUDIT_TABLE: Audit tables (only monitor can append)
  - UNKNOWN: Other tables (default deny)
"""

from enum import Enum
from typing import Set, Optional


class DBClass(Enum):
    """Database object type enum"""
    SECRET_TABLE = "secret_table"
    MUTABLE_TABLE = "mutable_table"
    READONLY_TABLE = "readonly_table"
    AUDIT_TABLE = "audit_table"
    UNKNOWN = "unknown"


# Default secret table set
DEFAULT_SECRET_TABLES: Set[str] = {
    "secrets",
    "credentials",
    "api_keys",
    "tokens",
    "private",
    "passwords",
}

# Default audit table set
DEFAULT_AUDIT_TABLES: Set[str] = {
    "audit",
    "audit_log",
    "vtrm_audit",
    "transcript",
}

# Default read-only table set
DEFAULT_READONLY_TABLES: Set[str] = {
    "tasks",
    "metadata",
}


class DBClassifier:
    """
    Database object classifier
    
    Usage:
        classifier = DBClassifier()
        db_class = classifier.classify_table("secrets")
        # db_class.value == "secret_table"
    """
    
    def __init__(
        self,
        secret_tables: Optional[Set[str]] = None,
        audit_tables: Optional[Set[str]] = None,
        readonly_tables: Optional[Set[str]] = None,
    ):
        """
        Initialize
        
        Parameters:
          - secret_tables: Secret table set
          - audit_tables: Audit table set
          - readonly_tables: Read-only table set
        """
        self.secret_tables = secret_tables or DEFAULT_SECRET_TABLES
        self.audit_tables = audit_tables or DEFAULT_AUDIT_TABLES
        self.readonly_tables = readonly_tables or DEFAULT_READONLY_TABLES
    
    def classify_table(self, table: str) -> DBClass:
        """
        Classify table name into DBClass
        
        Classification rules (by priority):
        1. secrets / credentials / api_keys / tokens → SECRET_TABLE
        2. audit / audit_log / transcript → AUDIT_TABLE
        3. tasks / metadata → READONLY_TABLE
        4. Others → MUTABLE_TABLE (if not in any set)
        
        Parameters:
          - table: Table name
        
        Returns:
          DBClass enum value
        """
        table_lower = table.lower()
        
        if table_lower in self.secret_tables:
            return DBClass.SECRET_TABLE
        
        if table_lower in self.audit_tables:
            return DBClass.AUDIT_TABLE
        
        if table_lower in self.readonly_tables:
            return DBClass.READONLY_TABLE
        
        # Default as mutable_table, but may need capability check
        return DBClass.MUTABLE_TABLE
    
    def is_secret_table(self, table: str) -> bool:
        """Check if table is a secret_table"""
        return self.classify_table(table) == DBClass.SECRET_TABLE
    
    def is_audit_table(self, table: str) -> bool:
        """Check if table is an audit_table"""
        return self.classify_table(table) == DBClass.AUDIT_TABLE
    
    def is_readonly_table(self, table: str) -> bool:
        """Check if table is a readonly_table"""
        return self.classify_table(table) == DBClass.READONLY_TABLE
    
    def can_agent_write(self, table: str) -> bool:
        """
        Check if agent can write to this table
        
        Rules:
          - SECRET_TABLE → False (needs high privilege)
          - AUDIT_TABLE → False (only monitor writable)
          - READONLY_TABLE → False (read-only)
          - MUTABLE_TABLE → True (needs corresponding capability)
          - UNKNOWN → False
        """
        db_class = self.classify_table(table)
        return db_class == DBClass.MUTABLE_TABLE
    
    def get_table_semantics(self, table: str) -> str:
        """
        Get semantic description of table
        
        Used for logs and error messages
        """
        db_class = self.classify_table(table)
        
        semantics = {
            DBClass.SECRET_TABLE: "contains sensitive data, read returns secret/high label",
            DBClass.AUDIT_TABLE: "append-only audit log, agent write denied",
            DBClass.READONLY_TABLE: "read-only table for agent",
            DBClass.MUTABLE_TABLE: "agent writable with capability",
            DBClass.UNKNOWN: "default deny for unknown tables",
        }
        
        return semantics.get(db_class, "unknown semantics")


# Global default instance
_default_classifier: Optional[DBClassifier] = None


def classify_table(table: str) -> DBClass:
    """
    Global classify_table function
    
    Uses global default classifier
    """
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = DBClassifier()
    return _default_classifier.classify_table(table)


def is_secret_table(table: str) -> bool:
    """Global is_secret_table function"""
    return classify_table(table) == DBClass.SECRET_TABLE


def can_agent_write_table(table: str) -> bool:
    """Global can_agent_write_table function"""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = DBClassifier()
    return _default_classifier.can_agent_write(table)
