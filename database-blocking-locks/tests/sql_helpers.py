"""Pure SQL-rendering helpers for the database-blocking-locks Real_Mode feature.

This file is the **test-side mirror** of the pure helpers embedded in the SSM
YAML heredoc at ``database-blocking-locks/database-blocking-locks-automation.yaml``
inside the ``InjectBlockingLocks`` step.

The two copies MUST be kept **byte-for-byte identical for the bodies of the
helper functions** (and for the ``DEFAULT_SYNTHETIC_TABLE`` constant value).
The signatures are also kept identical. The only acceptable difference between
the two copies is the leading whitespace on each line, because the YAML
heredoc's content sits inside a deeper indentation level than this standalone
module.

This mirror exists so the pure helpers can be imported and exercised by
``hypothesis`` property tests without requiring ``boto3``, ``psycopg2``,
``mysql.connector``, or ``pyodbc`` to be installed in the test environment.

If you change a helper's body here, update the corresponding helper in the
YAML heredoc in the same commit, and vice versa.
"""

from typing import List, Optional, Tuple


DEFAULT_SYNTHETIC_TABLE = "fis_blocking_locks_target"


def is_real_mode(target_table_name: str) -> bool:
    return target_table_name != DEFAULT_SYNTHETIC_TABLE


def quote_identifier(engine: str, name: str) -> str:
    if engine == "postgres":
        return '"' + name.replace('"', '""') + '"'
    if engine == "mysql":
        return "`" + name.replace("`", "``") + "`"
    if engine == "sqlserver":
        return "[" + name.replace("]", "]]") + "]"
    raise ValueError("unsupported engine: %r" % engine)


def parse_qualified_table_name(engine: str, name: str) -> Tuple[Optional[str], str]:
    if engine == "sqlserver":
        if "." in name:
            schema, table = name.split(".", 1)
            return (schema, table)
        return ("dbo", name)
    return (None, name)


def build_quoted_table_ref(engine: str, schema: Optional[str], table: str) -> str:
    if engine == "sqlserver":
        return (quote_identifier("sqlserver", schema) + "."
                + quote_identifier("sqlserver", table))
    return quote_identifier(engine, table)


def build_pk_where_clause(engine: str, pk_columns: List[str]) -> str:
    marker = "?" if engine == "sqlserver" else "%s"
    quoted = [quote_identifier(engine, c) for c in pk_columns]
    return " AND ".join("%s = %s" % (col, marker) for col in quoted)


def build_lock_query(engine: str, qualified_table_ref: str,
                     pk_columns: List[str]) -> str:
    quoted_cols = ", ".join(quote_identifier(engine, c) for c in pk_columns)
    where_clause = build_pk_where_clause(engine, pk_columns)
    if engine == "sqlserver":
        return ("SELECT " + quoted_cols + " FROM " + qualified_table_ref
                + " WITH (UPDLOCK, HOLDLOCK) WHERE " + where_clause)
    return ("SELECT " + quoted_cols + " FROM " + qualified_table_ref
            + " WHERE " + where_clause + " FOR UPDATE")
