"""Fixtures shared by the integration tests of T14 (recommendations)."""

import uuid

import pytest

from app.models import Document
from tests.integration.test_recommendations import BIG, add_access, backdate, set_class


@pytest.fixture
def alice(auth_headers):
    return auth_headers("alice@example.com")


@pytest.fixture
def cold(upload, alice, db):
    """Factory: an uploaded document made old and quiet enough for a given rule."""

    def _make(name="cold.txt", rule="R3", fill=b"a"):
        doc = upload(alice, name, fill * BIG).json()
        backdate(db, doc["id"], days=120)
        user_id = db.get(Document, uuid.UUID(doc["id"])).owner_id
        if rule == "R3":  # STANDARD, 1 access 40 days ago, idle 40 days
            add_access(db, doc["id"], user_id, days_ago=40)
        elif rule == "R1":  # STANDARD_IA for 60 days, 4 accesses in the last 30 days
            set_class(db, doc["id"], "STANDARD_IA", days_ago=60)
            for d in (1, 2, 3, 4):
                add_access(db, doc["id"], user_id, days_ago=d)
        # R2: no accesses at all, older than 90 days
        return doc

    return _make
