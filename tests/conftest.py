import uuid

import pytest

from tracebrain import db, schema


@pytest.fixture(scope="session")
def falkor():
    try:
        db.ping()
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable ({e}); run `docker compose up -d`")


@pytest.fixture
def temp_tenant(falkor):
    tenant = f"test_{uuid.uuid4().hex[:8]}"
    schema.apply(tenant)
    yield tenant
    schema.drop(tenant)
