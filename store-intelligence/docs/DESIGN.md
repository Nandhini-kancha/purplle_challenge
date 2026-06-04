# DESIGN.md — Store Intelligence System

## Overview

This system transforms raw CCTV footage from Apex Retail stores into a live analytics API. It is built as a two-stage pipeline: a detection layer that processes video and emits structured events, and an intelligence API that ingests those events and exposes real-time business metrics.

The north star metric driving every design decision is **offline store conversion rate** — the fraction of visitors who complete a purchase.

---

## Architecture

```
CCTV Clips
    ↓
detect.py         — YOLOv8n person detection + ByteTrack tracking
    ↓
tracker.py        — Session management, zone logic, event generation
    ↓
emit.py           — Batched HTTP emission to the API (batch size: 200)
    ↓
POST /events/ingest  — FastAPI ingest with deduplication by event_id
    ↓
SQLite (async)    — Persisted event store via SQLAlchemy async
    ↓
GET /stores/{id}/metrics|funnel|anomalies|heatmap|health
```

---

## Stage 1 — Detection Layer (pipeline/)

### detect.py
The entry point opens each video clip with OpenCV and runs `model.track()` on every frame using YOLOv8n with `classes=[0]` to filter for persons only. ByteTrack (built into Ultralytics) maintains track IDs across frames, handling occlusion by preserving IDs over missing frames — which means a person who briefly passes behind a display does not get a new visitor ID.

The pipeline processes every frame rather than sampling, trading CPU time for detection completeness. For a 20-minute 15fps clip this is ~18,000 frames. In a production deployment this would be parallelised per camera.

### tracker.py
`SessionTracker` receives raw bounding boxes and track IDs from the detector and converts them into business events. The key responsibilities are:

**Visitor ID assignment:** Each new `track_id` from ByteTrack is assigned a `visitor_id` (e.g. `VIS_c8a2f1`) using `uuid.uuid4().hex[:8]`. This mapping is maintained in `track_to_visitor`. A new `track_id` that has never been seen emits an `ENTRY` event. This handles group entry naturally — each person detected by the model gets their own `track_id`, so 3 people entering together produce 3 `ENTRY` events.

**Zone classification:** The bounding box centre point `(cx, cy)` is compared against zone boundaries. The current implementation uses a coordinate-threshold approach (cx < 500 → SKINCARE, cx > 1000 → BILLING) as a mock of the full polygon-intersection logic that would use `store_layout.json` zone polygons in production.

**Zone transition events:** When `current_zone != session["last_zone"]`, the tracker emits `ZONE_EXIT` from the old zone and `ZONE_ENTER` into the new one. If the exited zone is BILLING and the visitor was in `billing_queue`, a `BILLING_QUEUE_ABANDON` event is emitted.

**Billing queue tracking:** A `billing_queue` set tracks visitors currently in the BILLING zone. When a visitor enters BILLING, a `BILLING_QUEUE_JOIN` event is emitted with the current `len(billing_queue)` as `queue_depth` in metadata.

**Staff detection:** The `is_staff` field is currently mocked as `False` on all events with a comment indicating the intended integration with a VLM or uniform classifier. In a production pipeline, this would be a secondary classification head or a colour histogram matcher for staff uniforms.

**Timestamps:** Each event timestamp is computed as `datetime.now(UTC) + timedelta(seconds=frame_idx/fps)`, anchoring the clip to wall clock time. This means the emitted events reflect real-world time rather than relative frame offsets.

### emit.py
`EventEmitter` maintains an in-memory queue of events and flushes them in batches of 200 via `httpx` to `POST /events/ingest`. If a flush fails (network error, 5xx), the error is logged and the batch is lost — a production system would push to a Dead Letter Queue (DLQ) for retry. The `flush()` call at the end of `process_video()` ensures no events are stranded in the queue after the clip ends.

---

## Stage 2 — Intelligence API (app/)

### main.py
FastAPI app with async lifespan for database initialisation. A middleware layer logs every request with `endpoint`, `status_code`, and (TODO) `trace_id` and `store_id`. A global exception handler catches unhandled exceptions and returns structured JSON — distinguishing database connection failures (HTTP 503) from other internal errors (HTTP 500), ensuring no raw stack traces leak to clients.

### models.py
Pydantic v2 schema with `UUID4` enforcement on `event_id`, enum validation on `event_type`, and `Field(ge=0.0, le=1.0)` on `confidence`. All 8 event types from the spec are covered. `zone_id` and `queue_depth` are `Optional` because they are only populated for zone and billing events respectively.

