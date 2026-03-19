"""General-purpose SQL tools for database exploration and modification.

These are last-resort tools — the agent should always prefer native tools
(list_all_topics, show_topics, get_entries, etc.) for standard operations.
Each tool creates its own DB session via a closure over ``session_factory``,
matching the pattern in ``tools.py`` and ``review_tools.py``.
"""

from __future__ import annotations

import re

from langchain.tools import tool
from langgraph.types import interrupt
from sqlalchemy import text

from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.logs import get_logger

_logger = get_logger("agent.sql_tools")

_READ_KEYWORDS = frozenset({"SELECT", "PRAGMA", "EXPLAIN", "WITH"})
_WRITE_KEYWORDS = frozenset({"INSERT", "UPDATE", "DELETE"})


def _first_keyword(sql: str) -> str:
    """Extract the first SQL keyword (uppercased) from a statement."""
    stripped = sql.strip()
    # Skip leading comments
    while stripped.startswith("--") or stripped.startswith("/*"):
        if stripped.startswith("--"):
            newline = stripped.find("\n")
            stripped = stripped[newline + 1:].strip() if newline != -1 else ""
        elif stripped.startswith("/*"):
            end = stripped.find("*/")
            stripped = stripped[end + 2:].strip() if end != -1 else ""
    match = re.match(r"[A-Za-z]+", stripped)
    return match.group(0).upper() if match else ""


def _preview_delete(sql: str) -> str | None:
    """Rewrite a DELETE statement to a SELECT for preview."""
    pattern = re.compile(r"DELETE\s+FROM\b", re.IGNORECASE)
    match = pattern.match(sql.strip())
    if not match:
        return None
    rewritten = pattern.sub("SELECT * FROM", sql.strip(), count=1)
    rewritten = rewritten.rstrip("; \t\n")
    # Append LIMIT if not already present
    if not re.search(r"\bLIMIT\b", rewritten, re.IGNORECASE):
        rewritten += " LIMIT 50"
    return rewritten


def _preview_update(sql: str) -> str | None:
    """Rewrite an UPDATE statement to a SELECT for preview."""
    # Pattern: UPDATE <table> SET ... [WHERE ...]
    match = re.match(
        r"UPDATE\s+(\S+)\s+SET\s+.+?(WHERE\s+.+)?$",
        sql.strip(),
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    table = match.group(1)
    where = match.group(2) or ""
    rewritten = f"SELECT * FROM {table} {where}".strip().rstrip("; \t\n")
    if not re.search(r"\bLIMIT\b", rewritten, re.IGNORECASE):
        rewritten += " LIMIT 50"
    return rewritten


def _format_rows(columns: list[str], rows: list[list]) -> str:
    """Format rows as a pipe-delimited table."""
    if not columns:
        return "(no columns)"
    lines = [" | ".join(str(c) for c in columns)]
    lines.append("-+-".join("-" * max(len(str(c)), 3) for c in columns))
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)


