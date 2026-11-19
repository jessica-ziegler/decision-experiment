"""MongoDB persistence layer: the documents and update operators it sends."""

import pytest

from app.db import Store

pytestmark = pytest.mark.anyio


class RecordingCollection:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def insert_one(self, doc):
        self.calls.append(("insert_one", doc))
        if self.fail:
            raise ConnectionError("mongo is down")

    async def update_one(self, flt, update):
        self.calls.append(("update_one", flt, update))
        if self.fail:
            raise ConnectionError("mongo is down")


async def make_store(fail=False):
    store = Store("mongodb://localhost:1", "test")  # client is lazy: nothing connects
    store._sessions = RecordingCollection(fail)
    return store


async def test_store_sends_expected_operations():
    store = await make_store()
    await store.create_session({"_id": "s1", "messages": []})
    await store.push("s1", "messages", {"text": "hi"})
    await store.set("s1", {"status": "completed"})
    assert store._sessions.calls == [
        ("insert_one", {"_id": "s1", "messages": []}),
        ("update_one", {"_id": "s1"}, {"$push": {"messages": {"text": "hi"}}}),
        ("update_one", {"_id": "s1"}, {"$set": {"status": "completed"}}),
    ]
    await store.close()


async def test_failed_writes_are_logged_not_raised(caplog):
    store = await make_store(fail=True)
    await store.push("s1", "votes", {"target": "Player A"})  # must not raise mid-experiment
    assert "MongoDB write failed" in caplog.text
    await store.close()