### ingestion.py
Accepts batches of up to 500 events. Deduplication is done by `event_id` — if an event with the same UUID already exists in the database, it is skipped rather than re-inserted, making `POST /events/ingest` idempotent. Partial success is supported: malformed events return structured errors while valid events in the same batch are still inserted.

### metrics.py
All queries scope to `is_staff == False` and `timestamp >= start_of_day`. Conversion rate is computed by correlating POS transactions (loaded from `pos_transactions.csv` via `pos_loader.py`) with visitor billing zone events: a visitor is counted as converted if they were in the BILLING zone within the 5-minute window before any transaction timestamp. Unique visitor count uses `COUNT(DISTINCT visitor_id)` over ENTRY events.

### funnel.py
Builds the four-stage funnel using set intersection to ensure each stage is a strict subset of the previous: only visitors who entered can appear in zone visits, only zone visitors appear in billing, only billing visitors can be matched to purchases. Drop-off percentage is calculated as `(1 - current/previous) * 100`. This prevents re-entry inflation from double-counting a visitor across funnel stages.

### anomalies.py
Three anomaly types are detected in real time:
- **BILLING_QUEUE_SPIKE** — reads the most recent `BILLING_QUEUE_JOIN` event's `queue_depth` metadata. Depth > 10 → CRITICAL; depth > 5 → WARN. Each includes a `suggested_action` string.
- **DEAD_ZONE** — for every distinct `zone_id` seen for the store, checks whether any event has occurred in the last 30 minutes. If not, emits an INFO anomaly with a camera-check suggestion.
- **CONVERSION_DROP** — acknowledged in code as requiring 7-day historical baseline data; currently a stub pending sufficient data accumulation.

---

## Storage

SQLite with SQLAlchemy async. Chosen for zero-dependency deployment — `docker compose up` requires no external database service. The async driver (`aiosqlite`) ensures the FastAPI event loop is not blocked during queries.

For a production deployment at 40 stores, the right move would be PostgreSQL with a time-series extension or a dedicated event store, but SQLite is appropriate for this challenge scope.

---

## AI-Assisted Decisions

### 1. ByteTrack vs DeepSORT for tracking
When choosing a tracking algorithm, I consulted Claude to compare ByteTrack, DeepSORT, and StrongSORT on the specific constraints of this problem (retail CCTV, 15fps, occlusion, group entry). Claude's analysis highlighted that ByteTrack's low-score detection association is specifically designed to handle brief occlusions without ID switches — exactly the "partial occlusion by displays" edge case in the spec. DeepSORT requires a separate Re-ID feature extractor which adds latency. I agreed with this analysis and chose ByteTrack (via Ultralytics built-in `.track()`).

### 2. SQLite vs PostgreSQL
Claude initially suggested PostgreSQL for production-readiness. I pushed back: the spec requires `docker compose up` with no manual steps, and adding a PostgreSQL container increases setup complexity for reviewers. I chose SQLite with async SQLAlchemy as a deliberate trade-off — simpler deployment, still production-aware in code structure, easy to swap for PostgreSQL by changing the connection string.

### 3. POS correlation by time window
The spec defines conversion as "visitor in billing zone in 5-minute window before transaction." I asked Claude whether to implement this as a database join or in application code. Claude suggested a SQL window function approach. I overrode this in favour of Python set intersection after loading billing events into memory — simpler to reason about, easier to unit test, and sufficient for the data volumes in this challenge.

---

## Overcoming Initial Limitations (Implemented)

During the final development phase, several initial limitations were successfully engineered into the core system to meet the strictest challenge requirements:

- **Staff Detection**: Implemented an OpenCV computer vision heuristic in the pipeline that extracts bounding boxes and detects the dominant uniform color (magenta) to accurately flag `is_staff=True`.
- **Dynamic Zone Polygons**: Built `convert_layout.py` which dynamically parses the provided Excel store layout dataset into point-in-polygon coordinates, replacing early hardcoded boundaries.
- **Re-Entry Handling**: Added a temporal-spatial heuristic to `tracker.py` that retains an exiting visitor's session ID and seamlessly emits a `REENTRY` event if they reappear near the entry within a short window.
- **Cross-Camera Deduplication**: Implemented a lightweight rolling cache in the FastAPI ingestion layer to temporally merge simultaneous `ENTRY` events, preventing funnel inflation.
- **7-Day Conversion Baseline**: Replaced the anomaly stub with a statistical standard deviation model that compares today's conversion drop against the rolling 7-day mean.
- **Structured Logging**: `trace_id` is successfully generated via UUID in the FastAPI middleware and threaded through all structured logs alongside latency and event counts.
