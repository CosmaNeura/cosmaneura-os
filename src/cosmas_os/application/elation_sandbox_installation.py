"""Human installation of exact server-configured sandbox scope; no provider calls."""

from sqlalchemy import select

from cosmas_os.adapters.elation_sandbox_runtime import ManagedElationSandboxReads
from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrReadBinding, EhrReadRequest
from cosmas_os.elation_sandbox_models import ElationSandboxInstallationReceipt


def receipt(s, row, port):
    from cosmas_os.application import ehr_reads as ehr

    ehr._identity(s, row.box_id, row.owner_id, row.account_id)
    binding = s.get(EhrReadBinding, row.binding_id, populate_existing=True)
    if binding is None:
        raise ws.WorkspaceError("ehr_sandbox_installation_unavailable")
    body = dict(action="install", installation_id=row.installation_id,
        installation_sha256=row.installation_sha256, idempotency_key=row.idempotency_key)
    if payload_hash(body) != row.request_sha256:
        raise ws.WorkspaceError("ehr_sandbox_installation_unavailable")
    current = False
    try:
        candidate = port.selected(ehr._scope(binding)) if type(port) is ManagedElationSandboxReads else None
        current = (candidate is not None and str(candidate.id) == row.installation_id
            and candidate.commitment() == row.installation_sha256
            and ehr._binding(s, ehr._identity(s, row.box_id, row.owner_id, row.account_id),
                binding.connection_id, binding.binding_digest, port=port).id == binding.id)
    except ws.WorkspaceError:
        pass
    return dict(contract_version=1, status="installed" if current else "unavailable", transport="vendor_sandbox",
        installation_id=row.installation_id, installation_sha256=row.installation_sha256,
        connection_id=binding.connection_id, binding_sha256=binding.binding_digest,
        idempotency_key=row.idempotency_key, request_sha256=row.request_sha256)


def resolve(s, box, owner, account_id, key, port):
    row = s.scalar(select(ElationSandboxInstallationReceipt).where(
        ElationSandboxInstallationReceipt.box_id == box, ElationSandboxInstallationReceipt.owner_id == owner,
        ElationSandboxInstallationReceipt.idempotency_key == key))
    if row is None:
        return None
    if row.account_id != account_id:
        raise ws.WorkspaceError("idempotency_conflict")
    return receipt(s, row, port)


def install(s, box, owner, account_id, *, installation_id, installation_sha256, key, port, reauthenticate=None):
    from cosmas_os.application import ehr_reads as ehr

    ehr._key(key)
    ehr._digest(installation_sha256)
    ehr._access(s, box, owner, account_id, reauthenticate)
    body = dict(action="install", installation_id=installation_id,
        installation_sha256=installation_sha256, idempotency_key=key)
    previous = resolve(s, box, owner, account_id, key, port)
    if previous is not None:
        if previous["request_sha256"] != payload_hash(body):
            raise ws.WorkspaceError("idempotency_conflict")
        return previous
    if s.scalar(select(EhrReadRequest.id).where(EhrReadRequest.box_id == box,
            EhrReadRequest.owner_id == owner, EhrReadRequest.idempotency_key == key)):
        raise ws.WorkspaceError("idempotency_conflict")
    if type(port) is not ManagedElationSandboxReads or not port.available():
        raise ws.WorkspaceError("ehr_read_unavailable", 404)
    candidates = [candidate for candidate in port.candidates(box, owner, account_id)
        if str(candidate.id) == installation_id and candidate.commitment() == installation_sha256]
    if len(candidates) != 1:
        raise ws.WorkspaceError("ehr_sandbox_installation_changed")
    selected = candidates[0]
    if not port.current(selected.scope):
        raise ws.WorkspaceError("ehr_sandbox_setup_unavailable", 503)
    scope = selected.scope
    old_version = s.scalar(select(EhrReadBinding).where(EhrReadBinding.box_id == box,
        EhrReadBinding.owner_id == owner, EhrReadBinding.connection_id == str(scope.connection_id),
        EhrReadBinding.credential_generation == str(scope.credential_generation),
        EhrReadBinding.practice_id == str(scope.practice_id)))
    if old_version is not None:
        raise ws.WorkspaceError("ehr_sandbox_generation_already_installed")
    old = s.scalars(select(EhrReadBinding).where(EhrReadBinding.box_id == box,
        EhrReadBinding.owner_id == owner, EhrReadBinding.account_id == account_id,
        EhrReadBinding.state == "active").with_for_update())
    now = model_work.now(s)
    for binding in old:
        binding.state, binding.revoked_at = "revoked", now
    s.flush()
    binding = EhrReadBinding(box_id=box, owner_id=owner, account_id=account_id,
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id=str(scope.practice_id), practice_name=scope.practice_name,
        binding_digest=scope.commitment(), environment="sandbox", state="active")
    s.add(binding)
    s.flush()
    row = ElationSandboxInstallationReceipt(box_id=box, owner_id=owner, account_id=account_id,
        binding_id=binding.id, installation_id=installation_id, installation_sha256=installation_sha256,
        idempotency_key=key, request_sha256=payload_hash(body))
    s.add(row)
    if reauthenticate is not None:
        reauthenticate()
    ehr._identity(s, box, owner, account_id, writing=True)
    if not port.current(scope):
        raise ws.WorkspaceError("ehr_sandbox_installation_changed")
    s.commit()
    ehr._access(s, box, owner, account_id, reauthenticate)
    return receipt(s, row, port)
