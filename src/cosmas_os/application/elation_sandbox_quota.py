"""Conservative rolling-day quota shared by every process using one API client."""

import asyncio
import time
from contextlib import nullcontext
from datetime import UTC, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from cosmas_os.adapters.elation_read import ElationReadError
from cosmas_os.application.capture_deadline import CaptureBudget, capture_budget, current_budget
from cosmas_os.elation_sandbox_models import ElationSandboxQuota, ElationSandboxQuotaMinute


class ElationSandboxQuotaBudget:
    def __init__(self, sessions):
        self._sessions = sessions

    def reserve(self, credential_key, *, deadline=None):
        """Return delay or reserve one call; no lock crosses a sleep/network call."""
        parent = current_budget()
        remaining = min(2.0, parent.check() if parent else 2.0,
            deadline - time.monotonic() if deadline is not None else 2.0)
        if remaining <= 0:
            raise ElationReadError("rate_limited")
        budget = CaptureBudget(remaining)
        # This owns a new private Session only. The existing PostgreSQL hook
        # enforces decreasing statement/lock timeouts for this <=2s reservation;
        # the request's longer timeout cannot overwrite them. Parent cancellation
        # remains authoritative, and no child lock survives return or sleep.
        with parent.on_cancel(budget.cancel) if parent else nullcontext():
            with capture_budget(budget):
                return self._reserve(credential_key)

    def _reserve(self, credential_key):
        with self._sessions() as session:
            session.execute(insert(ElationSandboxQuota).values(credential_key=credential_key)
                .on_conflict_do_nothing(index_elements=["credential_key"]))
            quota = session.scalar(select(ElationSandboxQuota).where(
                ElationSandboxQuota.credential_key == credential_key).with_for_update())
            now = session.scalar(select(func.clock_timestamp())).astimezone(UTC)
            if quota.last_permitted_at is not None:
                wait = (quota.last_permitted_at + timedelta(seconds=0.51) - now).total_seconds()
                if wait > 5:
                    raise ElationReadError("rate_limited")
                if wait > 0:
                    session.rollback()
                    return wait
            minute = now.replace(second=0, microsecond=0)
            cutoff = minute - timedelta(days=1)
            # Include the entire oldest minute: conservative at the rolling edge.
            total = session.scalar(select(func.coalesce(func.sum(ElationSandboxQuotaMinute.requests), 0))
                .where(ElationSandboxQuotaMinute.credential_key == credential_key,
                    ElationSandboxQuotaMinute.minute >= cutoff))
            if total >= 149_999:
                raise ElationReadError("rate_limited")
            session.execute(delete(ElationSandboxQuotaMinute).where(
                ElationSandboxQuotaMinute.credential_key == credential_key,
                ElationSandboxQuotaMinute.minute < cutoff))
            session.execute(insert(ElationSandboxQuotaMinute).values(
                credential_key=credential_key, minute=minute, requests=1).on_conflict_do_update(
                    index_elements=["credential_key", "minute"],
                    set_={"requests": ElationSandboxQuotaMinute.requests + 1}))
            quota.last_permitted_at = now
            session.commit()
            return 0.0

    async def permit(self, credential_key):
        try:
            deadline = time.monotonic() + 5
            async with asyncio.timeout(5):
                while True:
                    wait = self.reserve(credential_key, deadline=deadline)
                    if wait == 0:
                        return True
                    await asyncio.sleep(wait)
        except ElationReadError:
            raise
        except Exception:
            raise ElationReadError("rate_limited") from None
