from fastapi import APIRouter, Depends, HTTPException, status
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
async def ingest_events(events: List[Dict[str, Any]], db: AsyncSession = Depends(get_db)):
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

    if parsed_events:
        # Idempotent insert for postgres
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
