"""Alembic environment."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cosmas_os import (  # noqa: F401
    finance_models,
    finance_setup_models,
    google_connection_models,
    inbox_handoff_models,
    inbox_models,
    membership_models,
    microsoft_connection_models,
    models,
    portal_models,
    portal_work_models,
    practice_access_models,
    research_models,
    scheduling_enrollment_models,
    scheduling_login_models,
    vendor_models,
    vendor_setup_models,
)
from cosmas_os.config import settings
from cosmas_os.db import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# Alembic stores this value in a ConfigParser, where percent-encoded URL
# credentials must escape "%" to avoid interpolation errors.
if config.attributes.get("connection") is None:
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
