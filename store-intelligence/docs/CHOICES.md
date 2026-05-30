# CHOICES.md — Key Design Decisions

## Decision 1 — Detection Model: YOLOv8n

### Options Considered
- **YOLOv8n** (nano) — fastest, lowest memory, runs on CPU
- **YOLOv8m** (medium) — better accuracy, requires GPU for real-time
- **YOLOv8x** (extra-large) — highest accuracy, impractical for local batch processing
- **RT-DETR** — transformer-based, state-of-the-art accuracy but slow inference
- **MediaPipe** — designed for mobile, not strong on occluded multi-person scenes

### What AI Suggested
Claude suggested YOLOv8m as a balance between speed and accuracy, noting that YOLOv8n may miss detections in crowded billing queue scenes. It also raised RT-DETR as worth benchmarking for the occlusion edge cases.

### What I Chose and Why
**YOLOv8n**, for two reasons:

First, the challenge spec says reviewers will run the pipeline on their own machines. YOLOv8n runs on CPU in real time — YOLOv8m requires a GPU to process 15fps without falling behind. Choosing a heavier model would break reproducibility for reviewers without a GPU.

Second, the Ultralytics `.track()` API integrates ByteTrack directly into YOLOv8, which means tracking is one function call rather than a separate pipeline stage. This integration is cleaner and less error-prone than wiring a separate tracker to a different detection library.

The accuracy trade-off is real: YOLOv8n will miss some detections in the crowded billing clip. I mitigated this by not suppressing low-confidence detections (the `confidence` field is always emitted) and by relying on ByteTrack's multi-frame association to recover missed detections across frames.

**If I had GPU access**, I would switch to YOLOv8m and evaluate whether the detection improvement on the occlusion and group-entry cases justifies the inference cost.

---

## Decision 2 — Event Schema Design

### Options Considered
**Option A — Flat schema per event type:** Separate schemas for ENTRY, ZONE_DWELL, BILLING events with different required fields per type. Strongly typed but requires union types and complex validation.

**Option B — Single schema with optional fields:** One `EventSchema` with `Optional` fields (`zone_id`, `queue_depth`) that are populated only when relevant. Simpler validation, some null fields on every event.

**Option C — Envelope + payload pattern:** A fixed envelope (`event_id`, `store_id`, `timestamp`) wrapping a typed payload. Most flexible but adds parsing complexity at ingest.

### What AI Suggested
Claude suggested Option A (per-event-type schemas) for strict type safety, arguing that a `ZONE_DWELL` event with a null `zone_id` is a schema violation that should be caught at the type level, not at runtime. It also suggested adding a `schema_version` field for forward compatibility.

### What I Chose and Why
**Option B — single schema with optional fields**, for three reasons:

The spec provides a single event schema with optional fields (`zone_id: null for ENTRY/EXIT events`). Following the spec's own design rather than redesigning it reduces the risk of schema mismatches with the scoring harness.

A single Pydantic model means a single database table, which makes queries in `metrics.py` and `funnel.py` straightforward — no joins across event-type-specific tables.

I did not add `schema_version` because it would require the scoring harness to handle it, and the spec does not mention it. Claude's suggestion was reasonable for a long-lived production API but overengineered for this challenge.

**Where I agreed with AI:** Using `UUID4` for `event_id` (Claude explicitly recommended this over sequential IDs for distributed idempotency) and using an `Enum` for `event_type` (catches typos at validation time rather than at query time).

---

## Decision 3 — API Storage Engine

### Options Considered
- **SQLite + aiosqlite** — zero external dependencies, single file, async-compatible
- **PostgreSQL + asyncpg** — production-grade, requires a Docker service, supports concurrent writes
- **Redis** — fast for real-time counters but not suitable as the primary event store
- **In-memory dict** — simplest, but loses all data on restart and fails the acceptance gate

### What AI Suggested
Claude recommended PostgreSQL, citing that SQLite has write serialisation issues under concurrent load and that a production retail system with 40 stores sending events simultaneously would hit SQLite's single-writer bottleneck quickly. It generated a `docker-compose.yml` with a PostgreSQL service as its first suggestion.

### What I Chose and Why
**SQLite with async SQLAlchemy**, and I disagree with Claude's recommendation for this context.

The challenge acceptance gate requires `docker compose up` to start everything with no manual steps. A PostgreSQL container adds a health check dependency — the app container must wait for PostgreSQL to be ready before starting. This adds complexity to `docker-compose.yml` and is a common source of submission failures (app starts before the database is ready, ingest returns 503, submission fails the gate).

SQLite with `aiosqlite` starts instantly, has no external dependency, and is sufficient for the event volumes in this challenge (5 stores, 20-minute clips, ~tens of thousands of events).

The code is deliberately structured so switching to PostgreSQL requires only changing the `DATABASE_URL` environment variable and the SQLAlchemy driver — `async_session`, models, and all query logic are identical. This is documented in `README.md`.

**Where Claude was right:** At 40 live stores sending events in real time, SQLite would be the first thing to break under concurrent writes. The correct production path is PostgreSQL with connection pooling via `asyncpg`. The current SQLite choice is an explicit trade-off for submission reliability, not a claim that SQLite is production-appropriate at scale.
