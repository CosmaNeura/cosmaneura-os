# API and worker image hardening

The API and worker share the pinned Debian Python image. After numeric account
creation and the existing guarded removal of `mount`, the build runs
`scripts/harden_runtime_tools.py` without network access.

The guard removes the unused `infocmp` and `nsenter` executables and their
inventoried aliases, and clears setuid/setgid bits from remaining runtime files.
It retains package metadata, Essential packages and required shared libraries.
Its preflight refuses unexpected tool ownership, contents or layout, or the
introduction of `mount`, `umount`, `systemd-homed` or `Archive/Tar.pm`. Package
inventory and Python dependency checks must pass before and after hardening.
An unexpected base-image change therefore requires a reviewed guard update.

These changes reduce executable and privilege surfaces. They do not constitute
vendor patches or automatically close package-level CVE findings. Continue to
scan the complete image and preserve attribution for retained libraries.

Bot handoff logic, models, context, database queues and network configuration are
unchanged. Keep the existing runtime contract: UID/GID 10001, all capabilities
dropped, no new privileges, a read-only root filesystem and bounded scratch
storage, CPU, memory and process counts. Image defaults alone do not enforce
these settings; verify the actual runtime configuration before hosted use.

For diagnostics, run reviewed commands with `docker exec --user 10001:10001`.
Do not use privileged `nsenter --join-cgroup` against untrusted workloads, add
writable host cgroup/device mounts, or perform privileged ACL operations over
user-controlled paths or ancestors. Retain operator tools in an appropriate
maintenance environment rather than reinstalling them into the runtime.

Qualify changes with the exact source commit and image ID: guarded failure tests,
package and shared-library inventory, Python imports, API/worker readiness,
restricted database roles, synthetic bot handoffs and bounded PDF validation.
Deployment and native release artifacts require their separate release process.
