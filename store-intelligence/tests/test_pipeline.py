# PROMPT: "Write pytest tests for the SessionTracker logic, covering zone interactions,
# dwell time emissions, staff exclusion, and re-entry handling."
#
# CHANGES MADE:
# - Refined the polygon coordinates to match our test grid.
# - Added edge case tests for missing tracks and network retries for the emitter.

import pytest
from fastapi.testclient import TestClient
from app.main import app
import uuid
from datetime import datetime, timezone
import httpx
from pipeline.tracker import SessionTracker
from pipeline.emit import EventEmitter

@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client

def test_ingest_happy_path(client):
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
    response = client.post("/events/ingest", json=payload)
    assert response.status_code == 202
    assert response.json()["accepted"] == 1

def test_ingest_idempotency(client):
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
    client.post("/events/ingest", json=payload)
    response = client.post("/events/ingest", json=payload)
    assert response.status_code == 202

def test_ingest_batch_limit(client):
    payload = [{"event_id": str(uuid.uuid4())} for _ in range(501)]
    response = client.post("/events/ingest", json=payload)
    assert response.status_code == 400
    assert "exceeds" in response.json()["detail"]

def test_metrics_and_heatmap(client):
    # Ingest test data
    store_id = "STORE_TEST_METRICS"
    visitor_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM1",
            "visitor_id": visitor_id,
            "event_type": "ZONE_ENTER",
            "timestamp": ts,
            "zone_id": "SKINCARE",
            "confidence": 0.9,
            "metadata": {"session_seq": 1}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM1",
            "visitor_id": visitor_id,
            "event_type": "ZONE_DWELL",
            "timestamp": ts,
            "zone_id": "SKINCARE",
            "dwell_ms": 35000,
            "confidence": 0.9,
            "metadata": {"session_seq": 2}
        }
    ]
    client.post("/events/ingest", json=payload)
    
    # Check metrics
    m_res = client.get(f"/stores/{store_id}/metrics")
    assert m_res.status_code == 200
    data = m_res.json()
    assert data["unique_visitors"] >= 1
    assert "SKINCARE" in data["avg_dwell_per_zone"]
    
    # Check heatmap
    h_res = client.get(f"/stores/{store_id}/heatmap")
    assert h_res.status_code == 200
    h_data = h_res.json()
    assert "zones" in h_data
    zones_list = h_data["zones"]
    skincare_zone = next((z for z in zones_list if z["zone_id"] == "SKINCARE"), None)
    assert skincare_zone is not None
    assert skincare_zone["visit_frequency"] >= 0

def test_anomalies(client):
    store_id = "STORE_TEST_ANO"
    ts = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM1",
            "visitor_id": str(uuid.uuid4()),
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": ts,
            "zone_id": "BILLING",
            "confidence": 0.9,
            "metadata": {"session_seq": 1, "queue_depth": 15}
        }
    ]
    client.post("/events/ingest", json=payload)
    
    res = client.get(f"/stores/{store_id}/anomalies")
    assert res.status_code == 200
    anomalies = res.json()["anomalies"]
    assert any(a["type"] == "BILLING_QUEUE_SPIKE" and a["severity"] == "CRITICAL" for a in anomalies)

def test_tracker_logic():
    tracker = SessionTracker()
    zones = [
        {"zone_id": "SKINCARE", "polygon": [[0,0], [500,0], [500,500], [0,500]]},
        {"zone_id": "BILLING", "polygon": [[1000,0], [1500,0], [1500,500], [1000,500]]}
    ]
    
    # Test point in polygon
    z1 = tracker._get_zone_for_point(250, 250, zones)
    assert z1 == "SKINCARE"
    z2 = tracker._get_zone_for_point(1200, 250, zones)
    assert z2 == "BILLING"
    z3 = tracker._get_zone_for_point(700, 700, zones)
    assert z3 is None
    
    # Test update and events
    boxes = [[100, 100, 200, 200]]
    track_ids = [100]
    confidences = [0.9]
    events = tracker.update(0, 10, boxes, track_ids, confidences, "S1", "C1", zones)
    # Should emit ENTRY and ZONE_ENTER
    event_types = [e["event_type"] for e in events]
    assert "ENTRY" in event_types
    assert "ZONE_ENTER" in event_types
    
    # Test staff check
    assert events[0]["is_staff"] == True # 100 % 10 == 0

    # Test dwell
    events2 = tracker.update(400, 10, boxes, track_ids, confidences, "S1", "C1", zones) # 40s later
    event_types2 = [e["event_type"] for e in events2]
    assert "ZONE_DWELL" in event_types2
    
    # Test missing track / EXIT
    events3 = tracker.update(800, 10, [], [], [], "S1", "C1", zones) # 40s later
    event_types3 = [e["event_type"] for e in events3]
    assert "EXIT" in event_types3
    assert "ZONE_EXIT" in event_types3
    
    # Test REENTRY
    events4 = tracker.update(900, 10, boxes, track_ids, confidences, "S1", "C1", zones)
    event_types4 = [e["event_type"] for e in events4]
    assert "REENTRY" in event_types4

def test_emitter_retry():
    class MockResponse:
        def raise_for_status(self):
            pass

    emitter = EventEmitter("http://test.url", batch_size=1)
    
    call_count = [0]
    def mock_post(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Network error")
        return MockResponse()
        
    emitter.client.post = mock_post
    emitter.queue_events([{"event_id": str(uuid.uuid4()), "dummy": "data"}])
    
    assert call_count[0] == 2
