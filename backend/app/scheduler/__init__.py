"""Scheduler package.

Importing this package side-effect-loads built-in job kinds (jobs module).
"""

from .core import (  # noqa: F401
    SchedulerCore,
    TriggerSpecError,
    build_trigger,
    get_job_kinds,
    get_scheduler,
    is_job_kind_registered,
    register_job_kind,
)
from . import jobs as _builtin_jobs  # noqa: F401  (registers daily_report etc.)
