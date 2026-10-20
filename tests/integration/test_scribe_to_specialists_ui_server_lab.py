"""Generated PCM through actual recording, reviewed Scribe custody and four product specialist graphs."""

import base64
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_workspace_capture import LocalCore, ref
from tests.integration.test_workspace_capture_operations import capabilities

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    CoreCaptureAccount,
    ExternalIdentity,
    ModelWorkAdmission,
    PatientLink,
)
from cosmas_os.ports import capture_protocol as capture
from cosmas_os.ports.core_capture import CoreCaptureAdmissionSnapshot
from cosmas_os.ports.core_notes import CoreTemplateReceipt
from cosmas_os.ports.creator_review import CreatorReviewView, ProviderEncounter
from cosmas_os.ports.scribe_capture import ScribeSessionReceipt

NODE = Path(shutil.which("node") or "node")
REPO = Path(__file__).resolve().parents[2]


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SyntheticReceiver:
    """The test receiver owns the decrypt key; the real client remains encrypt-only."""

    def __init__(self, workspace_id, appointment_ref, box):
        self.workspace_id, self.appointment_ref, self.box = workspace_id, appointment_ref, box
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.session = None
        self.dek = None
        self.lease = None
        self.reservations, self.authorizations, self.uploads, self.registered, self.idempotent = (
            {},
            {},
            {},
            {},
            {},
        )
        self.complete = False
        self.operations = []
        self.view = None
        self.lock = threading.RLock()
        self.created = datetime.now(UTC)

    def admission(self, binding, attestation, configured, expected):
        if self.session is None:
            if attestation is None:
                from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

                raise ConnectorUnavailable("capture_consent_required")
            self.session = CoreCaptureAdmissionSnapshot(
                contract_version="1",
                operation_ref=ref("scribe_admission"),
                binding_ref=binding.binding_ref,
                workspace_id=binding.workspace_id,
                appointment_ref=binding.appointment_ref,
                consent_record_id=uuid4(),
                session_id=uuid4(),
                status="admitted",
                configured_capture=configured,
                request_nonce=uuid4(),
                checked_at=datetime.now(UTC),
            )
        if expected is not None:
            assert self.session.session_id == expected
        return self.session

    def review(self):
        assert self.session is not None
        if not self.complete:
            return CreatorReviewView(
                schema_version="1.0",
                session_id=self.session.session_id,
                status="created" if self.lease is None else "capturing",
            )
        assert self.view is not None
        return self.view

    def generate_review(self):
        # This is simulated ASR, not speech recognition of generated tones.
        # It is exposed only after every ciphertext/PCM fingerprint and final
        # sequence is verified, and stays bound to that admitted session.
        assert self.complete and self.session is not None and len(self.registered) == 3
        sid, working = uuid4(), uuid4()
        text = (
            "SIMULATED ASR FROM VERIFIED GENERATED AUDIO. Invented Shawn reports heart issues. "
            "Diagnosis, event date, medications and DOB are unavailable. Stem-cell research and "
            "clinical-trial eligibility remain questions for clinician review. No treatment, "
            "referral, booking, delivery or public search was chosen. "
        ) * 5
        origin = dict(
            source_segment_id=str(sid),
            source_segment_version=1,
            source_locale="en-US",
            speaker_id=str(uuid4()),
            speaker_role="patient",
            start_ms=0,
            end_ms=2150,
        )
        self.view = CreatorReviewView.model_validate(
            dict(
                schema_version="1.0",
                session_id=str(self.session.session_id),
                status="transcript_ready",
                source=dict(
                    schema_version="1.0",
                    source_transcript_version=1,
                    language_mode="en-US",
                    transcription_adapter_id="synthetic_verified_pcm",
                    transcription_model_profile_id="simulated_asr_v1",
                    normalization_profile_id="invented_evidence_v1",
                    duration_ms=2150,
                    segments=[{**origin, "content": text, "locale_confidence": None}],
                ),
                working=dict(
                    schema_version="1.0",
                    working_transcript_id=str(working),
                    working_transcript_version=1,
                    source_transcript_version=1,
                    blockers=[],
                    note_ready=True,
                    segments=[
                        {
                            **origin,
                            "resolution": "english_source",
                            "content": text,
                            "translation_id": None,
                            "translation_version": None,
                            "translation_review_id": None,
                        }
                    ],
                ),
                review_queue=dict(
                    schema_version="1.0",
                    session_id=str(self.session.session_id),
                    source_transcript_version=1,
                    working_transcript_id=str(working),
                    working_transcript_version=1,
                    status="complete",
                    items=[],
                ),
                translation_progress=[],
            )
        )

    def upload(self, object_id, authorization, raw):
        with self.lock:
            assert self.dek is not None and self.authorizations.get(object_id) == authorization
            reservation = self.reservations[object_id]
            assert 12 < len(raw) <= 327680 and raw[:8] == b"CSCRIBE1"
            length = struct.unpack(">I", raw[8:12])[0]
            assert 0 < length <= 4096 and 12 + length < len(raw)
            header = json.loads(raw[12 : 12 + length])
            assert set(header) == {"content_encryption", "media_type", "nonce", "schema_version"}
            assert (
                header["content_encryption"] == "A256GCM"
                and header["media_type"] == "audio/wav"
                and header["schema_version"] == "1.0"
            )
            nonce = unb64(header["nonce"])
            assert len(nonce) == 12
            plaintext = AESGCM(self.dek).decrypt(
                nonce, raw[12 + length :], unb64(reservation.additional_authenticated_data)
            )
            number = reservation.sequence_number
            expected_count = 16000 if number < 2 else 2400
            samples = [
                ((i * 17 + (number + 1) * 101) % 24001) - 12000 for i in range(expected_count)
            ]
            with wave.open(io.BytesIO(plaintext), "rb") as audio:
                assert (
                    audio.getnchannels(),
                    audio.getsampwidth(),
                    audio.getframerate(),
                    audio.getcomptype(),
                    audio.getnframes(),
                ) == (1, 2, 16000, "NONE", expected_count)
                pcm = audio.readframes(expected_count)
            assert pcm == struct.pack("<" + "h" * len(samples), *samples)
            proof = dict(
                sequence_number=number,
                ciphertext_sha256=hashlib.sha256(raw).hexdigest(),
                ciphertext_bytes=len(raw),
                wav_sha256=hashlib.sha256(plaintext).hexdigest(),
                pcm_sha256=hashlib.sha256(pcm).hexdigest(),
                frames=expected_count,
            )
            if object_id in self.uploads:
                assert self.uploads[object_id] == proof
            self.uploads[object_id] = proof

    def perform(self, operation, key, origin):
        with self.lock:
            assert self.session is not None
            payload = operation.model_dump(mode="json")
            if key in self.idempotent:
                prior, result = self.idempotent[key]
                assert prior == payload
                return result
            kind = operation.kind
            self.operations.append(kind)
            now = datetime.now(UTC)
            session = self.session.session_id
            if kind == "creator_review":
                result = self.review()
            elif kind == "encryption_key":
                numbers = self.key.public_key().public_numbers()
                result = capture.EncryptionKey(
                    key_version="synthetic-receiver-v1",
                    algorithm="RSA-OAEP-256",
                    public_jwk=capture.PublicJwk(
                        kty="RSA",
                        n=b64(numbers.n.to_bytes(384, "big")),
                        e="AQAB",
                        alg="RSA-OAEP-256",
                        ext=True,
                        key_ops=("wrapKey",),
                    ),
                )
            elif kind == "capabilities":
                result = capabilities()
            elif kind == "bind_key":
                assert operation.payload.key_version == "synthetic-receiver-v1"
                dek = self.key.decrypt(
                    unb64(operation.payload.wrapped_dek),
                    padding.OAEP(
                        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
                    ),
                )
                assert len(dek) == 32 and (self.dek is None or self.dek == dek)
                self.dek = dek
                result = capture.KeyReceipt(
                    session_id=session, key_version=operation.payload.key_version, created_at=now
                )
            elif kind in {"issue_lease", "renew_lease"}:
                if kind == "renew_lease":
                    assert self.lease is not None
                    assert (
                        operation.lease_id == self.lease.lease_id
                        and operation.payload.expected_generation == self.lease.generation
                    )
                self.lease = capture.LeaseReceipt(
                    protocol_version="1.0",
                    receipt_id=uuid4(),
                    session_id=session,
                    lease_id=self.lease.lease_id if self.lease else uuid4(),
                    generation=self.lease.generation + 1 if self.lease else 1,
                    issued_at=now,
                    expires_at=now + timedelta(seconds=900),
                )
                result = self.lease
            elif kind == "capture_lease_state":
                result = capture.LeaseState(
                    session_id=session,
                    current_lease=self.lease,
                    lease_closed=self.complete,
                    session_status="uploaded"
                    if self.complete
                    else "capturing"
                    if self.lease
                    else "created",
                )
            elif kind == "reserve_chunks":
                assert self.lease is not None
                request = operation.payload
                assert (
                    request.channel == "microphone"
                    and request.capture_lease_id == self.lease.lease_id
                    and request.capture_lease_generation == self.lease.generation
                )
                reservations = []
                for number in range(
                    request.first_sequence_number, request.first_sequence_number + request.count
                ):
                    existing = next(
                        (r for r in self.reservations.values() if r.sequence_number == number), None
                    )
                    if existing is None:
                        object_id = uuid4()
                        aad = json.dumps(
                            dict(
                                channel="microphone",
                                object_id=str(object_id),
                                sequence_number=number,
                                session_id=str(session),
                                tenant_id=self.box,
                            ),
                            separators=(",", ":"),
                        ).encode()
                        existing = capture.Reservation(
                            protocol_version="1.0",
                            object_id=object_id,
                            session_id=session,
                            channel="microphone",
                            sequence_number=number,
                            additional_authenticated_data=b64(aad),
                            created_at=now,
                        )
                        self.reservations[str(object_id)] = existing
                    reservations.append(existing)
                result = capture.ReservationReceipt(
                    protocol_version="1.0",
                    batch_id=uuid4(),
                    session_id=session,
                    capture_authorized_until=self.lease.expires_at,
                    reservations=tuple(reservations),
                )
            elif kind == "authorize_upload":
                object_id = str(operation.object_id)
                reservation = self.reservations[object_id]
                authorization = uuid4()
                self.authorizations[object_id] = str(authorization)
                result = capture.UploadReceipt(
                    protocol_version="1.0",
                    authorization_receipt_id=authorization,
                    object_id=operation.object_id,
                    additional_authenticated_data=reservation.additional_authenticated_data,
                    upload_url=origin
                    + "/lab/audio/"
                    + self.workspace_id
                    + "/"
                    + object_id
                    + "?receipt="
                    + str(authorization),
                    expires_at=now + timedelta(minutes=5),
                )
            elif kind == "chunk_receipt":
                object_id = str(operation.object_id)
                registered = self.registered.get(object_id)
                registration = (
                    None
                    if registered is None
                    else capture.Registration(
                        chunk_id=registered.id,
                        sha256=registered.sha256,
                        ciphertext_size_bytes=registered.ciphertext_size_bytes,
                        registered_at=registered.registered_at,
                    )
                )
                result = capture.ChunkReceipt(
                    reservation=self.reservations[object_id],
                    state="registered" if registered else "reserved",
                    registration=registration,
                )
            elif kind == "register_chunk":
                request = operation.payload
                object_id = str(request.object_id)
                proof = self.uploads[object_id]
                assert (
                    request.sequence_number == proof["sequence_number"]
                    and request.channel == "microphone"
                )
                assert (
                    request.sha256 == proof["ciphertext_sha256"]
                    and request.ciphertext_size_bytes == proof["ciphertext_bytes"]
                )
                result = capture.RegisteredChunk(
                    **request.model_dump(), id=uuid4(), session_id=session, registered_at=now
                )
                self.registered[object_id] = result
            elif kind == "complete":
                assert self.lease is not None
                request = operation.payload
                assert (
                    request.capture_lease_id == self.lease.lease_id
                    and request.capture_lease_generation == self.lease.generation
                )
                assert (
                    len(request.channels) == 1
                    and request.channels[0].channel == "microphone"
                    and request.channels[0].final_sequence_number == 2
                )
                assert (
                    sorted(r.sequence_number for r in self.registered.values()) == [0, 1, 2]
                    and len(self.uploads) == 3
                )
                self.complete = True
                self.generate_review()
                result = ScribeSessionReceipt(
                    id=session,
                    appointment_id=self.appointment_ref,
                    practitioner_id="invented-clinician",
                    patient_id="invented-shawn-no-dob",
                    consent_record_id=self.session.consent_record_id,
                    modality="in_person",
                    ingest_mode="chunk_upload",
                    status="uploaded",
                    created_at=self.created,
                )
            else:
                raise AssertionError("Unimplemented synthetic capture operation: " + kind)
            self.idempotent[key] = (payload, result)
            return result

    def evidence(self):
        if self.view:
            assert self.view.source is not None and self.view.working is not None
        return dict(
            synthetic_only=True,
            physical_microphone_tested=False,
            real_asr_tested=False,
            session_id=str(self.session.session_id) if self.session else None,
            complete=self.complete,
            operations=list(self.operations),
            uploads=sorted(self.uploads.values(), key=lambda p: p["sequence_number"]),
            creator_review_sha256=hashlib.sha256(json.dumps(self.view.model_dump(mode="json"),
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                if self.view else None,
            source_transcript_version=self.view.source.source_transcript_version if self.view and self.view.source else None,
            working_transcript_id=str(self.view.working.working_transcript_id) if self.view and self.view.working else None,
            working_transcript_version=self.view.working.working_transcript_version if self.view and self.view.working else None,
        )


class SyntheticCore(LocalCore):
    def __init__(self, receivers):
        super().__init__()
        self.receivers = receivers
        self.upload_origin = ""

    def admit_capture(
        self,
        binding,
        credential,
        attestation,
        key,
        *,
        expected_session_id=None,
        configured_capture=None,
    ):
        return self.receivers[str(binding.workspace_id)].admission(
            binding, attestation, configured_capture, expected_session_id
        )

    def perform_capture_operation(self, binding, credential, session_id, operation, key, **_):
        receiver = self.receivers[str(binding.workspace_id)]
        assert receiver.session.session_id == session_id
        return receiver.perform(operation, key, self.upload_origin)

    def capture_note(self, binding, credential, session_id, selection):
        receiver = self.receivers[str(binding.workspace_id)]
        assert receiver.session.session_id == session_id and receiver.complete
        # A read-only empty template catalog is truthful; this test does not
        # exercise note generation or alter the existing clinical note.
        assert selection.action == "templates"
        return CoreTemplateReceipt(session_id=session_id, templates=())

    def provider_encounter(self, binding, credential, key):
        receiver = self.receivers[str(binding.workspace_id)]
        return ProviderEncounter(
            status="available" if receiver.session else "not_prepared",
            review=receiver.review() if receiver.session else None,
        )


def test_actual_recording_to_reviewed_source_and_four_specialist_ui_graphs(
    engine, monkeypatch, tmp_path
):
    assert NODE.is_file()
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        auth_mode="clerk_jwt",
        synth_seed=False,
        database_url=str(engine.url.render_as_string(hide_password=False)),
        clerk_issuer="https://multi.example.invalid",
        clerk_jwks_url="https://multi.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-multi",
        clerk_organization_id="org_multi",
        clerk_authorized_parties="http://localhost:5173",
        cors_allowed_origins="http://localhost:5173",
        workspace_capture_backend="core",
        core_capture_origin="https://core.example.invalid",
        core_capture_scope="api://synthetic-core/.default",
        core_capture_managed_identity_client_id=str(uuid4()),
        workspace_capture_notes_enabled=True,
    )
    monkeypatch.setattr(api, "settings", configuration)
    runtime = work.team.runtime_settings
    for name in (
        "workspace_enabled",
        "workspace_authenticated_enabled",
        "auth_mode",
        "synth_seed",
        "database_url",
        "clerk_issuer",
        "clerk_jwks_url",
        "clerk_audience",
        "clerk_organization_id",
        "clerk_authorized_parties",
        "cors_allowed_origins",
        "workspace_capture_backend",
        "core_capture_origin",
        "core_capture_scope",
        "core_capture_managed_identity_client_id",
        "workspace_capture_notes_enabled",
    ):
        monkeypatch.setattr(runtime, name, getattr(configuration, name))
    monkeypatch.setattr(runtime, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(runtime, "workspace_llm_api_key", SecretStr("invented-no-network"))
    monkeypatch.setattr(runtime, "workspace_agent_tools_enabled", True)

    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="synthetic-multi", key=signing.public_key())]

    verifier = ClerkTokenVerifier(configuration, jwks_client=Keys(), start_background_refresh=False)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)

    def sessions():
        with Session(engine) as session:
            yield session

    api.app.dependency_overrides[api.get_session] = sessions
    client = TestClient(api.app)

    cases = {}
    receivers = {}
    router = SyntheticCore(receivers)
    api.app.dependency_overrides[api._capture_connection] = lambda: router
    rounds = []
    reads = []
    dispatches = []
    lock = threading.Lock()
    parallel_barrier = None
    original = work.dispatch_claim

    def provider_response(content=None, calls=None):
        return {
            "model": "gpt-4.1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [
                {
                    "finish_reason": "tool_calls" if calls else "stop",
                    "message": {
                        "role": "assistant",
                        "content": None if content is None else json.dumps(content),
                        "tool_calls": calls,
                    }
                    if calls
                    else {"role": "assistant", "content": json.dumps(content)},
                }
            ],
        }

    def dispatch(claim, **_dependencies):
        context = _context(claim.envelope["context"])
        selection = claim.envelope["tool_selection"]
        started = time.monotonic()
        if context.draft_only and context.role in {"research", "visit_prep", "follow_up"}:
            assert "Accepted Scribe summary copied from the exact tool receipt:" in context.question
            assert "confirm missing DOB and owner without inventing facts" in context.question
        assert claim.envelope["contract"] == (
            "cosmas-gpt41-prepared.v7" if context.role == "research" else "cosmas-gpt41-prepared.v6")
        packet_sources = [
            p for p in context.sources if p.label.startswith("Reviewed Scribe snapshot ·")
        ]
        assert len(packet_sources) == 1 and len(packet_sources[0].content) > 1000
        delivered = json.loads(claim.envelope["body"]["messages"][1]["content"])["sources"]
        assert (
            next(p["text"] for p in delivered if p["source_id"] == packet_sources[0].entry_id)
            == packet_sources[0].content
        )

        def provider(request):
            body = json.loads(request.content)
            assert (
                str(request.url) == ENDPOINT
                and body["model"] == "gpt-4.1"
                and body["store"] is False
            )
            tool_messages = [m for m in body["messages"] if m["role"] == "tool"]
            with lock:
                rounds.append(
                    {
                        "admission_id": claim.admission_id,
                        "workspace_id": claim.workspace_id,
                        "role": context.role,
                        "started_s": time.monotonic(),
                        "tool_messages": len(tool_messages),
                        "request_bytes": len(request.content),
                    }
                )
            if not tool_messages:
                calls = []
                if "Collect the revised" in context.question:
                    by_role = {}
                    for p in sorted(
                        selection["teammate_drafts"], key=lambda p: p["revision"], reverse=True
                    ):
                        by_role.setdefault(p["role"], p)
                    selected = list(by_role.values())
                    assert len(selected) == 4
                    for i, p in enumerate(selected):
                        calls.append(
                            {
                                "id": "draft_" + str(i),
                                "type": "function",
                                "function": {
                                    "name": "read_saved_teammate_draft",
                                    "arguments": json.dumps(
                                        {k: p[k] for k in ("entry_id", "revision", "sha256")}
                                    ),
                                },
                            }
                        )
                else:
                    selected = [p for p in selection["sources"] if p["kind"] == "evidence"]
                    assert len(selected) == 1
                    for i, p in enumerate(selected):
                        calls.append(
                            {
                                "id": "source_" + str(i),
                                "type": "function",
                                "function": {
                                    "name": "read_selected_source",
                                    "arguments": json.dumps(
                                        {k: p[k] for k in ("entry_id", "revision", "sha256")}
                                    ),
                                },
                            }
                        )
                    if selection["teammate_drafts"]:
                        p = max(
                            (p for p in selection["teammate_drafts"] if p["role"] == "scribe"),
                            key=lambda p: p["revision"],
                            default=None,
                        )
                        if p is None:
                            p = max(selection["teammate_drafts"], key=lambda p: p["revision"])
                        calls.append(
                            {
                                "id": "origin",
                                "type": "function",
                                "function": {
                                    "name": "read_saved_teammate_draft",
                                    "arguments": json.dumps(
                                        {k: p[k] for k in ("entry_id", "revision", "sha256")}
                                    ),
                                },
                            }
                        )
                if (
                    parallel_barrier is not None
                    and context.draft_only
                    and "Human-requested revision" not in context.question
                ):
                    parallel_barrier.wait(timeout=12)
                return httpx.Response(200, json=provider_response(calls=calls))
            if "Collect the revised" in context.question:
                public = current(cases[claim.workspace_id])
                accepted = {h["result_entry_id"]: h["result_sha256"]
                    for h in public["handoffs"] if (h.get("review") or {}).get("decision") == "accepted"}
                observed = {json.loads(m["content"])["data"]["entry_id"]: json.loads(m["content"])["data"]["sha256"]
                    for m in tool_messages}
                assert len(accepted) == 4 and observed == accepted
            for m in tool_messages:
                value = json.loads(m["content"])
                r = value["receipt"]
                assert (
                    r["actor_agent_id"] != r["initiated_by_human_id"] == claim.owner
                    and r["admission_id"] == claim.admission_id
                )
                if value["tool"] == "read_selected_source":
                    assert (
                        hashlib.sha256(value["data"]["content"].encode()).hexdigest()
                        == value["data"]["sha256"]
                    )
                with lock:
                    reads.append(
                        {
                            "admission_id": claim.admission_id,
                            "workspace_id": claim.workspace_id,
                            "role": context.role,
                            "receipt": r,
                            "tool": value["tool"],
                            "data": {k: value["data"][k] for k in ("entry_id", "revision", "sha256")},
                        }
                    )
            feedback = ""
            if "Human-requested revision of the prior private draft\n" in context.question:
                feedback = json.loads(
                    context.question.split(
                        "Human-requested revision of the prior private draft\n", 1
                    )[1].split("\nTreat the quoted prior draft", 1)[0]
                )["feedback"]
            summary = next((json.loads(m["content"])["data"]["content"]
                for m in tool_messages if json.loads(m["content"])["tool"] == "read_saved_teammate_draft"
                and json.loads(m["content"])["data"]["role"] == "scribe"), None)
            if context.role == "chief":
                targets = {p["role"]: p["address"] for p in context.handoff_targets}
                recipients = (
                    []
                    if "Collect the revised" in context.question
                    else ["scribe"]
                    if "Ask Scribe only" in context.question
                    else ["research", "visit_prep", "follow_up"]
                )
                collected = [json.loads(m["content"])["data"] for m in tool_messages
                    if json.loads(m["content"])["tool"] == "read_saved_teammate_draft"]
                collection_answer = "Collected exact saved private drafts:\n" + "\n".join(
                    p["role"] + ": " + p["entry_id"] + " SHA-256 " + p["sha256"] for p in collected)
                collection_answer += "\nA human must confirm owner, due date and trial eligibility; no clinical signature, public search, booking or delivery is established."
                content = {
                    "answer": collection_answer if "Collect the revised" in context.question else "Invented preparation: retained missing diagnosis, DOB and trial eligibility; private drafts require human review.",
                    "source_ids": [p.entry_id for p in context.sources],
                    "handoffs": [
                        {
                            "role": targets[role],
                            "intended_role": role,
                            "brief": "Prepare an independent "
                            + role
                            + " draft from the exact saved Scribe transcript and summary; preserve unknown heart history and do not send or book."
                            + ("\nAccepted Scribe summary copied from the exact tool receipt:\n" + summary
                                if role != "scribe" and summary is not None else ""),
                            "requirements": REQUIREMENTS,
                        }
                        for role in recipients
                    ],
                }
            elif context.role == "scribe":
                content = {
                    "excerpts": [
                        {"source_id": p.entry_id, "quote": p.content[:1000]}
                        for p in context.sources
                        if p.kind == "evidence"
                    ],
                    "needs_from_clinician": ["Confirm diagnosis, medications and missing DOB."]
                    + ([feedback] if feedback else []),
                }
            else:
                content = {
                    "answer": context.role
                    + " invented private draft. "
                    + ("Applied requested edit: " + feedback + ". " if feedback else "")
                    + "Provider must confirm heart history, medications, responsible owner and due date. Trial eligibility unknown; no public search, booking or delivery occurred.",
                    "source_ids": [p.entry_id for p in context.sources],
                }
            if context.role == "chief" and claim.envelope["baseline"]["flags"]["work_status"]:
                content["intent"] = "conversation"
            return httpx.Response(200, json=provider_response(content=content))

        result = original(
            claim, session_factory=lambda: Session(engine), transport=httpx.MockTransport(provider)
        )
        with lock:
            dispatches.append(
                {
                    "admission_id": claim.admission_id,
                    "workspace_id": claim.workspace_id,
                    "role": context.role,
                    "started_s": started,
                    "ended_s": time.monotonic(),
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
        return result

    monkeypatch.setattr(work, "dispatch_claim", dispatch)

    def current(case):
        with Session(engine) as s:
            return work.project_workspace(s, ws.read(s, case["box"], case["owner"], case["wid"]))

    def inspect(case):
        with Session(engine) as s:
            admissions = list(
                s.scalars(
                    select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == case["wid"])
                )
            )
            events = list(
                s.scalars(
                    select(AuditEvent).where(
                        AuditEvent.box_id == case["box"],
                        AuditEvent.event_type == "workspace.agent_tool_read",
                    )
                )
            )
            public = current(case)
            receiver = receivers[case["wid"]]
            saved = [p for p in public["entries"] if p["kind"] == "evidence"]
            if saved:
                assert receiver.complete and receiver.view is not None and len(saved) == 1
                view = receiver.view.model_dump(mode="json")
                commitment = hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                packet = saved[0]
                assert f"Reviewed Scribe snapshot · {commitment} · 1/1" == packet["source_label"]
                assert f"Original session: {view['session_id']}" in packet["content"]
                assert f"Source transcript version: {view['source']['source_transcript_version']}" in packet["content"]
                assert f"Working transcript: {view['working']['working_transcript_id']}; version {view['working']['working_transcript_version']}" in packet["content"]
                assert f"Reviewed snapshot SHA-256: {commitment}" in packet["content"]
                assert view["working"]["segments"][0]["content"] in packet["content"]
                lineage = dict(session_id=view["session_id"], creator_review_sha256=commitment,
                    source_transcript_version=view["source"]["source_transcript_version"],
                    working_transcript_id=view["working"]["working_transcript_id"],
                    working_transcript_version=view["working"]["working_transcript_version"],
                    entry_id=packet["id"], content_sha256=hashlib.sha256(packet["content"].encode()).hexdigest())
            else:
                lineage = None
            return {
                "workspace": public,
                "verified_lineage": lineage,
                "capture": receivers[case["wid"]].evidence(),
                "admissions": [
                    {
                        "id": p.id,
                        "role": p.prepared_envelope["context"]["role"],
                        "kind": p.kind,
                        "state": p.state,
                        "source_sha256": p.source_sha256,
                        "envelope_sha256": p.envelope_sha256,
                        "agent_id": p.agent_id,
                        "owner_id": p.owner_id,
                    }
                    for p in admissions
                ],
                "tool_receipts": [
                    {
                        "actor_id": p.actor_principal_id,
                        "human_id": p.initiated_by_principal_id,
                        "detail": p.detail,
                    }
                    for p in events
                ],
                "dispatches": [p for p in dispatches if p["workspace_id"] == case["wid"]],
            }

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "authorization,content-type,idempotency-key")
            self.end_headers()

        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                if parsed.path == "/lab/case":
                    q = parse_qs(parsed.query)
                    persona = q["persona"][0]
                    iteration = q["round"][0]
                    assert persona in {
                        "physician",
                        "nurse_practitioner",
                        "physician_assistant",
                    } and iteration in {"1", "2"}
                    with Session(engine) as s:
                        seed = svc.provision_box(
                            svc.Container(s), "Invented multi-specialist " + persona
                        )
                        box, owner = seed["box_id"], seed["owner_id"]
                        subject = str(uuid4())
                        account = ExternalIdentity(
                            box_id=box,
                            principal_id=owner,
                            issuer=api.settings.clerk_issuer,
                            subject=subject,
                            organization_id="org_multi",
                            reviewed_by="Invented owner",
                            evidence_ref="test:multi-synthetic",
                        )
                        s.add(account)
                        s.commit()
                        conf = team.starter_configuration(box, owner)
                        version = team.save(
                            s, box, owner, expected=0, key="multi-team", configuration=conf
                        )
                        link = PatientLink(
                            box_id=box,
                            source_pair_key=str(uuid4()),
                            label="Invented Shawn " + persona + " " + iteration,
                            state="confirmed",
                            confirmed_by_principal_id=owner,
                            attested_at=datetime.now(UTC),
                        )
                        s.add(link)
                        s.flush()
                        appt = AppointmentObservation(
                            box_id=box,
                            patient_link_id=link.id,
                            external_id=ref("appointment"),
                            source="cosmaneura_core",
                            start_at=datetime.now(UTC),
                            patient_label=link.label,
                        )
                        s.add(appt)
                        s.commit()
                        w = ws.create(
                            s, box, owner, appt.id, "multi-create", initial_synthetic_source=False
                        )
                        w = ws.append(
                            s,
                            box,
                            owner,
                            w["id"],
                            expected=w["revision"],
                            key="source-notebook",
                            kind="scratchpad",
                            content="Invented visit notebook. DOB unavailable. Please preserve patient-reported uncertainty.",
                        )["workspace"]
                        capture_account = CoreCaptureAccount(
                            external_identity_id=account.id,
                            core_actor_ref=ref("authority_actor"),
                            core_tenant_ref=ref("authority_tenant"),
                            reviewed_by="Invented recording owner",
                            evidence_ref="test:synthetic-pcm",
                            reviewed_at=datetime.now(UTC),
                        )
                        s.add(capture_account)
                        s.commit()
                        receiver = SyntheticReceiver(w["id"], appt.external_id, box)
                        receivers[w["id"]] = receiver
                        n = notes.save(
                            s,
                            box,
                            owner,
                            w["id"],
                            expected=w["revision"],
                            key="preserved-note",
                            base_note_id=None,
                            source_reply_id=None,
                            content="INVENTED existing clinician note. Must stay unchanged while private specialists prepare drafts.",
                        )
                        monkeypatch.setattr(configuration, "beta_box_id", box)
                        monkeypatch.setattr(runtime, "beta_box_id", box)
                        assert api.settings.workspace_available, (
                            api.settings.runtime_configuration_errors()
                        )
                        case = {
                            "box": box,
                            "owner": owner,
                            "wid": w["id"],
                            "persona": persona,
                            "round": iteration,
                        }
                        cases[w["id"]] = case
                    now = datetime.now(UTC)
                    token = jwt.encode(
                        dict(
                            sub=subject,
                            iss=api.settings.clerk_issuer,
                            aud="cosmas-multi",
                            sid="synthetic-multi",
                            azp="http://localhost:5173",
                            org_id="org_multi",
                            iat=now,
                            nbf=now,
                            exp=now + timedelta(minutes=20),
                        ),
                        signing,
                        algorithm="RS256",
                        headers={"kid": "synthetic-multi"},
                    )
                    return self.respond(
                        200,
                        {
                            "workspace": current(case),
                            "capture": receivers[case["wid"]].evidence(),
                            "token": token,
                            "team_revision": version["revision"],
                            "clinical_note": n,
                        },
                    )
                if parsed.path == "/lab/inspect":
                    return self.respond(
                        200, inspect(cases[parse_qs(parsed.query)["workspace_id"][0]])
                    )
                response = client.get(self.path, headers=dict(self.headers))
                return self.respond(response.status_code, response.json())
            except Exception as error:
                import traceback

                traceback.print_exc()
                return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)})

        def do_PUT(self):
            try:
                parsed = urlsplit(self.path)
                parts = parsed.path.split("/")
                assert len(parts) == 5 and parts[1:3] == ["lab", "audio"]
                receiver = receivers[parts[3]]
                size = int(self.headers.get("Content-Length", "0"))
                assert 0 < size <= 327680
                receiver.upload(
                    parts[4], parse_qs(parsed.query)["receipt"][0], self.rfile.read(size)
                )
                return self.respond(201, {"synthetic_uploaded": True})
            except Exception as error:
                return self.respond(422, {"detail": type(error).__name__ + ": " + str(error)})

        def do_POST(self):
            nonlocal parallel_barrier
            try:
                size = int(self.headers.get("Content-Length", "0"))
                assert 0 <= size <= 12288
                body = self.rfile.read(size)
                if self.path == "/lab/work":
                    value = json.loads(body)
                    case = cases[value["workspace_id"]]
                    with Session(engine) as s:
                        reserved = list(
                            s.scalars(
                                select(ModelWorkAdmission).where(
                                    ModelWorkAdmission.workspace_id == case["wid"],
                                    ModelWorkAdmission.kind == "private_handoff",
                                    ModelWorkAdmission.state == "reserved",
                                )
                            )
                        )
                    assert len(reserved) in {1, 3}, len(reserved)
                    parallel_barrier = threading.Barrier(3) if len(reserved) == 3 else None
                    with ThreadPoolExecutor(max_workers=len(reserved)) as pool:
                        outcomes = list(
                            pool.map(
                                lambda _: work.process_next(
                                    lambda: Session(engine), dispatch=dispatch
                                ),
                                reserved,
                            )
                        )
                    parallel_barrier = None
                    assert all(outcomes)
                    return self.respond(200, inspect(case))
                response = client.post(self.path, headers=dict(self.headers), content=body)
                return self.respond(response.status_code, response.json())
            except Exception as error:
                parallel_barrier = None
                import traceback

                traceback.print_exc()
                return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    router.upload_origin = f"http://127.0.0.1:{server.server_port}"
    report_root = Path(os.environ.get("COSMAS_SCRIBE_SPECIALIST_EVIDENCE_DIR", str(tmp_path)))
    report_root.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env.update(
        COSMAS_SCRIBE_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_SCRIBE_LAB_REPORT=str(report_root / "ui-server-lab.json"),
    )
    try:
        command = [
            str(NODE),
            "node_modules/vitest/vitest.mjs",
            "run",
            "src/ScribeToSpecialistsServerLab.test.tsx",
            "--maxWorkers=1",
        ]
        browser_driver = os.environ.get("COSMAS_SCRIBE_BROWSER_DRIVER")
        if browser_driver:
            command = [str(NODE), browser_driver]
            env.update(
                VITE_API_BASE=f"http://127.0.0.1:{server.server_port}",
                VITE_CAPTURE_UPLOAD_ORIGINS=f"http://127.0.0.1:{server.server_port}",
            )
            for key in ("COSMAS_PLAYWRIGHT_MODULE_URL", "COSMAS_CHROMIUM_EXECUTABLE", "COSMAS_SCRIBE_BROWSER_SCENARIO"):
                if key in os.environ:
                    env[key] = os.environ[key]
        selected_test = os.environ.get("COSMAS_SCRIBE_LAB_TEST_NAME")
        if selected_test and not browser_driver:
            command.extend(["-t", selected_test])
        result = subprocess.run(
            command,
            cwd=REPO / "web",
            env=env,
            text=True,
            capture_output=True,
            timeout=900,
        )
        (report_root / "vitest.log").write_text(result.stdout + result.stderr)
        report = {
            "synthetic_only": True,
            "cases": [inspect(case) for case in cases.values()],
            "rounds": rounds,
            "reads": reads,
            "dispatches": dispatches,
            "vitest_returncode": result.returncode,
        }
        (report_root / "backend-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads((report_root / "ui-server-lab.json").read_text())
        expected_cases = 1 if selected_test else 6
        assert evidence["total"] == evidence["completed"] == expected_cases
        assert (
            len(cases) == expected_cases
            and len(dispatches) == 11 * expected_cases
            and len(rounds) == 22 * expected_cases
            and len(reads) == 15 * expected_cases
        )
        for case in report["cases"]:
            assert len(case["admissions"]) == 11 and all(
                p["state"] == "completed" for p in case["admissions"]
            )
            assert len(case["tool_receipts"]) == 15
    finally:
        server.shutdown()
        # Revoke only this fixture's human account, then let the product claim
        # guard close its own saved reservations; never drain the global queue.
        for case in cases.values():
            with Session(engine) as s:
                owned = list(s.scalars(select(ModelWorkAdmission).where(
                    ModelWorkAdmission.workspace_id == case["wid"],
                    ModelWorkAdmission.box_id == case["box"],
                    ModelWorkAdmission.owner_id == case["owner"],
                    ModelWorkAdmission.state == "reserved")))
                if owned:
                    account = s.scalar(select(ExternalIdentity).where(
                        ExternalIdentity.box_id == case["box"], ExternalIdentity.principal_id == case["owner"]))
                    assert account is not None
                    account.active = False
                    ids = [r.id for r in owned]
                    s.commit()
                    for admission_id in ids:
                        assert work.claim(s, case["box"], case["owner"], admission_id) is None

        server.server_close()
        thread.join(timeout=5)
        client.close()
        api.app.dependency_overrides.clear()
