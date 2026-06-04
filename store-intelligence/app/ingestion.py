from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Any
from app.models import EventSchema
from app.database import get_db, Event
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/events/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_events(events: List[Dict[str, Any]], request: Request, db: AsyncSession = Depends(get_db)):
    request.state.event_count = len(events)
    if len(events) > 500:
        raise HTTPException(status_code=400, detail="Batch size exceeds 500 events")

    successful_inserts = 0
    errors = []

    # Validating parsing
    parsed_events = []
    for idx, raw_event in enumerate(events):
        try:
            event_obj = EventSchema(**raw_event)
            parsed_events.append(event_obj)
        except Exception as e:
            errors.append({"index": idx, "event_id": raw_event.get("event_id"), "error": str(e)})

# Simple in-memory cache for cross-camera deduplication
recent_entries = {}
visitor_remapping = {}

    if parsed_events:
        # Cross-camera deduplication: temporally merge simultaneous entries
        global recent_entries, visitor_remapping
        for e in parsed_events:
            # Apply any known remapping
            if e.visitor_id in visitor_remapping:
                e.visitor_id = visitor_remapping[e.visitor_id]

            if e.event_type.value == "ENTRY":
                store_entries = recent_entries.setdefault(e.store_id, [])
                
                # Prune old entries (> 10 seconds)
                store_entries[:] = [x for x in store_entries if (e.timestamp - x["timestamp"]).total_seconds() < 10]
                
                merged = False
                for prev_entry in store_entries:
                    # If an entry happened within 2 seconds, assume it's the same person cross-camera
                    if abs((e.timestamp - prev_entry["timestamp"]).total_seconds()) <= 2.0:
                        visitor_remapping[e.visitor_id] = prev_entry["visitor_id"]
                        e.visitor_id = prev_entry["visitor_id"]
                        merged = True
                        break
                
                if not merged:
                    store_entries.append({"visitor_id": e.visitor_id, "timestamp": e.timestamp})

        # Idempotent insert for SQLite
        stmt = insert(Event).values([
            {
                "event_id": str(e.event_id),
                "store_id": e.store_id,
                "camera_id": e.camera_id,
                "visitor_id": e.visitor_id,
                "event_type": e.event_type.value,
                "timestamp": e.timestamp,
                "zone_id": e.zone_id,
                "dwell_ms": e.dwell_ms,
                "is_staff": e.is_staff,
                "confidence": e.confidence,
                "metadata_": e.metadata.model_dump()
            } for e in parsed_events
        ])
        
        # Do nothing on conflict to ensure idempotency
        stmt = stmt.on_conflict_do_nothing(index_elements=['event_id'])
        
        try:
            result = await db.execute(stmt)
            await db.commit()
            successful_inserts = result.rowcount
        except Exception as e:
            await db.rollback()
            logger.error(f"Database error during ingestion: {e}")
            raise HTTPException(status_code=503, detail="Database unavailable")

    response_body = {
        "accepted": len(parsed_events),
        "inserted": successful_inserts, # Note: rows ignored due to idempotency don't increment rowcount
        "failed": len(errors),
        "errors": errors
    }
    
    if errors:
        # Return 207 Multi-Status if partial success (though 202 is acceptable)
        pass 

    return response_body
