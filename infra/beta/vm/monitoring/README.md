# Staging application and backup alerts

The minute timer emits only two fixed health states and an observation time.
It checks the six expected containers, fresh successful readiness checks, the
actual local TLS listener and certificate, and the backup receiver/timers plus
the latest successful remote backup status job. Command output, health-check
bodies, application logs, credentials and records are never forwarded.

The probe runs with a read-only host filesystem and only loopback IP access.
It needs root solely for the fixed Docker inspection calls; it never executes
inside a container or changes a service. Its timer deliberately remains active
when staging stops, so an app stop cannot also silence the observer unnoticed.

Install the reviewed `probe.py` under `/opt/cosmabot/monitoring/`, root-owned
mode 0644, and the matching service/timer under `/etc/systemd/system/`.
Verify those exact hashes and run the service before enabling the timer.
The host must have rsyslog enabled; the official Azure Monitor Agent supplies
the supported forwarding integration. Docker application logs remain on the
existing local driver, separate from the selected `local6` facility.

Enable `runtime_monitoring_enabled` in the existing isolated foundation state.
The official Microsoft Linux agent uses the VM's existing user-assigned identity;
no new identity, role assignment, credential, inbound rule, or Core access is
introduced. The collection rule selects only `local6` informational events and
retains only the exact generated health-message format and process name.
It uses the existing East US 2 log workspace and its existing retention/quota.

Verify actual ingestion and both alert queries, including empty, stale, failed
and future-dated evidence. Then enable `runtime_alerts_enabled`. The two
stateful rules use the existing action group and fire when their health state
has had no successful report for five minutes, including a stopped probe,
agent or ingestion path. A brief overlap with a running backup check does not
immediately page the owner. The existing VM availability alert remains useful
if the entire host stops. Log alerts still depend on Azure Monitor availability
and can be delayed by ingestion; this does not prove clinical workflow success.

Recovery: disable the two runtime alerts before intentionally stopping the
probe/agent for maintenance. Keep the original infrastructure alerts intact.
Stop and disable only `cosmabot-health.timer` to retire the probe; retain its
read-only source and deployment evidence. No application or backup data needs
to be removed. A failed telemetry setup must not restart or modify the app.

References: [Azure Monitor Agent requirements](https://learn.microsoft.com/azure/azure-monitor/agents/azure-monitor-agent-requirements)
and [Syslog collection](https://learn.microsoft.com/azure/azure-monitor/vm/data-collection-syslog).
