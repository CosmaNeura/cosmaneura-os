"""Ciphertext-only generic fax document custody, forward migration only."""

from alembic import op

revision = "g57d9b3e0128"
down_revision = "f46c8a2d9017"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(CUSTODY)

def downgrade():
    raise RuntimeError("Retain authenticated fax document custody")

CUSTODY = r"""
-- The prior generic fax migration was unreleased WIP. Existing acquired
-- plaintext requires an explicit reviewed conversion; never mark it encrypted.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.fax_inbound_outcomes WHERE state='acquired')
 THEN RAISE EXCEPTION 'acquired plaintext fax custody requires explicit conversion'; END IF;
END $$;
ALTER TABLE public.fax_inbound_outcomes ADD COLUMN document_byte_length integer;
ALTER TABLE public.fax_inbound_outcomes ADD COLUMN document_ciphertext_sha256 varchar(64);
ALTER TABLE public.fax_inbound_outcomes ADD COLUMN document_key_id varchar(80);
DO $$ DECLARE n text; BEGIN
 FOR n IN SELECT conname FROM pg_constraint WHERE conrelid='public.fax_inbound_outcomes'::regclass
 AND contype='c' AND pg_get_constraintdef(oid) LIKE '%octet_length(document)%' LOOP
  EXECUTE format('ALTER TABLE public.fax_inbound_outcomes DROP CONSTRAINT %I',n);
 END LOOP;
END $$;
ALTER TABLE public.fax_inbound_outcomes ADD CONSTRAINT ck_fax_inbound_encrypted_document CHECK (
 (
 (state='acquired' AND document IS NOT NULL AND octet_length(document)=document_byte_length+28
  AND document_byte_length BETWEEN 1 AND 1048576 AND pages BETWEEN 1 AND 50
  AND document_sha256 ~ '^[a-f0-9]{64}$' AND document_ciphertext_sha256 ~ '^[a-f0-9]{64}$'
  AND document_key_id ~ '^[A-Za-z0-9:_-]{1,80}$') OR
 (state='outcome_unconfirmed' AND document IS NULL AND document_sha256 IS NULL AND pages IS NULL
  AND document_byte_length IS NULL AND document_ciphertext_sha256 IS NULL AND document_key_id IS NULL)) IS TRUE);
CREATE OR REPLACE FUNCTION public.guard_fax_inbound_outcome() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c public.fax_inbound_attempts;
BEGIN
 SELECT * INTO c FROM public.fax_inbound_attempts WHERE operation_id=NEW.operation_id;
 IF c.operation_id IS NULL OR (c.box_id,c.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NEW.state='acquired' AND (NEW.document_ciphertext_sha256 IS DISTINCT FROM encode(sha256(NEW.document),'hex')
   OR NOT EXISTS(SELECT 1 FROM public.fax_inbound_dispatches WHERE operation_id=NEW.operation_id))
 THEN RAISE EXCEPTION 'fax ciphertext outcome invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

