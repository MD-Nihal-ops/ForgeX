"""Thread-safe in-memory API session storage for the MVP."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import (
    AnalysisJobRecord,
    load_persisted_state,
    save_persisted_state,
)

_analysis_sessions: dict[str, str] = {}


class SessionStore:
    """Store JSON-compatible workflow state and calculated design results."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def create(self, session_id: str | None = None) -> str:
        ident = session_id or str(uuid4())
        with self._lock:
            self._sessions[ident] = {}
        return ident

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._sessions.get(session_id)
            return deepcopy(state) if state is not None else None

    def save(self, session_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Unknown ForgeX session: {session_id}")
            self._sessions[session_id] = deepcopy(state)

    def save_or_create(self, session_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._sessions[session_id] = deepcopy(state)

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
        _analysis_sessions.clear()


session_store = SessionStore()


async def get_workflow_state(
    session_id: str,
    database_session: AsyncSession | None,
) -> dict[str, Any] | None:
    if database_session is not None:
        try:
            persisted = await load_persisted_state(database_session, session_id)
            if persisted is not None:
                session_store.save_or_create(session_id, persisted)
                return persisted
        except SQLAlchemyError:
            await database_session.rollback()
            from logging import getLogger

            getLogger(__name__).warning(
                "Database read failed; falling back to in-memory session storage."
            )
    return session_store.get(session_id)


async def save_workflow_state(
    session_id: str,
    state: dict[str, Any],
    database_session: AsyncSession | None,
) -> None:
    session_store.save_or_create(session_id, state)
    if database_session is not None:
        try:
            await save_persisted_state(database_session, session_id, state)
        except SQLAlchemyError:
            await database_session.rollback()
            from logging import getLogger

            getLogger(__name__).warning(
                "Database write failed; continuing with in-memory session storage."
            )


async def create_workflow_session(
    session_id: str | None,
    database_session: AsyncSession | None,
) -> str:
    ident = session_id or str(uuid4())
    await save_workflow_state(ident, {}, database_session)
    return ident


def remember_analysis_session(analysis_id: str, session_id: str) -> None:
    _analysis_sessions[analysis_id] = session_id


async def locate_analysis_job(
    analysis_id: str,
    database_session: AsyncSession | None,
) -> tuple[str, dict[str, Any]] | None:
    if database_session is not None:
        try:
            record = await database_session.get(AnalysisJobRecord, analysis_id)
            if record is not None:
                state = await load_persisted_state(database_session, record.session_id)
                if state is not None:
                    session_store.save_or_create(record.session_id, state)
                    return record.session_id, state
        except SQLAlchemyError:
            await database_session.rollback()
    session_id = _analysis_sessions.get(analysis_id)
    if session_id is None:
        return None
    state = session_store.get(session_id)
    if state is None:
        return None
    return session_id, state
