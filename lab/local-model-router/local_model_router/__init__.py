"""Lab-only local-model job router. Never imported by the product runtime."""

from .config import RouterConfig, load_config
from .models import GuardResult, Job, RouteDecision
from .router import route_job

__all__ = [
    "GuardResult",
    "Job",
    "RouteDecision",
    "RouterConfig",
    "load_config",
    "route_job",
]

__version__ = "0.1.0"
