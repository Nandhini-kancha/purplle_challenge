# PROMPT: "Write pytest tests for a FastAPI endpoint POST /events/ingest 
# that validates: idempotency by event_id, partial success on malformed 
# events, batch size limit of 500, and returns structured errors"
#
# CHANGES MADE: 
# - AI generated happy path only, I added edge cases for empty store
# - Changed assertion on error format to match our actual Pydantic response
# - Added re-entry test which AI missed entirely

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db, Event


# ------------------------------------------------------------------
# Test Database
# ------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def build_event(
    *,
    event_type="ENTRY",
    event_id=None,
    visitor_id="visitor-1",
    store_id="store-1",
    is_staff=False,
    queue_depth=None,
):
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": "cam-1",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "zone_id": "zone-a",
        "dwell_ms": 1000,
        "is_staff": is_staff,
        "confidence": 0.95,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": "electronics",
            "session_seq": 1,
        },
    }


# ------------------------------------------------------------------
# 1. Idempotency
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_idempotency_same_event_inserted_once(client):
    event_id = str(uuid.uuid4())

    payload = [
        build_event(event_id=event_id),
        build_event(event_id=event_id),  # duplicate
    ]

    response = await client.post("/events/ingest", json=payload)

    assert response.status_code == 202

    body = response.json()

    assert body["accepted"] == 2
    assert body["inserted"] == 1
    assert body["failed"] == 0


# ------------------------------------------------------------------
# 2. Partial Success
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_partial_success(client):
    valid_event = build_event()

    malformed_event = {
        "store_id": "store-1",
        "event_type": "ENTRY",
        # missing required fields
    }

    response = await client.post(
        "/events/ingest",
        json=[valid_event, malformed_event],
    )

    assert response.status_code == 202

    body = response.json()

    assert body["accepted"] == 1
    assert body["inserted"] == 1
    assert body["failed"] == 1
    assert len(body["errors"]) == 1


# ------------------------------------------------------------------
# 3. Batch Limit
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_batch_limit_500(client):
    payload = [build_event() for _ in range(501)]

    response = await client.post(
        "/events/ingest",
        json=payload,
    )

    assert response.status_code == 400
    assert "Batch size exceeds 500 events" in response.json()["detail"]


# ------------------------------------------------------------------
# 4. Empty Batch
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_empty_event_list(client):
    response = await client.post(
        "/events/ingest",
        json=[],
    )

    assert response.status_code == 202

    body = response.json()

    assert body["accepted"] == 0
    assert body["inserted"] == 0
    assert body["failed"] == 0


# ------------------------------------------------------------------
# 5. Metrics - No Events
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_returns_zero_when_no_events_exist(client):
    response = await client.get("/stores/store-empty/metrics")

    assert response.status_code == 200

    body = response.json()

    # Adjust keys to match your implementation
    assert body["unique_visitors"] == 0


# ------------------------------------------------------------------
# 6. Metrics Excludes Staff
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_excludes_staff_events(client):
    payload = [
        build_event(
            visitor_id="customer-1",
            store_id="store-2",
            event_type="ENTRY",
            is_staff=False,
        ),
        build_event(
            visitor_id="staff-1",
            store_id="store-2",
            event_type="ENTRY",
            is_staff=True,
        ),
    ]

    ingest = await client.post(
        "/events/ingest",
        json=payload,
    )

    assert ingest.status_code == 202

    response = await client.get("/stores/store-2/metrics")

    assert response.status_code == 200

    body = response.json()

    # Only customer should count
    assert body["unique_visitors"] == 1


# ------------------------------------------------------------------
# 7. Funnel - Reentry Should Not Double Count
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_funnel_reentry_does_not_double_count_visitor(client):
    payload = [
        build_event(
            visitor_id="visitor-x",
            store_id="store-3",
            event_type="ENTRY",
        ),
        build_event(
            visitor_id="visitor-x",
            store_id="store-3",
            event_type="REENTRY",
        ),
    ]

    ingest = await client.post(
        "/events/ingest",
        json=payload,
    )

    assert ingest.status_code == 202

    response = await client.get("/stores/store-3/funnel")

    assert response.status_code == 200

    body = response.json()

    # Unique visitor count should remain 1
    assert body["funnel"][0]["count"] == 1


# ------------------------------------------------------------------
# 8. Billing Queue Spike Anomaly
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anomalies_returns_billing_queue_spike(client):
    payload = [
        build_event(
            event_type="BILLING_QUEUE_JOIN",
            queue_depth=6,
        )
    ]

    ingest = await client.post(
        "/events/ingest",
        json=payload,
    )

    assert ingest.status_code == 202

    response = await client.get("/stores/store-1/anomalies")

    assert response.status_code == 200

    body = response.json()

    assert "anomalies" in body
    assert len(body["anomalies"]) > 0

    anomaly_types = [
        item["type"] if isinstance(item, dict) else item
        for item in body["anomalies"]
    ]

    assert "BILLING_QUEUE_SPIKE" in anomaly_types
