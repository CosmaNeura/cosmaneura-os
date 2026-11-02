"""Install the log scrubber on every handler the process uses.

Uvicorn configures its loggers before the application imports. Celery replaces
worker handlers while the worker starts. Patching handler installation, and
arming handlers that already exist, covers both orders.
"""

from __future__ import annotations

import logging

from cosmas_os.log_scrub import LogScrubFilter, ScrubbingFormatter

_installed = False
_worker_hooks = False
_original_add_handler = logging.Logger.addHandler
_original_set_formatter = logging.Handler.setFormatter


def is_installed() -> bool:
    return _installed


def _attach_filter(handler: logging.Handler) -> None:
    if not any(isinstance(existing, LogScrubFilter) for existing in handler.filters):
        handler.addFilter(LogScrubFilter())


def _set_formatter(self: logging.Handler, fmt: logging.Formatter | None) -> None:
    if fmt is not None and not isinstance(fmt, ScrubbingFormatter):
        fmt = ScrubbingFormatter(fmt)
    _original_set_formatter(self, fmt)


def _add_handler(self: logging.Logger, handler: logging.Handler) -> None:
    _original_add_handler(self, handler)
    _arm_handler(handler)


def _arm_handler(handler: logging.Handler) -> None:
    _attach_filter(handler)
    current = handler.formatter
    if isinstance(current, ScrubbingFormatter):
        return
    if current is None:
        current = logging.Formatter("%(levelname)s %(name)s %(message)s")
    handler.setFormatter(current)


def _arm_existing() -> None:
    loggers: list[logging.Logger] = [logging.getLogger()]
    for candidate in logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, logging.Logger):
            loggers.append(candidate)
    for logger in loggers:
        for handler in logger.handlers:
            _arm_handler(handler)
    if logging.lastResort is not None:
        _arm_handler(logging.lastResort)


def install() -> None:
    """Scrub records on current and future handlers. Safe to call more than once."""
    global _installed
    if not _installed:
        logging.Logger.addHandler = _add_handler  # type: ignore[method-assign]
        logging.Handler.setFormatter = _set_formatter  # type: ignore[method-assign]
        _installed = True
    _arm_existing()


def _rearm(**_kwargs: object) -> None:
    install()


def install_worker() -> None:
    """Install the scrubber and re-arm it after Celery configures logging."""
    global _worker_hooks
    install()
    if _worker_hooks:
        return
    from celery.signals import after_setup_logger, after_setup_task_logger

    after_setup_logger.connect(_rearm, weak=False)
    after_setup_task_logger.connect(_rearm, weak=False)
    _worker_hooks = True