def build_sql_tools(session_factory) -> dict:
    """Build SQL exploration/modification tools closed over session_factory.

    Returns a dict of tool-name -> tool-function, following the
    ``build_review_tools`` pattern.
    """

    @tool("describe_database", description=(
        "Describe the database schema: list all tables with their columns, "
        "types, primary keys, and foreign keys. "
        "IMPORTANT: Always call this BEFORE run_sql_query or run_sql_modification "
        "if you are unsure of the exact table names, column names, or data types. "
        "Do not guess schema details — use this tool to confirm them first. "
        "This is a last-resort tool — prefer native tools (list_all_topics, "
        "show_topics, get_entries, etc.) for standard operations."
    ))
    @tool_visibility(ToolVisibility.DEFAULT)
    async def describe_database_tool() -> str:
        async with session_factory() as session:
            # Get all user tables
            result = await session.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ))
            tables = [row[0] for row in result.fetchall()]

            if not tables:
                return "No tables found."

            sections: list[str] = []
            for table in tables:
                lines: list[str] = [f"## {table}"]

                # Column info
                cols = await session.execute(text(f"PRAGMA table_info({table})"))
                col_rows = cols.fetchall()
                lines.append("Columns:")
                for col in col_rows:
                    # cid, name, type, notnull, dflt_value, pk
                    cid, name, ctype, notnull, dflt, pk = col
                    parts = [f"  - {name} ({ctype or 'untyped'})"]
                    if pk:
                        parts.append("PK")
                    if notnull:
                        parts.append("NOT NULL")
                    if dflt is not None:
                        parts.append(f"DEFAULT {dflt}")
                    lines.append(", ".join(parts))

                # Foreign keys
                fks = await session.execute(text(f"PRAGMA foreign_key_list({table})"))
                fk_rows = fks.fetchall()
                if fk_rows:
                    lines.append("Foreign keys:")
                    for fk in fk_rows:
                        # id, seq, table, from, to, on_update, on_delete, match
                        lines.append(f"  - {fk[3]} -> {fk[2]}.{fk[4]}")

                sections.append("\n".join(lines))

        return "\n\n".join(sections)

    @tool("run_sql_query", description=(
        "Run a read-only SQL query (SELECT, PRAGMA, EXPLAIN, WITH) and return "
        "the results as a formatted table. Returns up to 200 rows. "
        "IMPORTANT: Always run describe_database first to understand the schema. "
        "This is a last-resort tool — prefer native tools (list_all_topics, "
        "show_topics, get_entries, etc.) for standard operations."
    ))
    @tool_visibility(ToolVisibility.DEFAULT)
    async def run_sql_query_tool(sql: str) -> str:
        keyword = _first_keyword(sql)
        if keyword not in _READ_KEYWORDS:
            return (
                f"Rejected: first keyword '{keyword}' is not allowed. "
                f"Only {', '.join(sorted(_READ_KEYWORDS))} are permitted for read queries. "
                f"Use run_sql_modification for INSERT/UPDATE/DELETE."
            )
        try:
            async with session_factory() as session:
                result = await session.execute(text(sql))
                columns = list(result.keys()) if result.returns_rows else []
                if not columns:
                    return "(query returned no columns)"
                rows = [list(row) for row in result.fetchmany(201)]
                truncated = len(rows) > 200
                if truncated:
                    rows = rows[:200]
                output = _format_rows(columns, rows)
                if truncated:
                    output += "\n... (results truncated at 200 rows)"
                return output
        except Exception as exc:
            return f"SQL error: {exc}"

    @tool("run_sql_modification", description=(
        "Run a SQL modification statement (INSERT, UPDATE, DELETE). "
        "For UPDATE/DELETE, a preview of affected rows is shown before "
        "execution. Requires explicit user approval via a confirmation dialog. "
        "IMPORTANT: Always run describe_database first to understand the schema. "
        "This is a last-resort tool — prefer native tools (create_new_topic, "
        "create_entries, delete_topics, etc.) for standard operations."
    ))
    @tool_visibility(ToolVisibility.DEFAULT)
    async def run_sql_modification_tool(sql: str) -> str:
        keyword = _first_keyword(sql)
        if keyword not in _WRITE_KEYWORDS:
            return (
                f"Rejected: first keyword '{keyword}' is not allowed. "
                f"Only {', '.join(sorted(_WRITE_KEYWORDS))} are permitted for modifications. "
                f"Use run_sql_query for SELECT/PRAGMA/EXPLAIN."
            )

        # Build preview for UPDATE/DELETE
        preview_columns: list[str] = []
        preview_rows: list[list] = []
        row_count: int | None = None

        if keyword in ("UPDATE", "DELETE"):
            rewrite_fn = _preview_delete if keyword == "DELETE" else _preview_update
            preview_sql = rewrite_fn(sql)
            if preview_sql:
                try:
                    async with session_factory() as session:
                        # Count total affected rows
                        count_result = await session.execute(text(preview_sql))
                        all_rows = count_result.fetchall()
                        row_count = len(all_rows)
                        preview_columns = list(count_result.keys()) if count_result.returns_rows else []
                        preview_rows = [list(r) for r in all_rows[:50]]
                except Exception as exc:
                    _logger.warning("Preview query failed: %s", exc)
                    preview_columns = []
                    preview_rows = []
                    row_count = None

        # Interrupt for user confirmation
        interrupt_payload: dict = {
            "type": "sql_confirmation",
            "sql": sql,
            "preview": {
                "columns": preview_columns,
                "rows": preview_rows,
            },
            "row_count": row_count,
        }

        result = interrupt(interrupt_payload)

        if result != "Approve":
            return f"User denied SQL modification: {result}"

        # Execute the modification
        try:
            async with session_factory() as session:
                exec_result = await session.execute(text(sql))
                rowcount = exec_result.rowcount
                await session.commit()
            return f"SQL executed successfully. Rows affected: {rowcount}"
        except Exception as exc:
            return f"SQL error: {exc}"

    return {
        "describe_database": describe_database_tool,
        "run_sql_query": run_sql_query_tool,
        "run_sql_modification": run_sql_modification_tool,
    }
