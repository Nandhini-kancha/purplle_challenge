from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from app.database import get_db, Event
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    # 1. DB connection check
    status = "healthy"
    try:
        await db.execute(select(1))
    except Exception as e:
        logger.error(f"Healthcheck DB Error: {e}")
        status = "degraded"

    # 2. Check STALE_FEED (>10 min lag for any store)
    # Get max timestamp per store
    now = datetime.now(timezone.utc)
    stale_stores = []
    
    # We will just get the absolute latest event timestamp for simplicity in this demo.
    latest_event_query = select(Event.timestamp, Event.store_id).order_by(Event.timestamp.desc()).limit(1)
    
    try:
        result = await db.execute(latest_event_query)
        latest_event = result.first()
        
        if latest_event:
            last_ts, store_id = latest_event
            # Ensure last_ts is timezone-aware
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
                
            lag = (now - last_ts).total_seconds() / 60
            if lag > 10:
                stale_stores.append(store_id)
                status = "warning"
        
        return {
            "status": status,
            "stale_feeds": stale_stores,
            "last_event": latest_event[0].isoformat() if latest_event else None
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e)
        }
