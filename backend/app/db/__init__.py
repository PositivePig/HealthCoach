"""Database layer.

SQLAlchemy 2.0 async, backed by either SQLite (dev) or Postgres (prod),
controlled by `STORAGE_BACKEND` env var (see ADR/0006).
"""

from .engine import (  # noqa: F401
    AsyncSessionLocal,
    dispose_engine,
    get_engine,
    init_db,
    session_scope,
)
from .models import (  # noqa: F401
    Activity,
    Base,
    Meal,
    Notification,
    ScheduledJob,
    User,
    Vital,
)
