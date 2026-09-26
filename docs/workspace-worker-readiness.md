# Handoff and scheduled-brief worker readiness

The API's existing `/ready` probe now requires progress from each enabled
in-process workspace worker, in addition to the existing configuration and
database/schema checks. `/health` remains a separate liveness probe.

A handoff pass must finish at least once before readiness succeeds. An empty
queue counts as a successful pass. The worker stays ready during a normal model
request, but becomes unready after 90 seconds without a successful pass. This
allows the existing 30-second transport and 90-second durable work lease.
Scheduled briefs use a 300-second interval because each existing page can visit
20 bots and their local sources. Three consecutive unexpected pass failures make
either worker unready sooner. A subsequent successful pass restores readiness.

These are process-local monotonic progress checks, following the existing Celery
readiness convention. No timer can refresh them. Exit, cancellation and shutdown
make the corresponding state unready, and a late result cannot revive it. A new
application lifetime starts with fresh state. A disabled worker is not required;
turning a worker on without starting it leaves readiness false.

Progress means that the existing worker completed its queue pass. It does not
claim that every individual task succeeded or that a model/provider is available.
Expected per-item authority and scheduling skips retain their existing behavior.
Task failures, leases, permissions, retries and durable results remain owned by
their current application workflows. This change does not replay work, kill a
thread, create another scheduler or restart the application.

The HTTP response keeps its existing generic status. No worker name, private
brief, source, identity, credential or exception is included. Existing deployment
readiness probes use the updated route automatically when this image is selected.
Real service and rollout acceptance remain separate from local verification.
