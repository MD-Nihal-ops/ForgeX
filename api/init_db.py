"""Initialize the configured ForgeX SQLAlchemy schema."""

from __future__ import annotations

import asyncio
import logging

from api.database import initialize_schema


async def _main() -> None:
    initialized = await initialize_schema()
    if not initialized:
        raise SystemExit(
            "Database schema was not initialized. Set FORGEX_USE_DATABASE=true "
            "and provide a valid DATABASE_URL."
        )
    logging.getLogger(__name__).info("ForgeX database schema initialized.")


if __name__ == "__main__":
    asyncio.run(_main())
