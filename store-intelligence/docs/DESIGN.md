# Architecture Design

## Overview
The Store Intelligence platform is designed to be a highly available, robust system bridging raw CV outputs to business analytics. We use an event-driven ingestion approach rather than polling video states. The detection layer acts as an edge publisher, computing stateful visitor transitions and generating stateless events. The API acts as a centralized consumer, validating, storing, and aggregating these events in real time.

### Component Bounded Contexts
1. **Edge Node (Pipeline)**
   - Responsible for tracking (YOLOv8 + ByteTrack).
   - Responsible for zone management (polygon point tests).
   - Emits structured schemas in batches to reduce network overhead.
2. **Intelligence Core (FastAPI)**
   - Responsible for ensuring idempotent ingestion.
   - Provides live materialized views via SQL (metrics, funnel, anomalies).
   - Abstracts underlying database choices.

## AI-Assisted Decisions

1. **Schema Event Idempotency Strategy**
   - *AI Suggestion*: Use a cache layer like Redis to filter out duplicate `event_id` keys before hitting the database.
   - *My Decision*: **Overridden**. For a multi-store pipeline, a centralized Redis introduces unnecessary infrastructure complexity (violating the spirit of a lean 5-command setup) and potential race conditions under high ingest loads. I chose to use the PostgreSQL `ON CONFLICT DO NOTHING` native constraint. It provides strict ACID guarantees for idempotency at zero additional infrastructure cost.

2. **Dwell Time Computation**
   - *AI Suggestion*: Have the API calculate `dwell_ms` by correlating `ZONE_ENTER` and `ZONE_EXIT` events dynamically during the `/metrics` GET request.
   - *My Decision*: **Overridden**. Computing durations dynamically over thousands of unbounded events per store is an O(N) operation per request and doesn't scale. Instead, I moved stateful tracking to the edge (`tracker.py`), which emits `ZONE_EXIT` with pre-computed `dwell_ms` or periodic `ZONE_DWELL` events. The API now simply averages the `dwell_ms` field—an O(1) aggregation.

3. **Anomaly Detection Thresholds**
   - *AI Suggestion*: Use Z-score or standard deviation over a 7-day rolling window to flag anomalies.
   - *My Decision*: **Agreed**. While the challenge test data doesn't provide 7 days of history, framing the architecture to support standard deviation rather than hardcoded thresholds (like >10 queue depth) is critical for production. I implemented hardcoded fallbacks for the challenge demo but the design easily extends to dynamic baselines.
