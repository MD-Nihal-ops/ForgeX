"""Optional asynchronous SQLAlchemy persistence for ForgeX workflow state."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "forgex_users"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SessionRecord(Base):
    __tablename__ = "forgex_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("forgex_users.user_id"), nullable=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class EngineeringBriefRecord(Base):
    __tablename__ = "forgex_engineering_briefs"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ClarificationRecord(Base):
    __tablename__ = "forgex_clarification_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(String)


class ConfirmedBriefRecord(Base):
    __tablename__ = "forgex_confirmed_briefs"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class GeneratedAlternativeRecord(Base):
    __tablename__ = "forgex_generated_alternatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    alternative_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class CalculationRecord(Base):
    __tablename__ = "forgex_calculations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class EvidenceRecord(Base):
    __tablename__ = "forgex_evidence_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ComparisonRecord(Base):
    __tablename__ = "forgex_comparison_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ArtifactRecord(Base):
    __tablename__ = "forgex_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(32))
    design_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AnalysisJobRecord(Base):
    __tablename__ = "forgex_analysis_jobs"

    analysis_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("forgex_sessions.session_id", ondelete="CASCADE"), index=True
    )
    design_id: Mapped[str] = mapped_column(String(128))
    analysis_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    solver_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    solver_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_artifact_paths: Mapped[list[str]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON)
    disclaimer: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


def database_enabled() -> bool:
    return os.getenv("FORGEX_USE_DATABASE", "").strip().casefold() == "true"


def _configured_url() -> str | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


engine = None
session_factory: async_sessionmaker[AsyncSession] | None = None

if database_enabled():
    configured_url = _configured_url()
    if configured_url:
        try:
            engine = create_async_engine(configured_url, pool_pre_ping=True)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
        except (SQLAlchemyError, ValueError):
            logger.warning(
                "Could not configure database persistence; using in-memory storage."
            )


async def initialize_schema() -> bool:
    """Create the MVP schema; deployments may later replace this with Alembic."""
    if not database_enabled() or engine is None:
        return False
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except SQLAlchemyError:
        logger.warning(
            "Database schema initialization failed; using in-memory storage."
        )
        return False
    return True


async def get_db_session() -> AsyncIterator[AsyncSession | None]:
    """FastAPI dependency; tests may override this with an isolated async session."""
    if not database_enabled() or session_factory is None:
        yield None
        return
    async with session_factory() as database_session:
        yield database_session


async def load_persisted_state(
    database_session: AsyncSession,
    session_id: str,
) -> dict[str, Any] | None:
    row = await database_session.get(SessionRecord, session_id)
    return dict(row.state) if row is not None else None


async def save_persisted_state(
    database_session: AsyncSession,
    session_id: str,
    state: dict[str, Any],
) -> None:
    row = await database_session.get(SessionRecord, session_id)
    if row is None:
        row = SessionRecord(session_id=session_id, state=dict(state))
        database_session.add(row)
    else:
        row.state = dict(state)
        row.updated_at = datetime.now(UTC)

    for record_type in (
        EngineeringBriefRecord,
        ClarificationRecord,
        ConfirmedBriefRecord,
        GeneratedAlternativeRecord,
        CalculationRecord,
        EvidenceRecord,
        ComparisonRecord,
        ArtifactRecord,
        AnalysisJobRecord,
    ):
        await database_session.execute(
            delete(record_type).where(record_type.session_id == session_id)
        )

    draft = state.get("extraction")
    if draft:
        database_session.add(
            EngineeringBriefRecord(session_id=session_id, payload=dict(draft))
        )
    confirmed = state.get("confirmed_brief")
    if confirmed:
        database_session.add(
            ConfirmedBriefRecord(session_id=session_id, payload=dict(confirmed))
        )

    for sequence, message in enumerate(state.get("clarification_history", [])):
        database_session.add(
            ClarificationRecord(
                session_id=session_id,
                sequence=sequence,
                role=str(message["role"]),
                content=str(message["content"]),
            )
        )

    result = state.get("design_result") or {}
    for alternative in result.get("alternatives", []):
        database_session.add(
            GeneratedAlternativeRecord(
                session_id=session_id,
                alternative_id=str(alternative.get("id", "")),
                payload=dict(alternative),
            )
        )
    for record_type, key in (
        (CalculationRecord, "calculations"),
        (EvidenceRecord, "evidence_rows"),
        (ComparisonRecord, "comparison_table"),
    ):
        for sequence, item in enumerate(result.get(key, [])):
            database_session.add(
                record_type(
                    session_id=session_id,
                    sequence=sequence,
                    payload=dict(item),
                )
            )

    artifacts = [
        ("report", state.get("report_artifact")),
        *(
            ("cad", artifact)
            for artifact in state.get("cad_artifacts", [])
        ),
        *(
            ("preview", artifact)
            for artifact in state.get("preview_artifacts", [])
        ),
    ]
    for artifact_type, artifact in artifacts:
        if not artifact:
            continue
        database_session.add(
            ArtifactRecord(
                session_id=session_id,
                artifact_type=artifact_type,
                design_id=str(artifact.get("design_id", "")),
                status=str(artifact.get("status", "CREATED")),
                payload=dict(artifact),
            )
        )
    for job in state.get("analysis_jobs", []):
        database_session.add(
            AnalysisJobRecord(
                analysis_id=str(job["analysis_id"]),
                session_id=session_id,
                design_id=str(job["design_id"]),
                analysis_type=str(job["analysis_type"]),
                status=str(job["status"]),
                input_snapshot=dict(job["input_snapshot"]),
                solver_name=job.get("solver_name"),
                solver_version=job.get("solver_version"),
                created_at=datetime.fromisoformat(job["created_at"]),
                completed_at=(
                    datetime.fromisoformat(job["completed_at"])
                    if job.get("completed_at")
                    else None
                ),
                result_artifact_paths=list(job.get("result_artifact_paths", [])),
                limitations=list(job.get("limitations", [])),
                disclaimer=str(job["disclaimer"]),
                payload=dict(job),
            )
        )
    await database_session.commit()


async def clear_database(database_session: AsyncSession) -> None:
    await database_session.execute(delete(SessionRecord))
    await database_session.commit()


async def close_database() -> None:
    if engine is not None:
        await engine.dispose()
