# Engineering Choices

## 1. Detection Model Selection

**Goal**: Achieve high accuracy on crowd detection, grace under partial occlusion, and maintain real-time performance.
**Options Considered**: 
1. YOLOv8 + ByteTrack
2. MediaPipe (Pose/Holistic)
3. RT-DETR
**AI Suggestion**: RT-DETR for superior transformer-based occlusion handling at the cost of higher latency.
**My Decision**: **YOLOv8n + ByteTrack**.
**Why**: RT-DETR is excellent but overkill for standard 1080p retail CCTV where FPS throughput is key (processing 3 streams per store, 40 stores = 120 streams). YOLOv8 nano combined with ByteTrack (which excels at associating tracks even when bounding boxes disappear due to occlusion) provides the perfect balance. ByteTrack keeps the ID alive during the occlusion events prevalent in crowded billing queues, satisfying the edge case requirement. I supplemented this with a mocked call to a VLM (like GPT-4V) specifically for the `is_staff` classification based on uniform recognition, keeping the heavy lifting off the main frame loop.

## 2. Event Schema Design Rationale

**Goal**: Ensure analytical queries (funnels, conversions) can be run quickly without complex JOINs on raw bounding box data.
**Options Considered**:
1. Raw Frame Events (emit every box on every frame).
2. Stateful Transition Events (`ZONE_ENTER`, `ZONE_EXIT`).
**AI Suggestion**: Suggestion 1: Raw Frame Events, let the API figure out the state.
**My Decision**: **Stateful Transition Events** (as adopted in `EventSchema`).
**Why**: Emitting frame-level data (e.g. 15fps * 20 visitors = 300 events/sec/camera) completely overwhelms the API and database. By moving the stateful transition logic to the edge tracker (Part A), the API only receives sparse events (`ENTRY`, `ZONE_ENTER`, `ZONE_EXIT`). This reduces network bandwidth by >99% and makes the metrics queries trivially simple.

## 3. API Storage & Architecture Choice

**Goal**: Production-grade ingest and real-time query performance.
**Options Considered**:
1. SQLite (local file).
2. PostgreSQL (relational).
3. MongoDB (NoSQL).
**AI Suggestion**: MongoDB to handle loosely structured `metadata`.
**My Decision**: **PostgreSQL via Async SQLAlchemy**.
**Why**: While NoSQL handles unstructured data well, the `EventSchema` is highly structured and relational. The analytical queries required (conversion funnels, distinct session counting) are natively optimized in PostgreSQL (using `COUNT(DISTINCT)`). Furthermore, PostgreSQL's JSONB column perfectly handles the flexible `metadata` payload while maintaining strict ACID compliance for the `event_id` idempotency constraint. I used `asyncpg` to ensure the FastAPI loop isn't blocked during heavy batch ingests.
