"""T4: simulated S3 store table constraints (AM-7)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.storage.models import SimObjectVersion

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def obj(**kw):
    fields = dict(
        bucket="b", key="documents/o/d", version_id="v1", is_delete_marker=False, data=b"abc", size_bytes=3,
        content_type="text/plain", etag='"x"', checksum_sha256="c", storage_class="STANDARD", last_modified=NOW,
    )
    fields.update(kw)
    return SimObjectVersion(**fields)


def marker(**kw):
    fields = dict(bucket="b", key="documents/o/d", version_id="m1", is_delete_marker=True, last_modified=NOW)
    fields.update(kw)
    return SimObjectVersion(**fields)


def insert(db, row):
    db.add(row)
    db.flush()


def violates(db, row, constraint):
    with pytest.raises(IntegrityError) as exc:
        insert(db, row)
    db.rollback()
    assert constraint in str(exc.value)


def test_object_and_marker_rows_accepted(db):
    insert(db, obj())
    insert(db, marker())
    insert(db, obj(version_id="v2", storage_class="GLACIER_IR"))


def test_version_id_unique(db):
    insert(db, obj())
    violates(db, obj(), "sim_object_versions_version_id_key")


@pytest.mark.parametrize(
    "row",
    [
        lambda: obj(size_bytes=4),  # size must match the bytes
        lambda: obj(data=None, size_bytes=0),
        lambda: obj(etag=None),
        lambda: obj(storage_class=None),
        lambda: marker(data=b"x", size_bytes=1),
        lambda: marker(storage_class="STANDARD"),
        lambda: marker(content_type="text/plain"),
    ],
)
def test_marker_and_object_shapes(db, row):
    violates(db, row(), "ck_sim_marker_shape")


def test_storage_class_values(db):
    violates(db, obj(storage_class="DEEP_ARCHIVE"), "ck_sim_storage_class")


def test_key_not_empty(db):
    violates(db, obj(key=""), "ck_sim_key_nonempty")


def test_data_column_is_deferred(db):
    insert(db, obj())
    db.expunge_all()
    row = db.query(SimObjectVersion).one()
    assert "data" not in row.__dict__
    assert row.data == b"abc"
