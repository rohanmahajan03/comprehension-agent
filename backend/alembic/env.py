from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.config import get_settings
from app.db.engine import Base
from app.db import models  # noqa: F401 — populates Base.metadata as a side effect

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Read from the app's own Settings rather than alembic.ini, so DATABASE_URL has exactly
# one source of truth (see docs/specs/2026-08-21-persistent-storage-design.md §6).
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Interpret the config file for Python logging.
# disable_existing_loggers=False is load-bearing: main.py runs migrations in-process from
# the lifespan hook, and fileConfig's default (True) disables every logger not named in
# alembic.ini's [loggers] — which includes uvicorn, uvicorn.error, and uvicorn.access.
# Leaving it at the default silently kills all backend logging for the life of the server:
# no access lines and no tracebacks, so any 500 looks like it never happened.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
