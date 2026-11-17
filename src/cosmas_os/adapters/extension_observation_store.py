"""Local-proof-only Postgres table; never registered in hosted migrations/models."""
from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from cosmas_os.application.extension_screen_observations import ScreenObservation

DDL = (
    "CREATE SCHEMA extension_signin_proof",
    """CREATE TABLE extension_signin_proof.observations (
        id uuid PRIMARY KEY, box_id uuid NOT NULL REFERENCES box_contexts(id),
        principal_id uuid NOT NULL, payload text NOT NULL,
        payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (principal_id, box_id) REFERENCES principals(id, box_id),
        CHECK (payload_sha256 = encode(sha256(convert_to(payload, 'UTF8')), 'hex'))
    )""",
    """CREATE FUNCTION extension_signin_proof.refuse_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable_observation'; END $$""",
    """CREATE TRIGGER immutable_observation BEFORE UPDATE OR DELETE OR TRUNCATE
        ON extension_signin_proof.observations FOR EACH STATEMENT
        EXECUTE FUNCTION extension_signin_proof.refuse_mutation()""",
)


def initialize_observations(connection: Connection) -> None:
    for statement in DDL:
        connection.execute(text(statement))


class PostgresObservationStore:
    def __init__(self, session: Session):
        self.session = session

    def append(self, observation: ScreenObservation) -> None:
        if hashlib.sha256(observation.payload.encode()).hexdigest() != observation.payload_sha256:
            raise ValueError("invalid_observation")
        self.session.execute(text("""INSERT INTO extension_signin_proof.observations
            (id, box_id, principal_id, payload, payload_sha256)
            VALUES (:id, :box_id, :principal_id, :payload, :payload_sha256)"""), {
                "id": observation.id, "box_id": observation.box_id,
                "principal_id": observation.principal_id, "payload": observation.payload,
                "payload_sha256": observation.payload_sha256})
        self.session.commit()
