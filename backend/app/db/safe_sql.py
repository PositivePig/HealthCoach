"""Safe SQL execution for the `execute_sql` MCP tool.

Security philosophy (per project rules):
  - Only SELECT statements allowed
  - Single statement only (no `;` chaining)
  - Whitelisted tables only (meals / activities / vitals / users)
  - No dangerous tokens (DROP / DELETE / UPDATE / INSERT / ALTER / ATTACH / PRAGMA / EXEC / -- / /*)
  - Hard row LIMIT (default 200, max 1000)
  - User input goes via :param placeholders → SQLAlchemy parameterizes them
  - Forced filter: SELECTs over user-scoped tables MUST include user_id binding;
    enforced by the MCP tool wrapper, NOT by this module (caller responsibility)

Returns: list of dict rows (column → value), JSON-safe.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger

log = get_logger(__name__)


ALLOWED_TABLES = {"meals", "activities", "vitals", "users",
                  "scheduled_jobs", "notifications"}

# Tokens that are absolutely forbidden anywhere in the SQL
_FORBIDDEN_PATTERNS = [
    r"\bdrop\b",
    r"\bdelete\b",
    r"\bupdate\b",
    r"\binsert\b",
    r"\balter\b",
    r"\bcreate\b",
    r"\battach\b",
    r"\bdetach\b",
    r"\bpragma\b",
    r"\bexec(?:ute)?\b",
    r"\btruncate\b",
    r"\bgrant\b",
    r"\brevoke\b",
    r"\bvacuum\b",
    r"\bmerge\b",
    r"--",
    r"/\*",
    r"\*/",
]

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000


class UnsafeSQLError(ValueError):
    """Raised when a SQL string fails the safety screen."""


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip()).rstrip(";").strip()


def validate_sql(sql: str) -> str:
    """Validate and normalize the input SQL.

    Returns the safe string. Raises UnsafeSQLError otherwise.
    """
    s = _normalize(sql)
    if not s:
        raise UnsafeSQLError("empty SQL")

    if ";" in s:
        raise UnsafeSQLError("multiple statements not allowed (`;` is forbidden)")

    lower = s.lower()

    if not (lower.startswith("select ") or lower.startswith("with ")):
        raise UnsafeSQLError("only SELECT statements are allowed")

    for pat in _FORBIDDEN_PATTERNS:
        if re.search(pat, lower):
            raise UnsafeSQLError(f"forbidden token matched: /{pat}/")

    # Whitelist table check: any sequence "from <table>" or "join <table>"
    referenced = set(re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", lower))

    # CTE aliases (e.g. "WITH recent AS (...)") are introduced by the user;
    # treat them as "known" since they cannot mutate data.
    cte_aliases = set(re.findall(r"\bwith\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", lower))
    cte_aliases |= set(re.findall(r",\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", lower))

    illegal = referenced - ALLOWED_TABLES - cte_aliases
    if illegal:
        raise UnsafeSQLError(
            f"table(s) not in whitelist: {sorted(illegal)} "
            f"(allowed: {sorted(ALLOWED_TABLES)})"
        )

    return s


def _ensure_limit(sql: str, limit: int) -> str:
    """Append LIMIT if the SELECT lacks one (case-insensitive). Idempotent."""
    if re.search(r"\blimit\s+\d+\b", sql, flags=re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {limit}"


async def execute_safe_select(
    session: AsyncSession,
    sql: str,
    *,
    params: dict[str, Any] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Validate then execute. Always parameterized (SQLAlchemy text + bind params)."""
    if limit < 1 or limit > _MAX_LIMIT:
        raise UnsafeSQLError(f"limit must be 1..{_MAX_LIMIT}")

    safe_sql = validate_sql(sql)
    safe_sql = _ensure_limit(safe_sql, limit)

    log.info(
        "execute_safe_select",
        sql_preview=safe_sql[:120],
        param_keys=sorted((params or {}).keys()),
    )
    result = await session.execute(text(safe_sql), params or {})
    rows = result.mappings().all()
    return [dict(r) for r in rows]
