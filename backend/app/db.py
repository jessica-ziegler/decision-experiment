"""MongoDB persistence: one document per session, events appended as they happen."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymongo import AsyncMongoClient

log = logging.getLogger(__name__)


class Store:
    def __init__(self, url: str, db_name: str):
        self._client = AsyncMongoClient(url, tz_aware=True)
        self._sessions = self._client[db_name]["sessions"]

    async def connect(self, attempts: int = 15) -> None:
        for i in range(attempts):
            try:
                await self._client.admin.command("ping")
                log.info("Connected to MongoDB")
                return
            except Exception as exc:  # noqa: BLE001
                if i == attempts - 1:
                    raise RuntimeError(f"Could not reach MongoDB: {exc}") from exc
                await asyncio.sleep(2)

    async def close(self) -> None:
        await self._client.close()

    async def create_session(self, doc: dict[str, Any]) -> None:
        await self._safe(self._sessions.insert_one(doc))

    async def push(self, session_id: str, array: str, item: dict[str, Any]) -> None:
        await self._safe(self._sessions.update_one({"_id": session_id}, {"$push": {array: item}}))

    async def set(self, session_id: str, fields: dict[str, Any]) -> None:
        await self._safe(self._sessions.update_one({"_id": session_id}, {"$set": fields}))

    @staticmethod
    async def _safe(coro) -> None:
        # A failed write is logged but must not crash a running experiment.
        try:
            await coro
        except Exception:  # noqa: BLE001
            log.exception("MongoDB write failed")
