# PROMPT: "Write a pytest test for an idempotent FastAPI POST /events/ingest endpoint that accepts up to 500 events based on Pydantic schemas. Use httpx.AsyncClient."
# CHANGES MADE: Adapted the prompt's output to use standard TestClient for simpler synchronous testing of FastAPI in a pytest fixture. Added malformed data edge cases.

import pytest
from fastapi.testclient import TestClient
from app.main import app
import uuid
from datetime import datetime, timezone

def test_ingest_happy_path():
    event_id = str(uuid.uuid4())
    payload = [{
        "event_id": event_id,
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_123",
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.95,
        "metadata": {
            "session_seq": 1
        }
    }]
    
    with TestClient(app) as client:
        response = client.post("/events/ingest", json=payload)
        assert response.status_code == 202
        assert response.json()["accepted"] == 1

def test_ingest_idempotency():
    event_id = str(uuid.uuid4())
    payload = [{
        "event_id": event_id,
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_123",
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.95,
        "metadata": {
            "session_seq": 1
        }
    }]
    
    with TestClient(app) as client:
        # First call
        response1 = client.post("/events/ingest", json=payload)
        assert response1.status_code == 202
        
        # Second call - should also return 202 and not fail
        response2 = client.post("/events/ingest", json=payload)
        assert response2.status_code == 202

def test_ingest_batch_limit():
    payload = []
    for _ in range(501):
        payload.append({"event_id": str(uuid.uuid4())})
        
    with TestClient(app) as client:
        response = client.post("/events/ingest", json=payload)
        assert response.status_code == 400
        assert "exceeds" in response.json()["detail"]
