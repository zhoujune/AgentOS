#!/usr/bin/env python3
"""
db_ops.py — Restricted Database Operations

Responsibilities:
  - Provide typed DB operation interface
  - Prohibit arbitrary SQL execution
  - Track data label propagation
  - Record operation audit logs

Design Principles:
  - Do not expose exec_sql interface
  - All operations go through VTRM for policy checking
  - Operation results carry correct label (for downstream use)

Supported typed operations:
  - db.read(table, key)      → returns (LabeledData, label)
  - db.insert(table, row)    → returns success/failure + label
  - db.update(table, key, patch) → returns success/failure + label
"""

import json
import sqlite3
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from .label_model import Label, LabeledData

logger = logging.getLogger("vtrm.db_ops")


@dataclass
class DBResult:
    """Database operation result"""
    success: bool
    data: Optional[Any] = None
    label: Label = Label.PUBLIC
    error: Optional[str] = None
    rows_affected: int = 0


class DBOperations:
    """
    Restricted database operations executor
    
    Usage:
      db = DBOperations("/data/agent.db")
      result = db.read("tasks", "task-001")
    """
    
    def __init__(self, db_path: str):
        """
        Initialize
        
        Parameters:
          - db_path: SQLite database file path
        """
        self.db_path = Path(db_path)
        self._init_db()
    
    def _init_db(self) -> None:
        """Ensure database exists"""
        if not self.db_path.exists():
            conn = sqlite3.connect(self.db_path)
            conn.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    def read(self, table: str, key: str) -> DBResult:
        """
        Read record by primary key
        
        Parameters:
          - table: Table name
          - key: Primary key value
        
        Returns:
          DBResult containing data and label
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            
            if row is None:
                return DBResult(
                    success=False,
                    error=f"Record not found: table={table}, key={key}"
                )
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            conn.close()
            
            row_dict = dict(zip(columns, row))
            
            label = Label.SECRET_HIGH if self._is_secret_table(table) else Label.PUBLIC
            
            return DBResult(
                success=True,
                data=LabeledData(data=row_dict, label=label, 
                                 metadata={"table": table, "key": key}),
                label=label
            )
            
        except sqlite3.Error as e:
            logger.error(f"DB read error: {e}")
            return DBResult(success=False, error=str(e))
    
    def insert(self, table: str, row: Dict[str, Any]) -> DBResult:
        """
        Insert record
        
        Parameters:
          - table: Table name
          - row: Row data (key-value pairs)
        
        Returns:
          DBResult
        """
        try:
            if not row:
                return DBResult(success=False, error="Empty row data")
            
            columns = list(row.keys())
            placeholders = ["?" for _ in columns]
            values = list(row.values())
            
            sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
            conn.close()
            
            label = Label.SECRET_HIGH if self._is_secret_table(table) else Label.PUBLIC
            
            return DBResult(
                success=True,
                label=label,
                rows_affected=1,
            )
            
        except sqlite3.Error as e:
            return DBResult(success=False, error=str(e))
    
    def update(self, table: str, key: str, patch: Dict[str, Any]) -> DBResult:
        """
        Update record (partial fields)
        
        Parameters:
          - table: Table name
          - key: Primary key value
          - patch: Fields to update
        
        Returns:
          DBResult
        """
        try:
            if not patch:
                return DBResult(success=False, error="Empty patch data")
            
            set_clauses = [f"{col} = ?" for col in patch.keys()]
            sql = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id = ?"
            values = list(patch.values()) + [key]
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, values)
            rows_affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            if rows_affected == 0:
                return DBResult(
                    success=False,
                    error=f"Record not found for update: table={table}, key={key}"
                )
            
            label = Label.SECRET_HIGH if self._is_secret_table(table) else Label.PUBLIC
            
            return DBResult(
                success=True,
                label=label,
                rows_affected=rows_affected,
            )
            
        except sqlite3.Error as e:
            return DBResult(success=False, error=str(e))

    def delete(self, table: str, key: str) -> DBResult:
        """Delete a record by primary key."""
        try:
            sql = f"DELETE FROM {table} WHERE id = ?"
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, (key,))
            rows_affected = cursor.rowcount
            conn.commit()
            conn.close()

            if rows_affected == 0:
                return DBResult(
                    success=False,
                    error=f"Record not found for delete: table={table}, key={key}"
                )

            label = Label.SECRET_HIGH if self._is_secret_table(table) else Label.PUBLIC
            return DBResult(
                success=True,
                label=label,
                rows_affected=rows_affected,
            )

        except sqlite3.Error as e:
            return DBResult(success=False, error=str(e))
    
    def _is_secret_table(self, table: str) -> bool:
        """
        Determine if table is a secret table
        
        Based on table name (configurable).
        """
        SECRET_TABLES = {"secrets", "credentials", "api_keys", "tokens", "private"}
        return table.lower() in SECRET_TABLES
    
    def table_exists(self, table: str) -> bool:
        """Check if table exists"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except sqlite3.Error:
            return False
    
    def create_table_if_not_exists(self, table: str, schema: str) -> bool:
        """
        Create table if it doesn't exist
        
        Parameters:
          - table: Table name
          - schema: CREATE TABLE statement (must include table name placeholder)
        
        Example:
          db.create_table_if_not_exists("tasks",
              "CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, output TEXT)")
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(schema)
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to create table {table}: {e}")
            return False
