"""Routine migration-job entrypoint: upgrade tables, then seed current schemas."""

from __future__ import annotations

from typing import Any


def seed_runtime_schema_registry(conn: Any) -> None:
    from api.main import app
    from api.request_schema import collect_api_request_schema_definitions
    from api.safe_import import get_degraded_modules
    from ontology.schema_definitions import (
        domain_action_schema_definitions,
        ontology_schema_definitions,
        seed_schema_definitions,
    )

    degraded = get_degraded_modules()
    if degraded:
        raise RuntimeError(f"Refusing to seed an incomplete API schema registry: {', '.join(sorted(degraded))}")
    seed_schema_definitions(
        conn,
        [
            *ontology_schema_definitions(),
            *domain_action_schema_definitions(),
            *collect_api_request_schema_definitions(app.router.routes),
        ],
    )


def main() -> None:
    from alembic import command
    from alembic.config import Config
    from dotenv import load_dotenv

    from api.postgres import close_pools
    from api.postgres_state import PostgresStateConnection

    load_dotenv()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        # The adapter reuses the same idempotent upsert as the former boot seed.
        # A failure rolls back the seed and fails the job before API rollout.
        with PostgresStateConnection() as conn:
            seed_runtime_schema_registry(conn)
    finally:
        close_pools()


if __name__ == "__main__":
    main()
