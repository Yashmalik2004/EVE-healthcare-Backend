"""Alembic environment configuration.

This file is executed by Alembic to configure migrations.  It:

1. Adds the project root to sys.path so ``app.*`` imports resolve.
2. Imports all ORM model modules so their tables are included in
   ``Base.metadata`` and Alembic can autogenerate migrations.
3. Overrides ``sqlalchemy.url`` from ``alembic.ini`` with the live
   database URI from application settings.
"""

import sys
from logging.config import fileConfig
from os.path import abspath, dirname

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure project root is on sys.path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

# Alembic Config object — access values within the .ini file
config = context.config

# Setup loggers defined in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so they register with Base.metadata.
# This import must come after sys.path manipulation.
import app.models  # noqa: F401, E402

from app.core.config import settings  # noqa: E402
from app.db.database import Base  # noqa: E402

# Provide metadata to Alembic for autogenerate support
target_metadata = Base.metadata

# Override the placeholder URL in alembic.ini with the live database URI
config.set_main_option("sqlalchemy.url", settings.SQLALCHEMY_DATABASE_URI)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required)."""
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
    """Run migrations in 'online' mode (connects to the live database)."""
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
