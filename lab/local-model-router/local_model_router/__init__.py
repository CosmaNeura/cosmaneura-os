"""Lab-only local-model job router. Never imported by the product runtime."""

from .config import RouterConfig, assert_fable_locked, load_config
from .models import GuardResult, Job, RouteDecision
from .router import route_job
from .router_types import LOG_TASK_TYPES, is_coding_task

__all__ = [
    "GuardResult",
    "Job",
    "LOG_TASK_TYPES",
    "RouteDecision",
    "RouterConfig",
    "assert_fable_locked",
    "is_coding_task",
    "load_config",
    "route_job",
]

__version__ = "0.1.1"
