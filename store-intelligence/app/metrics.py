from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, cast, Integer
from sqlalchemy.orm import load_only
from datetime import datetime, timedelta, timezone
from app.database import get_db, Event
from app.pos_loader import get_pos_transactions
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/stores/{store_id}/metrics")
async def get_store_metrics(store_id: str, db: AsyncSession = Depends(get_db)):
    # Calculate "today" UTC (For a real retail app, store timezone matters, assuming UTC here)
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Base query for today, excluding staff
    base_query = select(Event).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.is_staff == False
    )

    # Unique visitors
    uv_query = select(func.count(distinct(Event.visitor_id))).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.is_staff == False
    )
    uv_result = await db.execute(uv_query)
    unique_visitors = uv_result.scalar() or 0

    # Avg dwell per zone
    dwell_query = select(
        Event.zone_id, 
        func.avg(Event.dwell_ms)
    ).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.is_staff == False,
        Event.event_type.in_(['ZONE_DWELL', 'ZONE_EXIT']),
        Event.zone_id.isnot(None)
    ).group_by(Event.zone_id)
    dwell_result = await db.execute(dwell_query)
    avg_dwell_per_zone = {row[0]: float(row[1]) for row in dwell_result if row[1] is not None}

    # Queue depth (current)
    # Calculate current queue depth by checking the latest queue-related event for each visitor
    q_events_query = select(Event.visitor_id, Event.event_type, Event.timestamp).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type.in_(['BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON', 'EXIT', 'ZONE_EXIT'])
    )
    q_events_result = await db.execute(q_events_query)
    
    visitor_status = {}
    for v_id, e_type, ts in q_events_result:
        # For ZONE_EXIT, we only care if they are exiting the BILLING zone.
        # But for simplicity in this fallback, any exit event resets their queue status.
        if v_id not in visitor_status or ts > visitor_status[v_id]['ts']:
            visitor_status[v_id] = {'type': e_type, 'ts': ts}
            
    current_queue_depth = sum(1 for status in visitor_status.values() if status['type'] == 'BILLING_QUEUE_JOIN')

    # Abandonment Rate = BILLING_QUEUE_ABANDON / (BILLING_QUEUE_JOIN)
    q_join_query = select(func.count(Event.event_id)).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type == 'BILLING_QUEUE_JOIN'
    )
    q_abandon_query = select(func.count(Event.event_id)).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type == 'BILLING_QUEUE_ABANDON'
    )
    q_join_count = (await db.execute(q_join_query)).scalar() or 0
    q_abandon_count = (await db.execute(q_abandon_query)).scalar() or 0
    abandonment_rate = (q_abandon_count / q_join_count) if q_join_count > 0 else 0.0

    # Conversion Rate
    # A visitor who was in the billing zone in the 5-minute window before a transaction timestamp counts as converted.
    transactions = get_pos_transactions(store_id)
    # Filter transactions to today
    today_tx = [t for t in transactions if t['timestamp'] >= start_of_day]
    
    # Get all billing zone events for today
    billing_events_query = select(Event.visitor_id, Event.timestamp).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.zone_id == 'BILLING',  # assuming zone_id='BILLING' or event_type='BILLING_QUEUE_JOIN'
        Event.is_staff == False
    )
    billing_events_result = await db.execute(billing_events_query)
    billing_events = billing_events_result.all()

    converted_visitors = set()
    for tx in today_tx:
        tx_time = tx['timestamp']
        window_start = tx_time - timedelta(minutes=5)
        
        # Find any visitor in billing zone within [window_start, tx_time]
        for v_id, b_time in billing_events:
            # We assume b_time has tzinfo matching tx_time
            if window_start <= b_time <= tx_time:
                converted_visitors.add(v_id)

    conversion_rate = 0.0
    if unique_visitors > 0:
        conversion_rate = len(converted_visitors) / unique_visitors

    return {
        "unique_visitors": unique_visitors,
        "conversion_rate": conversion_rate,
        "avg_dwell_per_zone": avg_dwell_per_zone,
        "queue_depth": current_queue_depth,
        "abandonment_rate": abandonment_rate
    }

