"""Explicit managed sandbox installation, transport provenance and shared quota."""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "n13f9b2d7654"
down_revision = "m02e8a1c6543"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.execute("ALTER TABLE ehr_read_requests ADD COLUMN transport varchar(20) NOT NULL DEFAULT 'mock'")
    op.create_check_constraint("ck_ehr_read_transport", "ehr_read_requests", "transport IN ('mock','vendor_sandbox')")
    prior = run_path(str(Path(__file__).with_name("m02e8a1c6543_ehr_read_custody.py")))["GUARDS"]
    for start, finish, replacements in (
        ("CREATE FUNCTION public.ehr_read_payload_valid", "CREATE FUNCTION public.ehr_read_snapshot_valid", PAYLOAD_CHANGES),
        ("CREATE FUNCTION public.guard_ehr_read_request", "CREATE TRIGGER ehr_read_request_guard", REQUEST_CHANGES),
    ):
        sql = prior[prior.index(start):prior.index(finish)]
        sql = sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
        for before, after in replacements:
            if sql.count(before) != 1:
                raise RuntimeError("Prior EHR guard differs from the reviewed transport extension")
            sql = sql.replace(before, after)
        op.execute(sql)
    op.execute(GUARDS)


def downgrade():
    raise RuntimeError("Retain sandbox installation receipts and transport provenance")


PAYLOAD_CHANGES = (
    ("OR NOT public.finance_settings_keys(priv,ARRAY['binding_sha256','request_sha256','items','provider_sources'])",
     "OR NOT (public.finance_settings_keys(priv,ARRAY['binding_sha256','request_sha256','items','provider_sources']) OR "
     "public.finance_settings_keys(priv,ARRAY['binding_sha256','request_sha256','items','provider_sources','transport']))\n"
     "  OR coalesce(priv->>'transport','mock') IS DISTINCT FROM r.transport\n"
     "  OR (priv ? 'transport' AND jsonb_typeof(priv->'transport') IS DISTINCT FROM 'string')"),
)
REQUEST_CHANGES = (
    ("OR NEW.valid_until<=clock_timestamp()",
     "OR NEW.valid_until<=clock_timestamp()\n"
     "  OR EXISTS(SELECT 1 FROM public.elation_sandbox_installation_receipts i WHERE (i.box_id,i.owner_id,i.idempotency_key)=(NEW.box_id,NEW.owner_id,NEW.idempotency_key))\n"
     "  OR (NEW.transport='vendor_sandbox' AND NOT EXISTS(SELECT 1 FROM public.elation_sandbox_installation_receipts i WHERE i.binding_id=NEW.binding_id))"),
    ("OR NOT public.ehr_read_request_current(root.id) OR NEW.valid_until>root.valid_until",
     "OR NOT public.ehr_read_request_current(root.id) OR NEW.valid_until>root.valid_until OR NEW.transport IS DISTINCT FROM root.transport"),
)


TABLES = r"""
CREATE TABLE elation_sandbox_installation_receipts (
	id UUID NOT NULL, 
	binding_id UUID NOT NULL, 
	account_id UUID NOT NULL, 
	installation_id UUID NOT NULL, 
	installation_sha256 VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(binding_id, box_id, owner_id, account_id) REFERENCES ehr_read_bindings (id, box_id, owner_id, account_id), 
	CONSTRAINT uq_elation_install_key UNIQUE (box_id, owner_id, idempotency_key), 
	CONSTRAINT uq_elation_install_binding UNIQUE (binding_id), 
	CONSTRAINT uq_elation_install_version UNIQUE (box_id, owner_id, installation_id, installation_sha256), 
	CONSTRAINT ck_elation_install_key CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CHECK (installation_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE elation_sandbox_quotas (
	credential_key VARCHAR(64) NOT NULL, 
	last_permitted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (credential_key), 
	CHECK (credential_key ~ '^[a-f0-9]{64}$')
);

CREATE TABLE elation_sandbox_quota_minutes (
	credential_key VARCHAR(64) NOT NULL, 
	minute TIMESTAMP WITH TIME ZONE NOT NULL, 
	requests INTEGER NOT NULL, 
	PRIMARY KEY (credential_key, minute), 
	CONSTRAINT ck_elation_quota_minute CHECK (requests BETWEEN 1 AND 149999 AND isfinite(minute)), 
	FOREIGN KEY(credential_key) REFERENCES elation_sandbox_quotas (credential_key)
);
"""

GUARDS = r"""
CREATE FUNCTION public.guard_elation_sandbox_installation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Sandbox installation receipts are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE (id,box_id)=(NEW.owner_id,NEW.box_id) FOR UPDATE;
 IF NOT public.ehr_read_binding_current(NEW.binding_id)
  OR EXISTS(SELECT 1 FROM public.ehr_read_requests r WHERE (r.box_id,r.owner_id,r.idempotency_key)=(NEW.box_id,NEW.owner_id,NEW.idempotency_key))
  OR NEW.request_sha256 IS DISTINCT FROM public.google_calendar_json_digest(jsonb_build_object('action','install',
   'installation_id',NEW.installation_id,'installation_sha256',NEW.installation_sha256,'idempotency_key',NEW.idempotency_key))
 THEN RAISE EXCEPTION 'Sandbox installation authority or commitment invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER elation_sandbox_installation_guard BEFORE INSERT OR UPDATE OR DELETE ON public.elation_sandbox_installation_receipts
 FOR EACH ROW EXECUTE FUNCTION public.guard_elation_sandbox_installation();
"""
